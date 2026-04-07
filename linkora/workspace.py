"""
workspace.py - Workspace model.

Design invariants:
- Workspaces are namespace labels in the DB, NOT directories.
- All linkora data lives under get_data_root().
- Single SQLite database stores all workspace data.
- Use get_db_path() for database, get_cache_dir() for cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from linkora.db import DatabaseManager
from linkora import setup as _setup

get_data_root = _setup.get_data_root
get_db_path = _setup.get_db_path
get_cache_dir = _setup.get_cache_dir
get_config_path = _setup.get_config_path


@dataclass(frozen=True)
class WorkspaceMetadata:
    """Persistent identity data for a workspace."""

    id: str
    name: str
    description: str = ""
    created_at: str = ""
    is_default: bool = False

    @staticmethod
    def create(name: str) -> "WorkspaceMetadata":
        return WorkspaceMetadata(
            id=name,
            name=name,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )


class WorkspaceStore:
    """Manages workspace namespace operations via database."""

    def __init__(self, db):
        self._db_manager = DatabaseManager(db)

    def document_store(self):
        from linkora.store import DocumentStore

        return DocumentStore(self._db_manager)

    def topic_store(self):
        from linkora.store import TopicStore

        return TopicStore(self._db_manager)

    def search_index(self):
        from linkora.index import SearchIndex

        return SearchIndex(self._db_manager)

    def vector_index(self):
        from linkora.index import VectorIndex

        return VectorIndex(self._db_manager)

    def list_workspaces(self) -> list[WorkspaceMetadata]:
        """Return all workspace metadata."""
        rows = self._db_manager.execute_query(
            "SELECT id, name, description, created_at, is_default FROM workspaces ORDER BY created_at ASC, name ASC"
        )
        return [
            WorkspaceMetadata(
                id=row["id"],
                name=row["name"],
                description=row["description"] or "",
                created_at=row["created_at"] or "",
                is_default=bool(row["is_default"]),
            )
            for row in rows
        ]

    def get_default(self) -> WorkspaceMetadata | None:
        """Return the default workspace."""
        row = self._db_manager.get_single_row(
            "SELECT id, name, description, created_at, is_default FROM workspaces WHERE is_default = 1"
        )
        if not row:
            return None
        return WorkspaceMetadata(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            created_at=row["created_at"] or "",
            is_default=bool(row["is_default"]),
        )

    def set_default(self, name: str) -> None:
        """Set default workspace by name."""
        self._db_manager.execute_update("UPDATE workspaces SET is_default = 0")
        self._db_manager.execute_update(
            "UPDATE workspaces SET is_default = 1 WHERE name = ?", (name,)
        )

    def ensure_default_workspace(self) -> tuple[str, bool]:
        """Ensure one default workspace exists and return ``(name, created)``."""
        default_ws = self.get_default()
        if default_ws:
            return default_ws.name, False

        existing = self.list_workspaces()
        if existing:
            name = existing[0].name
            self.set_default(name)
            return name, False

        name = "default"
        self.create(name, description="Default workspace")
        self.set_default(name)
        return name, True

    def create(self, name: str, description: str = "") -> WorkspaceMetadata:
        """Create a new workspace."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._db_manager.execute_update(
            "INSERT INTO workspaces (id, name, description, created_at, is_default) VALUES (?, ?, ?, ?, 0)",
            (name, name, description, now),
        )
        return WorkspaceMetadata(
            id=name,
            name=name,
            description=description,
            created_at=now,
            is_default=False,
        )

    def delete(self, name: str, *, delete_documents: bool = False) -> None:
        """Delete a workspace."""
        if delete_documents:
            self._db_manager.execute_update(
                "DELETE FROM documents WHERE workspace_id = ?", (name,)
            )
        self._db_manager.execute_update(
            "DELETE FROM workspaces WHERE name = ?", (name,)
        )

    def rename(self, old: str, new: str) -> None:
        """Rename a workspace."""
        self._db_manager.execute_update(
            "UPDATE workspaces SET id = ?, name = ? WHERE name = ?", (new, new, old)
        )
        self._db_manager.execute_update(
            "UPDATE documents SET workspace_id = ? WHERE workspace_id = ?", (new, old)
        )

    def exists(self, name: str) -> bool:
        """Check if workspace exists."""
        row = self._db_manager.get_single_row(
            "SELECT 1 AS exists_flag FROM workspaces WHERE name = ?", (name,)
        )
        return row is not None

    def get_metadata(self, name: str) -> WorkspaceMetadata | None:
        """Get workspace metadata by name."""
        row = self._db_manager.get_single_row(
            "SELECT id, name, description, created_at, is_default FROM workspaces WHERE name = ?",
            (name,),
        )
        if not row:
            return None
        return WorkspaceMetadata(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            created_at=row["created_at"] or "",
            is_default=bool(row["is_default"]),
        )

    def get_paper_count(self, name: str) -> int:
        """Get document count in workspace."""
        row = self._db_manager.get_single_row(
            "SELECT COUNT(*) AS count FROM documents WHERE workspace_id = ?", (name,)
        )
        return int(row["count"]) if row else 0

    def set_metadata(self, name: str, description: str = "") -> None:
        """Update workspace description."""
        self._db_manager.execute_update(
            "UPDATE workspaces SET description = ? WHERE name = ?", (description, name)
        )

    def add_watched_dir(
        self, path: str, workspace_id: str, doc_type_hint: str | None = None
    ) -> None:
        """Add a watched directory."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._db_manager.execute_update(
            "INSERT OR REPLACE INTO watched_dirs (path, workspace_id, doc_type_hint, added_at) VALUES (?, ?, ?, ?)",
            (path, workspace_id, doc_type_hint, now),
        )

    def list_watched_dirs(self) -> list[dict]:
        """List all watched directories."""
        return self._db_manager.execute_query(
            "SELECT path, workspace_id, doc_type_hint, added_at FROM watched_dirs"
        )

    def remove_watched_dir(self, path: str) -> None:
        """Remove a watched directory."""
        self._db_manager.execute_update(
            "DELETE FROM watched_dirs WHERE path = ?", (path,)
        )

    @property
    def data_root(self) -> Path:
        """Return data root path."""
        return get_data_root()
