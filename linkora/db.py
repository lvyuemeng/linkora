"""
db.py - SQLite database layer.

Manages database connections, migrations, and schema.
All database access goes through this module.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Database:
    """SQLite database connection manager."""

    def __init__(self, path: Path):
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if not self._conn:
            self._conn = sqlite3.connect(
                self.path, detect_types=sqlite3.PARSE_DECLTYPES
            )
            self._conn.row_factory = sqlite3.Row
            self._initialize_schema()
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _initialize_schema(self) -> None:
        """Create tables if they don't exist."""
        if self._conn is None:
            raise RuntimeError("Database connection is not initialized")
        cursor = self._conn.cursor()

        # Workspaces table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            created_at  TEXT NOT NULL,
            is_default  INTEGER DEFAULT 0
        )
        """)

        # Documents table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id            TEXT PRIMARY KEY,
            workspace_id  TEXT NOT NULL REFERENCES workspaces(id),
            doc_type      TEXT NOT NULL,
            title         TEXT,
            source_path   TEXT NOT NULL,
            content_hash  TEXT NOT NULL,
            status        TEXT DEFAULT 'ok',
            l2_summary    TEXT,
            l3_outline    TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            imported_at   TEXT NOT NULL,
            enriched_at   TEXT,
            UNIQUE(workspace_id, content_hash)
        )
        """)

        # Watched directories table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS watched_dirs (
            path          TEXT PRIMARY KEY,
            workspace_id  TEXT NOT NULL REFERENCES workspaces(id),
            doc_type_hint TEXT,
            added_at      TEXT NOT NULL
        )
        """)

        # File locations table (path is not portable)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS file_locations (
            content_hash  TEXT NOT NULL,
            path          TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'ok',
            last_seen_at  TEXT NOT NULL,
            PRIMARY KEY (content_hash, path)
        )
        """)

        # FTS5 full text search index
        cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            doc_id UNINDEXED,
            title, l2_summary, l3_outline, content,
            content='', tokenize='unicode61'
        )
        """)

        # Sessions table (for chat history - kept for compatibility)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id            TEXT PRIMARY KEY,
            workspace_id  TEXT NOT NULL REFERENCES workspaces(id),
            created_at    TEXT NOT NULL,
            messages_json TEXT NOT NULL DEFAULT '[]'
        )
        """)

        # Workspace profiles table (for chat context)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS workspace_profiles (
            workspace_id  TEXT PRIMARY KEY REFERENCES workspaces(id),
            profile_json  TEXT NOT NULL DEFAULT '{}'
        )
        """)

        # Topics table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            topic_id      INTEGER NOT NULL,
            workspace_id  TEXT NOT NULL REFERENCES workspaces(id),
            label         TEXT NOT NULL,
            top_terms_json TEXT NOT NULL DEFAULT '[]',
            size          INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL,
            PRIMARY KEY (workspace_id, topic_id)
        )
        """)

        # Document-topic assignments
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_topics (
            doc_id        TEXT NOT NULL REFERENCES documents(id),
            workspace_id  TEXT NOT NULL REFERENCES workspaces(id),
            topic_id      INTEGER NOT NULL,
            score         REAL NOT NULL DEFAULT 0.0,
            PRIMARY KEY (workspace_id, doc_id)
        )
        """)

        self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        """Transaction context manager."""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise


class DatabaseManager:
    """High-level database operations manager.

    Eliminates repetitive connection/cursor/commit patterns.
    Provides unified interface for all database operations.
    """

    def __init__(self, db: Database):
        self.db = db

    def execute_query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute SELECT query and return results as dicts."""
        with self.db.transaction() as cursor:
            cursor.execute(sql, params)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def execute_update(self, sql: str, params: tuple = ()) -> int:
        """Execute INSERT/UPDATE/DELETE and return affected rows."""
        with self.db.transaction() as cursor:
            cursor.execute(sql, params)
            return cursor.rowcount

    def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """Execute multiple INSERT/UPDATE operations."""
        with self.db.transaction() as cursor:
            cursor.executemany(sql, params_list)

    def get_single_row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """Execute query and return single row as dict, or None."""
        with self.db.transaction() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None

    def table_exists(self, table_name: str) -> bool:
        """Check if table exists."""
        result = self.get_single_row(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return result is not None


__all__ = ["Database", "DatabaseManager"]
