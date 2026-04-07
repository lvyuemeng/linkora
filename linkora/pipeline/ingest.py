from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from linkora import content_hash
from linkora.pipeline.enrich import enrich
from linkora.pipeline.extract import extract_text
from linkora.schema.registry import (
    DEFAULT_SCHEMA_REGISTRY,
    resolve_doc_type,
    resolve_schema,
)
from linkora.store import Document as StoreDocument


@dataclass(frozen=True)
class IngestResult:
    doc_id: str
    success: bool
    error: str | None = None


class IngestStoreLike(Protocol):
    def get_by_id(self, doc_id: str) -> StoreDocument | None: ...

    def save(self, doc: StoreDocument) -> None: ...


async def ingest(
    path: Path,
    workspace_id: str,
    metadata_hint: dict | None = None,
    doc_type_hint: str | None = None,
    force: bool = False,
    store: IngestStoreLike | None = None,
) -> IngestResult:
    """Main pipeline: path in, DB out."""
    doc_store = store or _default_store()
    doc_id = content_hash(path)

    if not force and doc_store.get_by_id(doc_id):
        return IngestResult(doc_id=doc_id, success=True)

    doc_type = resolve_doc_type(registry=DEFAULT_SCHEMA_REGISTRY, hint=doc_type_hint)
    schema = resolve_schema(doc_type, registry=DEFAULT_SCHEMA_REGISTRY)
    raw = await extract_text(path)
    result = await enrich(raw.content, schema, seed=metadata_hint)

    doc_store.save(
        StoreDocument(
            id=doc_id,
            workspace_id=workspace_id,
            doc_type=schema.doc_type,
            source_path=str(path),
            title=result.fields.title or "",
            l2_summary=result.fields.summary or "",
            l3_outline=",".join(result.fields.outline),
            metadata_json=result.fields.model_dump_json(),
        )
    )
    return IngestResult(doc_id=doc_id, success=True)


def _default_store() -> IngestStoreLike:
    from linkora.setup import get_runtime_db
    from linkora.store import DocumentStore

    return DocumentStore(get_runtime_db())


__all__ = ["IngestResult", "ingest"]
