from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

from linkora.log import get_logger, ui
from linkora.schema.registry import (
    DEFAULT_SCHEMA_REGISTRY,
    DocumentFields,
    DocumentSchema,
    resolve_schema,
)
from linkora.store import Document

_LOG = get_logger(__name__)


@dataclass(frozen=True)
class EnrichResult:
    fields: DocumentFields
    token_count: int


@dataclass(frozen=True)
class EnrichRequest:
    workspace_id: str
    paper_id: str | None
    limit: int | None
    force: bool
    summary: bool
    outline: bool


@dataclass(frozen=True)
class EnrichPlan:
    update_summary: bool
    update_outline: bool

    @classmethod
    def from_request(cls, request: EnrichRequest) -> "EnrichPlan":
        if request.summary or request.outline:
            return cls(update_summary=request.summary, update_outline=request.outline)
        return cls(update_summary=True, update_outline=True)


class EnrichStoreLike(Protocol):
    def get_by_id(self, doc_id: str) -> Document | None: ...

    def list_by_workspace(
        self, workspace_id: str, limit: int = 100
    ) -> list[Document]: ...

    def save(self, doc: Document) -> None: ...


async def enrich(
    raw_content: str,
    schema: type[DocumentSchema],
    seed: dict | None = None,
) -> EnrichResult:
    """Enrich document metadata with schema-aware LLM extraction."""
    from linkora.config import get_config

    config = get_config()
    known = {k: v for k, v in (seed or {}).items() if v}
    missing = [name for name in schema.fields_model.model_fields if name not in known]
    api_key = config.resolve_llm_api_key()

    if not missing or not api_key:
        return EnrichResult(fields=schema.fields_model(**known), token_count=0)

    llm_fields = await _call_llm(
        prompt=schema.extraction_prompt(raw_content, missing),
        fields_model=schema.fields_model,
        model=config.llm.model,
        base_url=config.llm.base_url,
        api_key=api_key,
        timeout=config.llm.timeout,
        backend=config.llm.backend,
    )
    known.update(llm_fields.model_dump(exclude_none=True))
    return EnrichResult(
        fields=schema.fields_model(**known),
        token_count=len(raw_content.split()) // 4,
    )


async def enrich_store(store: EnrichStoreLike, request: EnrichRequest) -> None:
    """Apply enrichment workflow to documents loaded from store."""
    plan = EnrichPlan.from_request(request)
    if request.paper_id:
        single = store.get_by_id(request.paper_id)
        docs = [single] if single else []
    else:
        docs = store.list_by_workspace(request.workspace_id, limit=request.limit or 100)
    if not docs:
        ui("No documents found.", logger=_LOG)
        return

    ui(f"Enriching {len(docs)} document(s)...", logger=_LOG)
    updated = 0

    for doc in docs:
        if not request.force and not _needs_update(doc, plan):
            continue
        try:
            schema = resolve_schema(doc.doc_type, registry=DEFAULT_SCHEMA_REGISTRY)
            result = await enrich(
                raw_content=doc.l2_summary or "",
                schema=schema,
                seed=_parse_seed(doc.metadata_json),
            )
            if plan.update_summary:
                doc.l2_summary = result.fields.summary or ""
            if plan.update_outline:
                doc.l3_outline = ",".join(result.fields.outline)
            store.save(doc)
            updated += 1
        except Exception as exc:
            ui(f"Failed to enrich {doc.id}: {exc}", logger=_LOG)

    ui(f"Enriched {updated}/{len(docs)} document(s).", logger=_LOG)


def _needs_update(doc: Document, plan: EnrichPlan) -> bool:
    return (plan.update_summary and not doc.l2_summary) or (
        plan.update_outline and not doc.l3_outline
    )


def _parse_seed(metadata_json: str) -> dict:
    if not metadata_json:
        return {}
    try:
        parsed = json.loads(metadata_json)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _call_llm(
    prompt: str,
    fields_model: type[DocumentFields],
    model: str,
    base_url: str,
    api_key: str,
    timeout: int,
    backend: str,
) -> DocumentFields:
    """Call LLM with structured output."""
    import litellm
    from pydantic import BaseModel

    class LiteLLMResponse(BaseModel):
        title: str | None = None
        summary: str | None = None
        outline: list[str] = []
        doi: str | None = None
        authors: list[str] = []
        journal: str | None = None
        year: int | None = None

    provider = "openai" if backend == "openai-compat" else None
    response = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=LiteLLMResponse,
        api_base=base_url,
        api_key=api_key,
        timeout=timeout,
        custom_llm_provider=provider,
    )

    content = response.choices[0].message.content
    if not content:
        return fields_model()

    try:
        payload = json.loads(content)
    except Exception:
        payload = {}
    return fields_model(**payload)


__all__ = ["EnrichResult", "EnrichRequest", "EnrichPlan", "enrich", "enrich_store"]
