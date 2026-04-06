"""index.py - Search indexes (FTS5 + LanceDB)."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Any, Iterator, cast

from pydantic import BaseModel, Field
from linkora.config import get_config
from linkora.db import DatabaseManager
from linkora.paths import get_vectors_dir
from linkora.store import DocumentStore

if TYPE_CHECKING:
    from linkora.config import AppConfig


_VECTOR_TABLE = "documents"


class SearchResult(BaseModel):
    doc_id: str
    title: str
    snippet: str
    workspace_id: str
    doc_type: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "SearchResult":
        return cls(
            doc_id=str(row["id"]),
            title=str(row.get("title") or ""),
            snippet=str(row.get("l2_summary") or "")[:200],
            workspace_id=str(row["workspace_id"]),
            doc_type=str(row["doc_type"]),
        )


class SearchQuery(BaseModel):
    text: str
    workspace_id: str | None = None
    doc_type: str | None = None
    limit: int = Field(default=20, ge=1)


class VectorResult(BaseModel):
    doc_id: str
    title: str
    score: float
    workspace_id: str
    doc_type: str

    @classmethod
    def from_lance_row(cls, row: Any) -> "VectorResult":
        return cls(
            doc_id=row.doc_id,
            title=row.title,
            score=float(getattr(row, "score", 0.0)),
            workspace_id=row.workspace_id,
            doc_type=row.doc_type,
        )


class VectorStore(BaseModel):
    """Encapsulates vectors directory and LanceDB table lifecycle."""

    vectors_dir: Path
    table_name: str = _VECTOR_TABLE

    @classmethod
    def default(cls) -> "VectorStore":
        return cls(vectors_dir=get_vectors_dir())

    def open_table(self):
        import lancedb

        self.vectors_dir.mkdir(parents=True, exist_ok=True)
        db = lancedb.connect(str(self.vectors_dir))
        schema = {
            "doc_id": "string",
            "title": "string",
            "l2_summary": "string",
            "workspace_id": "string",
            "doc_type": "string",
            "vector": "float32",
        }
        try:
            return db.create_table(self.table_name, schema=schema, exist_ok=True)
        except Exception:
            return db.open_table(self.table_name)


class SearchIndex:
    """FTS5 full-text search index over documents."""

    def __init__(self, db_manager: DatabaseManager):
        self._db = db_manager

    def search(
        self,
        query: str,
        workspace_id: str | None = None,
        doc_type: str | None = None,
        limit: int = 20,
    ) -> Iterator[SearchResult]:
        spec = SearchQuery(
            text=query,
            workspace_id=workspace_id,
            doc_type=doc_type,
            limit=max(1, limit),
        )
        for row in self._query_rows(spec):
            yield SearchResult.from_row(row)

    def rebuild(self) -> None:
        self._db.execute_update("DELETE FROM documents_fts")
        self._db.execute_update(
            """
            INSERT INTO documents_fts(doc_id, title, l2_summary, l3_outline)
            SELECT id, title, l2_summary, l3_outline FROM documents
            """
        )

    def _query_rows(self, query: SearchQuery) -> list[dict[str, Any]]:
        sql = (
            "SELECT d.id, d.title, d.l2_summary, d.workspace_id, d.doc_type "
            "FROM documents_fts f "
            "JOIN documents d ON d.id = f.doc_id "
            "WHERE f MATCH ?"
        )
        params: list[object] = [query.text]
        sql, params = _append_doc_filters(
            sql, params, query.workspace_id, query.doc_type, "d"
        )
        sql += " LIMIT ?"
        params.append(query.limit)

        try:
            return self._db.execute_query(sql, tuple(params))
        except sqlite3.OperationalError:
            return self._fallback_rows(query)

    def _fallback_rows(self, query: SearchQuery) -> list[dict[str, Any]]:
        search_term = f"%{query.text}%"
        sql = (
            "SELECT id, title, l2_summary, workspace_id, doc_type "
            "FROM documents "
            "WHERE (title LIKE ? OR l2_summary LIKE ? OR l3_outline LIKE ? OR source_path LIKE ?)"
        )
        params: list[object] = [cast(object, search_term) for _ in range(4)]
        sql, params = _append_doc_filters(
            sql, params, query.workspace_id, query.doc_type
        )
        sql += " LIMIT ?"
        params.append(query.limit)
        return self._db.execute_query(sql, tuple(params))


class VectorIndex:
    """LanceDB vector search index over documents."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        config: "AppConfig | None" = None,
        vector_store: VectorStore | None = None,
    ):
        self._db = db_manager
        self._config = config or get_config()
        self._vector_store = vector_store or VectorStore.default()
        self._table = None
        self._embedder = None

    def add_document(
        self,
        doc_id: str,
        title: str,
        summary: str,
        workspace_id: str,
        doc_type: str,
    ) -> None:
        table = self._get_table()
        table.add(
            {
                "doc_id": doc_id,
                "title": title,
                "l2_summary": summary,
                "workspace_id": workspace_id,
                "doc_type": doc_type,
                "vector": self._compute_embedding(f"{title} {summary}".strip()),
            }
        )

    def search(
        self,
        query: str,
        workspace_id: str | None = None,
        doc_type: str | None = None,
        limit: int = 20,
    ) -> Iterator[VectorResult]:
        req = self._get_table().search(self._compute_embedding(query))
        where_clause = _build_where_clause(workspace_id=workspace_id, doc_type=doc_type)
        if where_clause:
            req = req.where(where_clause)
        for row in req.limit(limit).to_pydantic(VectorResult):
            yield VectorResult.from_lance_row(row)

    def rebuild(self) -> None:
        store = DocumentStore(self._db)
        for workspace_id in store.list_workspace_ids():
            for doc in store.list_by_workspace(workspace_id, limit=10000):
                self.add_document(
                    doc_id=doc.id,
                    title=doc.title,
                    summary=doc.l2_summary,
                    workspace_id=doc.workspace_id,
                    doc_type=doc.doc_type,
                )

    def _get_table(self):
        if self._table is None:
            self._table = self._vector_store.open_table()
        return self._table

    def _compute_embedding(self, text: str) -> list[float]:
        try:
            from sentence_transformers import SentenceTransformer

            if self._embedder is None:
                model_name = self._config.index.embed_model
                device = self._config.index.embed_device
                source = (self._config.index.embed_source or "").lower()
                model_ref = _resolve_model(model_name, source)
                self._embedder = SentenceTransformer(model_ref, device=device)
            embedding = self._embedder.encode(text, normalize_embeddings=True)
            return embedding.tolist()
        except ImportError:
            return [0.0] * 768


def _append_doc_filters(
    sql: str,
    params: list[object],
    workspace_id: str | None,
    doc_type: str | None,
    alias: str | None = None,
) -> tuple[str, list[object]]:
    prefix = f"{alias}." if alias else ""
    if workspace_id:
        sql += f" AND {prefix}workspace_id = ?"
        params.append(workspace_id)
    if doc_type:
        sql += f" AND {prefix}doc_type = ?"
        params.append(doc_type)
    return sql, params


def _build_where_clause(workspace_id: str | None, doc_type: str | None) -> str | None:
    clauses: list[str] = []
    if workspace_id:
        clauses.append(f"workspace_id = '{_escape_sql_string(workspace_id)}'")
    if doc_type:
        clauses.append(f"doc_type = '{_escape_sql_string(doc_type)}'")
    return " AND ".join(clauses) if clauses else None


def _escape_sql_string(value: str) -> str:
    return value.replace("'", "''")


def _resolve_model(model_name: str, source: str) -> str:
    if source != "modelscope":
        return model_name
    try:
        from modelscope.hub.snapshot_download import snapshot_download

        return snapshot_download(model_name)
    except Exception:
        return model_name


__all__ = [
    "SearchIndex",
    "SearchResult",
    "SearchQuery",
    "VectorStore",
    "VectorIndex",
    "VectorResult",
]
