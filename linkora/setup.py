"""setup.py - Unified path resolution and diagnostics helpers."""

from __future__ import annotations

import os
import platform
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from linkora.cli.commands import AppContext
    from linkora.config import AppConfig
    from linkora.db import Database


_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")
_runtime_db: "Database | None" = None
_runtime_db_path: Path | None = None
_runtime_config: "AppConfig | None" = None
_runtime_config_path: Path | None = None
_runtime_config_loaded: bool = False

VALID_CONFIG_SECTIONS = {
    "sources",
    "index",
    "extract",
    "tidy",
    "llm",
    "topics",
    "log",
}


class CheckCategory(Enum):
    CONFIG = auto()
    ENV = auto()
    PATH = auto()


@dataclass(frozen=True)
class CheckItem:
    category: CheckCategory
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class CheckResult:
    items: tuple[CheckItem, ...]

    @property
    def passed(self) -> bool:
        return all(i.ok for i in self.items)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def failed(self) -> int:
        return sum(1 for i in self.items if not i.ok)


# ---------------------------------------------------------------------------
# Path APIs
# ---------------------------------------------------------------------------


def get_data_root() -> Path:
    """Return the platform-appropriate linkora data directory."""
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

    return (base / "linkora").expanduser().resolve()


def ensure_data_root() -> Path:
    root = get_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_db_path() -> Path:
    """Return the path to the SQLite database file."""
    return get_data_root() / "linkora.db"


def get_cache_dir() -> Path:
    """Return the extraction cache directory."""
    return get_data_root() / "cache"


def get_vectors_dir() -> Path:
    """Return the vector index directory."""
    return get_data_root() / "vectors"


def resolve_data_path(value: str) -> Path:
    """Resolve a path under data root unless already absolute."""
    raw = Path(value).expanduser()
    return raw if raw.is_absolute() else (get_data_root() / raw)


def get_config_candidates() -> list[Path]:
    """Return ordered global config path candidates."""
    home = Path.home()
    return [
        home / ".linkora" / "config.yml",
        home / ".linkora" / "config.yaml",
        home / ".linkora.yml",
        home / ".linkora.yaml",
        home / ".config" / "linkora" / "config.yml",
        home / ".config" / "linkora" / "config.yaml",
    ]


def get_config_path() -> Path:
    """Return canonical config write path."""
    return get_config_candidates()[0]


def _resolve_config_files() -> tuple[list[Path], Path | None]:
    existing = [p for p in get_config_candidates() if p.exists()]
    active = existing[0] if existing else None
    return existing, active


def get_existing_config_candidates() -> list[Path]:
    """Return existing config files in candidate order."""
    existing, _ = _resolve_config_files()
    return existing


def get_active_config_path() -> Path | None:
    """Return active config path, if any."""
    _, active = _resolve_config_files()
    return active


def get_runtime_config_dir() -> Path:
    """Return active config dir or canonical write dir parent."""
    if _runtime_config_loaded and _runtime_config_path is not None:
        return _runtime_config_path.parent
    active = get_active_config_path()
    return active.parent if active else get_config_path().parent


def _expand_env(value: str) -> str:
    def _sub(match: re.Match) -> str:
        name, fallback = match.group(1), match.group(2)
        return os.environ.get(name) or fallback or ""

    return _ENV_PATTERN.sub(_sub, value)


def _resolve_env(value: Any) -> Any:
    if isinstance(value, str):
        return _expand_env(value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


def _yaml_load(raw: str) -> Any:
    import yaml

    return yaml.safe_load(raw)


def _yaml_dump(data: Any) -> str:
    import yaml

    return yaml.safe_dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def _read_yaml_file(path: Path) -> dict[str, Any]:
    """Read YAML mapping from path; return empty dict on errors."""
    try:
        payload = _yaml_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        from linkora.log import get_logger

        get_logger(__name__).warning("Failed to load %s: %s", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_yaml_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml_dump(data), encoding="utf-8")


def _set_nested(doc: Any, parts: list[str], value: Any) -> None:
    current = doc
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


_MISSING = object()


def _to_yaml_value(value: Any) -> Any:
    from pydantic import BaseModel

    if isinstance(value, BaseModel):
        return value.model_dump()
    return value


def _read_nested_model_value(obj: Any, parts: list[str]) -> Any:
    from pydantic import BaseModel

    current = obj
    for part in parts:
        if isinstance(current, BaseModel):
            if not hasattr(current, part):
                return _MISSING
            current = getattr(current, part)
            continue
        if isinstance(current, Mapping):
            if part not in current:
                return _MISSING
            current = current[part]
            continue
        return _MISSING
    return current


def render_config_yaml(config: "AppConfig", field: str | None = None) -> str:
    """Render full runtime config or one field as YAML."""
    if not field:
        return _yaml_dump(config.model_dump())
    value = _read_nested_model_value(config, field.split("."))
    if value is _MISSING:
        return f"Field '{field}' not found in config."
    return _yaml_dump({field: _to_yaml_value(value)})


def set_config_value(field: str, raw_value: str) -> tuple[str, Path, str | None]:
    """Write one config field and reset setup runtime cache."""
    value = _yaml_load(raw_value)
    top_key = field.split(".")[0]
    if top_key not in VALID_CONFIG_SECTIONS:
        return (
            f"Error: Unknown config section '{top_key}'. Valid sections: "
            f"{', '.join(sorted(VALID_CONFIG_SECTIONS))}",
            get_config_path(),
            None,
        )

    config_path = get_active_config_path() or get_config_path()
    existed_before = config_path.exists()
    doc = _read_yaml_file(config_path) if existed_before else {}

    _set_nested(doc, field.split("."), value)
    _write_yaml_file(config_path, doc)

    note = None
    if not existed_before:
        note = f"Creating new config file at {config_path}"

    reset_runtime_state()
    return (f"Set {field} = {value!r}  ({config_path})", config_path, note)


def load_app_config() -> tuple["AppConfig", Path | None]:
    """Load active config file and return ``(config, active_path)``."""
    from linkora.config import AppConfig
    from linkora.log import get_logger

    log = get_logger(__name__)
    candidates, active = _resolve_config_files()
    if len(candidates) > 1:
        log.warning(
            "Multiple config files found. '%s' is active; ignoring: %s. "
            "Remove the ignored file(s) to silence this warning.",
            candidates[0],
            ", ".join(str(p) for p in candidates[1:]),
        )

    if active is None:
        log.info("No config file found; using built-in defaults.")
        return AppConfig(), None

    log.debug("Loading config from %s", active)
    raw = _read_yaml_file(active)
    resolved = _resolve_env(raw)
    return AppConfig.model_validate(resolved), active


def get_runtime_config() -> "AppConfig":
    """Return process runtime config singleton managed by setup."""
    global _runtime_config, _runtime_config_path, _runtime_config_loaded
    if not _runtime_config_loaded:
        _runtime_config, _runtime_config_path = load_app_config()
        _runtime_config_loaded = True
    if _runtime_config is None:
        raise RuntimeError("Runtime config failed to load")
    return _runtime_config


def get_runtime_db(db_path: Path | None = None) -> "Database":
    """Return process runtime DB singleton managed by setup."""
    from linkora.db import Database

    global _runtime_db, _runtime_db_path
    resolved = db_path.expanduser().resolve() if db_path else get_db_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    if _runtime_db is None or _runtime_db_path != resolved:
        if _runtime_db is not None:
            _runtime_db.close()
        _runtime_db = Database(resolved)
        _runtime_db_path = resolved
    return _runtime_db


def reset_runtime_state() -> None:
    """Reset setup-managed DB/config singletons (for tests)."""
    global _runtime_db, _runtime_db_path
    global _runtime_config, _runtime_config_path, _runtime_config_loaded

    if _runtime_db is not None:
        _runtime_db.close()
    _runtime_db = None
    _runtime_db_path = None

    _runtime_config = None
    _runtime_config_path = None
    _runtime_config_loaded = False


def _check_config_resolution(ctx) -> Iterator[CheckItem]:
    """
    Inspect global config file resolution.

    Reports which file is active and warns when multiple candidates exist
    (the non-active ones are silently ignored, which can confuse users).
    """
    existing, active = _resolve_config_files()

    if not existing:
        yield CheckItem(
            CheckCategory.CONFIG,
            "config.file",
            ok=True,
            detail="no file found (using built-in defaults)",
        )
    else:
        yield CheckItem(
            CheckCategory.CONFIG,
            "config.active",
            ok=True,
            detail=str(active),
        )

    if len(existing) > 1 and active is not None:
        ignored = [p for p in existing if p != active]
        yield CheckItem(
            CheckCategory.CONFIG,
            "config.conflict",
            ok=False,
            detail=(
                f"Multiple config files found — only '{active.name}' is active. "
                f"Ignored: {', '.join(str(p) for p in ignored)}. "
                "Remove the ignored file(s) to eliminate this ambiguity."
            ),
        )

    yield CheckItem(
        CheckCategory.CONFIG,
        "config.defaults",
        ok=True,
        detail=(
            f"index.top_k={ctx.config.index.top_k}, "
            f"llm.model={ctx.config.llm.model}, "
            f"llm.base_url={ctx.config.llm.base_url}, "
            f"llm.timeout={ctx.config.llm.timeout}"
        ),
    )


def _check_secrets(ctx) -> Iterator[CheckItem]:
    config_key_set = bool(ctx.config.llm.api_key)
    env_key_set = bool(os.environ.get("LINKORA_LLM_API_KEY"))
    yield CheckItem(
        CheckCategory.ENV,
        "llm.api_key",
        ok=True,
        detail=(
            "configured via config"
            if config_key_set
            else "configured via LINKORA_LLM_API_KEY"
            if env_key_set
            else "not set (optional; enrichment falls back to seed/default fields)"
        ),
    )


def _check_env_vars() -> Iterator[CheckItem]:
    root = os.environ.get("LINKORA_ROOT")
    yield CheckItem(
        CheckCategory.ENV,
        "env.LINKORA_ROOT",
        ok=True,
        detail=root if root else "not set (using platform default data root)",
    )


def _check_paths() -> Iterator[CheckItem]:
    root = get_data_root()
    yield CheckItem(CheckCategory.PATH, "paths.data_root", ok=True, detail=str(root))

    try:
        exists = root.exists()
        yield CheckItem(
            CheckCategory.PATH,
            "paths.data_root.exists",
            ok=exists,
            detail="exists" if exists else "missing (will be created on demand)",
        )
    except Exception as exc:
        yield CheckItem(
            CheckCategory.PATH,
            "paths.data_root.exists",
            ok=False,
            detail=f"failed to check data root: {exc}",
        )

    try:
        ensured = ensure_data_root()
        yield CheckItem(
            CheckCategory.PATH,
            "paths.data_root.ensure",
            ok=True,
            detail=str(ensured),
        )
    except Exception as exc:
        yield CheckItem(
            CheckCategory.PATH,
            "paths.data_root.ensure",
            ok=False,
            detail=f"failed to create data root: {exc}",
        )

    yield CheckItem(
        CheckCategory.PATH,
        "paths.db",
        ok=True,
        detail=str(get_db_path()),
    )
    yield CheckItem(
        CheckCategory.PATH,
        "paths.cache",
        ok=True,
        detail=str(get_cache_dir()),
    )
    yield CheckItem(
        CheckCategory.PATH,
        "paths.vectors",
        ok=True,
        detail=str(get_vectors_dir()),
    )


# ---------------------------------------------------------------------------
# Collection pipelines
# ---------------------------------------------------------------------------


def _collect_doctor(ctx) -> Iterator[CheckItem]:
    yield from _check_config_resolution(ctx)
    yield from _check_env_vars()
    yield from _check_secrets(ctx)
    yield from _check_paths()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_doctor(ctx) -> CheckResult:
    """Run config/env/path doctor checks (no network calls)."""
    return CheckResult(items=tuple(_collect_doctor(ctx)))


def format_result(result: CheckResult, title: str = "Check") -> str:
    """Format a CheckResult for terminal output."""
    bar = "=" * (len(title) + 8)
    lines = [bar, f"    {title}", bar]

    by_cat: dict[CheckCategory, list[CheckItem]] = {}
    for item in result.items:
        by_cat.setdefault(item.category, []).append(item)

    for cat in CheckCategory:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"\n{cat.name}:")
        for item in items:
            mark = "OK" if item.ok else "FAIL"
            lines.append(f"  [{mark}] {item.name:<34} {item.detail}")

    status = "PASS" if result.passed else "FAIL"
    lines.append(
        f"\n{status}  {result.total - result.failed}/{result.total} checks passed"
    )
    return "\n".join(lines)


def run_init(cli_workspace: str | None = None, force: bool = False) -> "AppContext":
    """
    Bootstrap runtime context for CLI and command handlers.

    Workspace resolution order is:
      CLI override > LINKORA_WORKSPACE env var > default workspace in registry.
    """
    from linkora.cli.commands import AppContext

    if force:
        print("'--force' has no effect: init no longer writes config files.")

    data_root = ensure_data_root()

    from linkora.workspace import WorkspaceStore

    db = get_runtime_db(data_root / "linkora.db")
    store = WorkspaceStore(db)
    default_workspace_name, _ = store.ensure_default_workspace()
    workspace_name = (
        cli_workspace
        or os.environ.get("LINKORA_WORKSPACE", "")
        or default_workspace_name
    )

    return AppContext(
        config=get_runtime_config(),
        config_dir=get_runtime_config_dir(),
        store=store,
        workspace_name=workspace_name,
        data_root=data_root,
        db=db,
    )


__all__ = [
    "CheckCategory",
    "CheckItem",
    "CheckResult",
    "get_data_root",
    "ensure_data_root",
    "get_db_path",
    "get_cache_dir",
    "get_vectors_dir",
    "resolve_data_path",
    "get_config_path",
    "get_config_candidates",
    "set_config_value",
    "render_config_yaml",
    "VALID_CONFIG_SECTIONS",
    "get_existing_config_candidates",
    "get_active_config_path",
    "get_runtime_config",
    "get_runtime_config_dir",
    "load_app_config",
    "get_runtime_db",
    "reset_runtime_state",
    "run_doctor",
    "format_result",
    "run_init",
]
