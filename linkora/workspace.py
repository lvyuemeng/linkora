"""
workspace.py — Workspace registry, metadata, and path resolution.

Design invariants
─────────────────
1. WorkspaceMetadata stores ONLY: name, description, created_at.
   No filesystem paths are persisted — they are always computed.

2. WorkspacePaths is a pure value object computed from (data_root, name).
   It is never written to disk.  Renaming a workspace or changing the
   data root never requires updating stored paths.

3. WorkspaceStore is the single authoritative write point for the
   workspace registry (workspaces.json) and per-workspace metadata
   (workspace/<n>/workspace.json).
   Both files are managed exclusively by CLI commands — NOT user-editable.

4. get_data_root() is the single canonical source for the data directory.
   All code that needs the data root must call this function — no inline
   platform detection elsewhere in the codebase.

Registry layout (CLI-managed, not user-editable)
─────────────────────────────────────────────────
<data_root>/
└── workspace/
    ├── workspaces.json          ← name list + default
    ├── default/
    │   ├── workspace.json       ← name, description, created_at only
    │   ├── papers/
    │   ├── logs/
    │   ├── index.db
    │   └── vectors.faiss
    └── ml/
        └── …
"""

from __future__ import annotations

import copy
import json
import os
import platform
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Data root  (single source of truth for the whole codebase)
# ---------------------------------------------------------------------------


def get_data_root() -> Path:
    """
    Return the platform-appropriate linkora data directory.

    Override via the ``LINKORA_ROOT`` environment variable.

    Platform defaults
    ─────────────────
    Windows   %APPDATA%/linkora
    macOS     ~/Library/Application Support/linkora
    Linux     $XDG_DATA_HOME/linkora  (default: ~/.local/share/linkora)
    """
    env_root = os.environ.get("LINKORA_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    home = Path.home()
    system = platform.system()

    if system == "Windows":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

    return base / "linkora"


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path, default: dict | None = None) -> dict:
    # deepcopy — NOT shallow copy — so that callers who mutate the returned
    # dict (e.g. appending to the "workspaces" list) never corrupt the
    # module-level _REGISTRY_DEFAULT constant.  Using .copy() here is a
    # latent bug: the nested "workspaces" list would be shared across all
    # callers and mutated by _ensure_in_registry, poisoning every subsequent
    # call that hits the default (e.g. when the registry file does not yet
    # exist on a fresh tmp_path in tests).
    if not path.exists():
        return copy.deepcopy(default) if default else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default) if default else {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# WorkspaceMetadata — stored in workspace/<n>/workspace.json
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceMetadata:
    """
    Persistent identity data for a workspace.

    Deliberately minimal: name + description + created_at.
    Filesystem paths are NEVER stored here — see WorkspacePaths.
    """

    name: str
    description: str = ""
    created_at: str = ""

    @staticmethod
    def create(name: str) -> "WorkspaceMetadata":
        return WorkspaceMetadata(
            name=name,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(data: dict) -> "WorkspaceMetadata":
        # Silently ignore legacy fields (root, is_default) that older
        # versions may have written.
        return WorkspaceMetadata(
            name=data.get("name", ""),
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# WorkspacePaths — computed at runtime, never persisted
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkspacePaths:
    """
    All filesystem paths for a single workspace.

    Computed purely from (data_root, name) — never stored anywhere.
    Changing data_root or renaming a workspace automatically produces
    correct paths without any migration of stored path strings.
    """

    data_root: Path
    name: str

    @property
    def workspace_dir(self) -> Path:
        return self.data_root / "workspace" / self.name

    @property
    def papers_dir(self) -> Path:
        return self.workspace_dir / "papers"

    @property
    def index_db(self) -> Path:
        return self.workspace_dir / "index.db"

    @property
    def vectors_file(self) -> Path:
        return self.workspace_dir / "vectors.faiss"

    @property
    def metadata_file(self) -> Path:
        return self.workspace_dir / "workspace.json"

    def log_file(self, filename: str) -> Path:
        """Resolve a log filename relative to the workspace logs/ directory."""
        return self.workspace_dir / "logs" / filename

    def metrics_db(self, filename: str) -> Path:
        """Resolve a metrics DB filename relative to the workspace directory."""
        return self.workspace_dir / filename

    def ensure_dirs(self) -> None:
        """Create all required workspace directories."""
        self.papers_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / "logs").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Registry schema default
# ---------------------------------------------------------------------------

_REGISTRY_DEFAULT: dict = {
    "version": 1,
    "default": "default",
    "workspaces": ["default"],
}


# ---------------------------------------------------------------------------
# WorkspaceStore
# ---------------------------------------------------------------------------


class WorkspaceStore:
    """
    Manages the workspace registry and per-workspace metadata.

    All filesystem path logic is delegated to WorkspacePaths — this class
    deals only with names, the registry, and metadata serialisation.

    Parameters
    ----------
    data_root:
        The linkora data root directory.  Use ``get_data_root()`` to
        obtain the correct platform default.
    """

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self._registry_path = data_root / "workspace" / "workspaces.json"

    # ------------------------------------------------------------------
    # Path factory
    # ------------------------------------------------------------------

    def paths(self, name: str) -> WorkspacePaths:
        """Return the computed paths for workspace *name*."""
        return WorkspacePaths(data_root=self.data_root, name=name)

    # ------------------------------------------------------------------
    # Registry  (workspaces.json)
    # ------------------------------------------------------------------

    def _load_registry(self) -> dict:
        return _read_json(self._registry_path, default=_REGISTRY_DEFAULT)

    def _save_registry(self, data: dict) -> None:
        _write_json(self._registry_path, data)

    # ------------------------------------------------------------------
    # Workspace listing
    # ------------------------------------------------------------------

    def list_workspaces(self) -> list[str]:
        """
        Return all registered workspace names.

        Falls back to a directory scan when the registry is missing or
        empty (e.g. after a manual move of the data directory).
        """
        # Only use registry if the file actually exists
        if self._registry_path.exists():
            data = self._load_registry()
            names: list = data.get("workspaces", [])
            if names:
                return names

        # Fallback: scan for workspace.json sentinels.
        ws_root = self.data_root / "workspace"
        if not ws_root.exists():
            return ["default"]
        scanned = [
            d.name
            for d in ws_root.iterdir()
            if d.is_dir() and (d / "workspace.json").exists()
        ]
        return scanned if scanned else ["default"]

    def exists(self, name: str) -> bool:
        return name in self.list_workspaces()

    # ------------------------------------------------------------------
    # Default workspace
    # ------------------------------------------------------------------

    def get_default(self) -> str:
        return self._load_registry().get("default", "default")

    def set_default(self, name: str) -> None:
        if not self.exists(name):
            raise KeyError(f"Workspace '{name}' not found")
        data = self._load_registry()
        data["default"] = name
        self._save_registry(data)

    # ------------------------------------------------------------------
    # Metadata  (workspace/<n>/workspace.json)
    # ------------------------------------------------------------------

    def get_metadata(self, name: str) -> WorkspaceMetadata:
        path = self.paths(name).metadata_file
        raw = _read_json(path)
        return (
            WorkspaceMetadata.from_dict(raw) if raw else WorkspaceMetadata.create(name)
        )

    def set_metadata(self, name: str, *, description: str | None = None) -> None:
        """
        Update mutable metadata for *name*.

        Only ``description`` is user-settable.  The ``name`` and
        ``created_at`` fields are set at creation time and are never
        changed by this method.  Legacy fields (``root``, ``is_default``)
        are silently stripped on every rewrite.
        """
        path = self.paths(name).metadata_file
        existing = _read_json(path)
        if not existing:
            existing = WorkspaceMetadata.create(name).to_dict()

        if description is not None:
            existing["description"] = description

        for stale in ("root", "is_default"):
            existing.pop(stale, None)

        _write_json(path, existing)
        self._ensure_in_registry(name)

    def list_metadata(self) -> List[WorkspaceMetadata]:
        return [self.get_metadata(n) for n in self.list_workspaces()]

    # ------------------------------------------------------------------
    # Create / delete
    # ------------------------------------------------------------------

    def create(self, name: str, description: str = "") -> WorkspacePaths:
        """
        Create a new workspace directory structure and register it.

        Returns the WorkspacePaths for the new workspace.
        Raises FileExistsError if a workspace with that name already exists.
        """
        if self.exists(name):
            raise FileExistsError(f"Workspace '{name}' already exists")
        p = self.paths(name)
        p.ensure_dirs()
        self.set_metadata(name, description=description)
        return p

    def delete(self, name: str) -> None:
        """
        Delete a workspace and remove it from the registry.

        Raises ValueError when attempting to delete the default workspace.
        """
        if name == self.get_default():
            raise ValueError(
                f"Cannot delete the default workspace '{name}'. "
                "Set a different default first: linkora config set-default <name>"
            )
        ws_dir = self.paths(name).workspace_dir
        if ws_dir.exists():
            shutil.rmtree(ws_dir)
        self._remove_from_registry(name)

    # ------------------------------------------------------------------
    # Migrate (rename / relocate)
    # ------------------------------------------------------------------

    def migrate(self, source: str, target: str) -> int:
        """
        Rename or relocate a workspace.

        ``target`` may be:
        - a plain name  →  renamed within the same data_root
        - an absolute path  →  moved to an arbitrary filesystem location

        Returns the number of papers in the migrated workspace.

        Raises
        ------
        FileNotFoundError
            When *source* does not exist.
        FileExistsError
            When *target* already exists.
        """
        if not self.exists(source):
            raise FileNotFoundError(f"Workspace '{source}' not found")

        src_dir = self.paths(source).workspace_dir
        target_p = Path(target)

        if target_p.is_absolute():
            dst_dir = target_p
            new_name = target_p.name
        else:
            dst_dir = self.data_root / "workspace" / target
            new_name = target

        if dst_dir.exists():
            raise FileExistsError(f"Target '{target}' already exists")

        try:
            src_dir.rename(dst_dir)
        except OSError:
            # Cross-device move.
            shutil.copytree(src_dir, dst_dir)
            shutil.rmtree(src_dir)

        # Rewrite stored metadata: update name, strip legacy path fields.
        meta_path = dst_dir / "workspace.json"
        meta_raw = _read_json(meta_path)
        if meta_raw:
            meta_raw["name"] = new_name
            for stale in ("root", "is_default"):
                meta_raw.pop(stale, None)
            _write_json(meta_path, meta_raw)

        self._rename_in_registry(source, new_name)
        return self._count_papers(dst_dir / "papers")

    # ------------------------------------------------------------------
    # Paper counting
    # ------------------------------------------------------------------

    def get_paper_count(self, name: str) -> int:
        return self._count_papers(self.paths(name).papers_dir)

    @staticmethod
    def _count_papers(papers_dir: Path) -> int:
        if not papers_dir.exists():
            return 0
        return sum(
            1 for d in papers_dir.iterdir() if d.is_dir() and (d / "meta.json").exists()
        )

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    def _ensure_in_registry(self, name: str) -> None:
        data = self._load_registry()
        ws: list = data.setdefault("workspaces", [])
        if name not in ws:
            ws.append(name)
        self._save_registry(data)

    def _remove_from_registry(self, name: str) -> None:
        data = self._load_registry()
        data["workspaces"] = [n for n in data.get("workspaces", []) if n != name]
        self._save_registry(data)

    def _rename_in_registry(self, old: str, new: str) -> None:
        data = self._load_registry()
        ws: list = data.get("workspaces", [])
        try:
            ws[ws.index(old)] = new
        except ValueError:
            ws.append(new)
        data["workspaces"] = ws
        if data.get("default") == old:
            data["default"] = new
        self._save_registry(data)


__all__ = ["WorkspaceStore", "WorkspaceMetadata", "WorkspacePaths", "get_data_root"]
