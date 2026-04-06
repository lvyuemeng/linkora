from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json

from linkora.db import Database, DatabaseManager
from linkora import content_hash, string_hash


@dataclass
class Document:
    id: str
    workspace_id: str
    doc_type: str
    source_path: str
    title: str
    l2_summary: str
    l3_outline: str
    metadata_json: str
    content_hash: str | None = None
    status: str = "ok"
    imported_at: str | None = None
    enriched_at: str | None = None


@dataclass
class FileLocation:
    content_hash: str
    path: str
    status: str
    last_seen_at: str


@dataclass
class Topic:
    topic_id: int
    workspace_id: str
    label: str
    top_terms: list[str]
    size: int
    created_at: str


@dataclass
class DocumentTopic:
    doc_id: str
    workspace_id: str
    topic_id: int
    score: float


class DocumentStore:
    """Document CRUD operations."""

    def __init__(self, db_or_manager: Database | DatabaseManager):
        self._db_manager = _to_db_manager(db_or_manager)
        self._locations = FileLocationStore(self._db_manager)

    def topic_store(self) -> "TopicStore":
        return TopicStore(self._db_manager)

    def file_location_store(self) -> "FileLocationStore":
        return FileLocationStore(self._db_manager)

    def list_workspace_ids(self) -> list[str]:
        rows = self._db_manager.execute_query(
            "SELECT DISTINCT workspace_id FROM documents"
        )
        return [str(row["workspace_id"]) for row in rows if row.get("workspace_id")]

    def save(self, doc: Document) -> None:
        """Save or update a document."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Generate content hash if missing
        doc_content_hash = doc.content_hash
        if doc_content_hash is None:
            try:
                doc_content_hash = content_hash(Path(doc.source_path))
            except Exception:
                # Fallback to a stable hash of the document ID
                doc_content_hash = string_hash(doc.id)

        self._db_manager.execute_update(
            """
            INSERT OR REPLACE INTO documents (
                id, workspace_id, doc_type, source_path, title, content_hash,
                status, l2_summary, l3_outline, metadata_json, imported_at, enriched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc.id,
                doc.workspace_id,
                doc.doc_type,
                doc.source_path,
                doc.title,
                doc_content_hash,
                doc.status,
                doc.l2_summary,
                doc.l3_outline,
                doc.metadata_json,
                now,
                doc.enriched_at,
            ),
        )
        self._locations.upsert(
            content_hash=doc_content_hash,
            path=doc.source_path,
            status="ok",
        )

    def get_by_id(self, doc_id: str) -> Document | None:
        """Get document by ID."""
        row = self._db_manager.get_single_row(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        )
        if not row:
            return None
        return Document(
            id=row["id"],
            workspace_id=row["workspace_id"],
            doc_type=row["doc_type"],
            source_path=row["source_path"],
            title=row["title"] or "",
            l2_summary=row["l2_summary"] or "",
            l3_outline=row["l3_outline"] or "",
            metadata_json=row["metadata_json"],
            content_hash=row["content_hash"],
            status=row["status"],
            imported_at=row["imported_at"],
            enriched_at=row["enriched_at"],
        )

    def list_by_workspace(
        self,
        workspace_id: str,
        doc_type: str | None = None,
        limit: int = 100,
    ) -> list[Document]:
        """List documents in a workspace."""
        if doc_type:
            rows = self._db_manager.execute_query(
                "SELECT * FROM documents WHERE workspace_id = ? AND doc_type = ? ORDER BY imported_at DESC LIMIT ?",
                (workspace_id, doc_type, limit),
            )
        else:
            rows = self._db_manager.execute_query(
                "SELECT * FROM documents WHERE workspace_id = ? ORDER BY imported_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        return [
            Document(
                id=row["id"],
                workspace_id=row["workspace_id"],
                doc_type=row["doc_type"],
                source_path=row["source_path"],
                title=row["title"] or "",
                l2_summary=row["l2_summary"] or "",
                l3_outline=row["l3_outline"] or "",
                metadata_json=row["metadata_json"],
                content_hash=row["content_hash"],
                status=row["status"],
                imported_at=row["imported_at"],
                enriched_at=row["enriched_at"],
            )
            for row in rows
        ]

    def delete(self, doc_id: str) -> bool:
        """Delete a document by ID."""
        return (
            self._db_manager.execute_update(
                "DELETE FROM documents WHERE id = ?", (doc_id,)
            )
            > 0
        )

    def update_source_path(self, doc_id: str, new_path: str) -> None:
        """Update source path for a document."""
        self._db_manager.execute_update(
            "UPDATE documents SET source_path = ? WHERE id = ?", (new_path, doc_id)
        )

    def update_status(self, doc_id: str, status: str) -> None:
        """Update status for a document."""
        self._db_manager.execute_update(
            "UPDATE documents SET status = ? WHERE id = ?", (status, doc_id)
        )


class FileLocationStore:
    """Track non-portable file paths for content hashes."""

    def __init__(self, db_or_manager: Database | DatabaseManager):
        self._db_manager = _to_db_manager(db_or_manager)

    def upsert(self, content_hash: str, path: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._db_manager.execute_update(
            """
            INSERT OR REPLACE INTO file_locations (
                content_hash, path, status, last_seen_at
            ) VALUES (?, ?, ?, ?)
            """,
            (content_hash, path, status, now),
        )

    def mark_missing(self, content_hash: str, path: str) -> None:
        self.upsert(content_hash=content_hash, path=path, status="missing")


class TopicStore:
    """Topic modeling storage operations."""

    def __init__(self, db_or_manager: Database | DatabaseManager):
        self._db_manager = _to_db_manager(db_or_manager)

    def replace_workspace(
        self,
        workspace_id: str,
        topics: list[Topic],
        assignments: list[DocumentTopic],
    ) -> None:
        self._db_manager.execute_update(
            "DELETE FROM topics WHERE workspace_id = ?", (workspace_id,)
        )
        self._db_manager.execute_update(
            "DELETE FROM document_topics WHERE workspace_id = ?", (workspace_id,)
        )
        self.save_topics(topics)
        self.save_assignments(assignments)

    def save_topics(self, topics: list[Topic]) -> None:
        if not topics:
            return
        params = [
            (
                t.topic_id,
                t.workspace_id,
                t.label,
                json.dumps(t.top_terms),
                t.size,
                t.created_at,
            )
            for t in topics
        ]
        self._db_manager.execute_many(
            """
            INSERT OR REPLACE INTO topics (
                topic_id, workspace_id, label, top_terms_json, size, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            params,
        )

    def save_assignments(self, assignments: list[DocumentTopic]) -> None:
        if not assignments:
            return
        params = [(a.doc_id, a.workspace_id, a.topic_id, a.score) for a in assignments]
        self._db_manager.execute_many(
            """
            INSERT OR REPLACE INTO document_topics (
                doc_id, workspace_id, topic_id, score
            ) VALUES (?, ?, ?, ?)
            """,
            params,
        )

    def list_topics(self, workspace_id: str) -> list[Topic]:
        rows = self._db_manager.execute_query(
            "SELECT * FROM topics WHERE workspace_id = ? ORDER BY size DESC",
            (workspace_id,),
        )
        topics: list[Topic] = []
        for row in rows:
            topics.append(
                Topic(
                    topic_id=row["topic_id"],
                    workspace_id=row["workspace_id"],
                    label=row["label"],
                    top_terms=json.loads(row["top_terms_json"] or "[]"),
                    size=row["size"],
                    created_at=row["created_at"],
                )
            )
        return topics

    def get_topic(self, workspace_id: str, topic_id: int) -> Topic | None:
        row = self._db_manager.get_single_row(
            "SELECT * FROM topics WHERE workspace_id = ? AND topic_id = ?",
            (workspace_id, topic_id),
        )
        if not row:
            return None
        return Topic(
            topic_id=row["topic_id"],
            workspace_id=row["workspace_id"],
            label=row["label"],
            top_terms=json.loads(row["top_terms_json"] or "[]"),
            size=row["size"],
            created_at=row["created_at"],
        )

    def list_assignments(self, workspace_id: str) -> list[DocumentTopic]:
        rows = self._db_manager.execute_query(
            "SELECT * FROM document_topics WHERE workspace_id = ?",
            (workspace_id,),
        )
        return [
            DocumentTopic(
                doc_id=row["doc_id"],
                workspace_id=row["workspace_id"],
                topic_id=row["topic_id"],
                score=row["score"],
            )
            for row in rows
        ]

    def delete_topics(self, workspace_id: str, topic_ids: list[int]) -> int:
        if not topic_ids:
            return 0
        placeholders = ",".join("?" for _ in topic_ids)
        params: tuple = (workspace_id, *topic_ids)
        return self._db_manager.execute_update(
            f"DELETE FROM topics WHERE workspace_id = ? AND topic_id IN ({placeholders})",
            params,
        )

    def delete_assignments(self, workspace_id: str, topic_ids: list[int]) -> int:
        if not topic_ids:
            return 0
        placeholders = ",".join("?" for _ in topic_ids)
        params: tuple = (workspace_id, *topic_ids)
        return self._db_manager.execute_update(
            f"DELETE FROM document_topics WHERE workspace_id = ? AND topic_id IN ({placeholders})",
            params,
        )


def _to_db_manager(db_or_manager: Database | DatabaseManager) -> DatabaseManager:
    if isinstance(db_or_manager, DatabaseManager):
        return db_or_manager
    return DatabaseManager(db_or_manager)
