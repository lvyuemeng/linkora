from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from linkora.store import Document


class DocumentFields(BaseModel):
    title: str | None = None
    summary: str | None = None
    outline: list[str] = Field(default_factory=list)


class DocumentSchema(Protocol):
    doc_type: str
    display_name: str
    fields_model: type[DocumentFields]
    file_extensions: list[str]

    @staticmethod
    def extraction_prompt(raw_text: str, missing: list[str]) -> str: ...

    @staticmethod
    def filename_template(fields: DocumentFields) -> str | None: ...

    @staticmethod
    def field_match(key: str, candidate: Any, expected: str) -> bool: ...


@dataclass(frozen=True)
class SchemaRegistry:
    schemas: dict[str, type[DocumentSchema]]


@dataclass(frozen=True)
class FilenameRenderRequest:
    schema: type[DocumentSchema]
    fields: DocumentFields
    template: str | None = None
    use_schema_fallback: bool = True


@dataclass(frozen=True)
class FilenameRenderOutcome:
    value: str | None


@dataclass(frozen=True)
class ParsedSchemaDocument:
    document: Document
    schema: type[DocumentSchema]
    fields: DocumentFields


@dataclass(frozen=True)
class SearchFilter:
    doc_type: str | None = None
    fields: dict[str, str] = field(default_factory=dict)

    def normalized(self) -> "SearchFilter":
        return SearchFilter(
            doc_type=normalize_doc_type(self.doc_type),
            fields={k: v for k, v in self.fields.items() if v != ""},
        )

    def is_empty(self) -> bool:
        normalized = self.normalized()
        return not normalized.doc_type and not normalized.fields


def _match_value(candidate: Any, expected: str) -> bool:
    if candidate is None:
        return False
    if isinstance(candidate, (int, float)):
        return str(candidate) == expected
    if isinstance(candidate, str):
        return expected.lower() in candidate.lower()
    if isinstance(candidate, list):
        return any(
            _match_value(item, expected) for item in candidate if isinstance(item, str)
        )
    return False


def default_field_match(key: str, candidate: Any, expected: str) -> bool:
    del key
    return _match_value(candidate, expected)


def _schema_types() -> dict[str, type[DocumentSchema]]:
    from linkora.schema.types import (
        ContractSchema,
        GenericSchema,
        InvoiceSchema,
        ManualSchema,
        PaperSchema,
    )

    return {
        "paper": PaperSchema,
        "invoice": InvoiceSchema,
        "manual": ManualSchema,
        "contract": ContractSchema,
        "generic": GenericSchema,
    }


DEFAULT_SCHEMA_REGISTRY = SchemaRegistry(schemas=_schema_types())


def list_builtin_schemas(
    registry: SchemaRegistry = DEFAULT_SCHEMA_REGISTRY,
) -> dict[str, type[DocumentSchema]]:
    return dict(registry.schemas)


def normalize_doc_type(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def resolve_doc_type(
    *,
    registry: SchemaRegistry = DEFAULT_SCHEMA_REGISTRY,
    hint: str | None = None,
) -> str:
    normalized_hint = normalize_doc_type(hint)
    if normalized_hint and normalized_hint in registry.schemas:
        return normalized_hint
    return "generic"


def resolve_schema(
    doc_type: str | None,
    *,
    registry: SchemaRegistry = DEFAULT_SCHEMA_REGISTRY,
) -> type[DocumentSchema]:
    normalized_doc_type = normalize_doc_type(doc_type)
    if normalized_doc_type is None:
        return registry.schemas["generic"]
    return registry.schemas.get(normalized_doc_type, registry.schemas["generic"])


def normalize_filename(value: str, preserve_spaces: bool = True) -> str:
    allowed = "-_ ." if preserve_spaces else "-_."
    normalized = "".join(ch if ch.isalnum() or ch in allowed else "-" for ch in value)
    compact = " ".join(normalized.split()) if preserve_spaces else normalized
    return compact.strip().strip(".")


def slugify_filename(value: str) -> str:
    return normalize_filename(value.lower(), preserve_spaces=False)


def resolve_filename(request: FilenameRenderRequest) -> FilenameRenderOutcome:
    data = build_filename_context(request.fields)
    if request.template:
        custom = render_custom_filename(request.template, data)
        if custom:
            return FilenameRenderOutcome(value=custom)
    if request.use_schema_fallback:
        return FilenameRenderOutcome(
            value=request.schema.filename_template(request.fields)
        )
    return FilenameRenderOutcome(value=None)


def render_custom_filename(template: str, context: dict[str, Any]) -> str | None:
    class _SafeDict(dict):
        def __missing__(self, key):
            return ""

    try:
        value = template.format_map(_SafeDict(context)).strip()
    except Exception:
        return None
    return value or None


def build_filename_context(fields: DocumentFields) -> dict[str, Any]:
    data = fields.model_dump()
    title = str(data.get("title") or "")
    authors = data.get("authors") or []
    parties = data.get("parties") or []

    if isinstance(authors, list) and authors:
        author = str(authors[0])
        author_last = str(authors[0]).split()[-1].lower()
    elif isinstance(authors, str):
        author = authors
        author_last = authors.split()[-1].lower() if authors.strip() else ""
    else:
        author = ""
        author_last = ""

    data["author"] = author
    data["author_last"] = author_last
    data["title_slug"] = slugify_filename(title)[:40]
    data["parties_slug"] = (
        "_".join(str(p).split()[-1] for p in parties[:2]).lower()
        if isinstance(parties, list) and parties
        else ""
    )
    return data


def resolve_field_matcher(schema: type[DocumentSchema]):
    try:
        return schema.field_match
    except AttributeError:
        return default_field_match


def parse_schema_documents(
    documents: list[Document],
    *,
    registry: SchemaRegistry = DEFAULT_SCHEMA_REGISTRY,
) -> list[ParsedSchemaDocument]:
    parsed: list[ParsedSchemaDocument] = []
    for document in documents:
        schema = resolve_schema(document.doc_type, registry=registry)
        fields = schema.fields_model.model_validate_json(document.metadata_json)
        parsed.append(
            ParsedSchemaDocument(document=document, schema=schema, fields=fields)
        )
    return parsed


def filter_schema_documents(
    documents: list[ParsedSchemaDocument],
    filters: SearchFilter | None,
) -> list[Document]:
    if filters is None:
        return [item.document for item in documents]
    normalized = filters.normalized()
    if normalized.is_empty():
        return [item.document for item in documents]
    return [item.document for item in documents if _matches_document(item, normalized)]


def _matches_document(item: ParsedSchemaDocument, filters: SearchFilter) -> bool:
    if filters.doc_type and item.schema.doc_type != filters.doc_type:
        return False

    data = item.fields.model_dump()
    matcher = resolve_field_matcher(item.schema)
    for key, expected in filters.fields.items():
        if key not in data:
            return False
        if not matcher(key, data[key], expected):
            return False
    return True


__all__ = [
    "DocumentFields",
    "DocumentSchema",
    "SchemaRegistry",
    "DEFAULT_SCHEMA_REGISTRY",
    "FilenameRenderRequest",
    "FilenameRenderOutcome",
    "ParsedSchemaDocument",
    "SearchFilter",
    "list_builtin_schemas",
    "normalize_doc_type",
    "resolve_doc_type",
    "resolve_schema",
    "normalize_filename",
    "slugify_filename",
    "resolve_filename",
    "render_custom_filename",
    "build_filename_context",
    "default_field_match",
    "resolve_field_matcher",
    "parse_schema_documents",
    "filter_schema_documents",
]
