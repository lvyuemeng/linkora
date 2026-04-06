"""Integration tests for schema and store modules."""

from linkora.schema.registry import (
    DEFAULT_SCHEMA_REGISTRY,
    FilenameRenderRequest,
    build_filename_context,
    resolve_filename,
    list_builtin_schemas,
    resolve_doc_type,
    resolve_schema,
)
from linkora.schema.types import ContractFields, PaperFields, PaperSchema
from linkora.db import DatabaseManager
from linkora.store import DocumentStore, Document
from linkora.index import SearchIndex


def test_builtin_schemas_all_present():
    """Test all 5 built-in schemas are registered."""
    expected = {"paper", "invoice", "manual", "contract", "generic"}
    assert set(list_builtin_schemas().keys()) == expected


def test_detect_doc_type_from_extension():
    """Test document type detection from file extension."""
    assert resolve_doc_type(registry=DEFAULT_SCHEMA_REGISTRY, hint=None) == "generic"


def test_detect_doc_type_hint_override():
    """Test doc_type hint overrides extension detection."""
    assert (
        resolve_doc_type(registry=DEFAULT_SCHEMA_REGISTRY, hint="invoice") == "invoice"
    )
    assert resolve_doc_type(registry=DEFAULT_SCHEMA_REGISTRY, hint="manual") == "manual"


def test_get_schema_returns_correct_type():
    """Test get_schema returns correct schema."""
    paper_schema = resolve_schema("paper", registry=DEFAULT_SCHEMA_REGISTRY)
    assert paper_schema.doc_type == "paper"
    assert paper_schema.display_name == "Research Paper"

    invoice_schema = resolve_schema("invoice", registry=DEFAULT_SCHEMA_REGISTRY)
    assert invoice_schema.doc_type == "invoice"

    generic_schema = resolve_schema("generic", registry=DEFAULT_SCHEMA_REGISTRY)
    assert generic_schema.doc_type == "generic"


def test_get_schema_fallback_to_generic():
    """Test get_schema falls back to generic for unknown types."""
    schema = resolve_schema("unknown-type", registry=DEFAULT_SCHEMA_REGISTRY)
    assert schema.doc_type == "generic"


def test_paper_schema_fields():
    """Test PaperSchema provides expected fields."""
    fields = PaperFields(
        title="Test Paper",
        summary="Test summary",
        doi="10.1234/test",
        authors=["Author One", "Author Two"],
        year=2024,
    )
    assert fields.title == "Test Paper"
    assert fields.doi == "10.1234/test"
    assert len(fields.authors) == 2


def test_paper_schema_filename_template():
    """Test PaperSchema filename template."""
    fields = PaperFields(
        title="Attention Is All You Need",
        authors=["Vaswani"],
        year=2017,
    )
    template = PaperSchema.filename_template(fields)
    assert template == "2017_vaswani_attention-is-all-you-need"


def test_paper_schema_filename_template_missing_fields():
    """Test PaperSchema filename template handles missing fields."""
    fields = PaperFields(title="Test")  # No year
    template = PaperSchema.filename_template(fields)
    assert template is None


def test_filename_context_mapping_for_authors_and_title_slug():
    fields = PaperFields(
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        year=2017,
    )

    context = build_filename_context(fields)

    assert context["author"] == "Ashish Vaswani"
    assert context["author_last"] == "vaswani"
    assert context["title_slug"] == "attention-is-all-you-need"


def test_filename_context_mapping_for_parties_slug_and_template_rendering():
    schema = resolve_schema("contract", registry=DEFAULT_SCHEMA_REGISTRY)
    fields = ContractFields(
        title="Service Agreement",
        parties=["Acme Corporation", "Riverstone LLC"],
        effective_date="2026-01-01",
    )
    context = build_filename_context(fields)
    assert context["parties_slug"] == "corporation_llc"

    name = resolve_filename(
        FilenameRenderRequest(
            schema=schema,
            fields=fields,
            template="{parties_slug}_{effective_date}",
            use_schema_fallback=True,
        )
    ).value
    assert name == "corporation_llc_2026-01-01"


def test_document_store_save_and_get(tmp_db):
    """Test DocumentStore save and retrieve."""
    store = DocumentStore(tmp_db)

    doc = Document(
        id="test-doc-1",
        workspace_id="test-ws",
        doc_type="paper",
        source_path="/test/doc.pdf",
        title="Test Document",
        l2_summary="Test summary",
        l3_outline="Outline",
        metadata_json='{"key": "value"}',
    )

    store.save(doc)

    retrieved = store.get_by_id("test-doc-1")
    assert retrieved is not None
    assert retrieved.title == "Test Document"
    assert retrieved.workspace_id == "test-ws"


def test_document_store_list_by_workspace(tmp_db):
    """Test listing documents by workspace."""
    store = DocumentStore(tmp_db)

    # Add docs to different workspaces with unique IDs
    for i in range(3):
        doc = Document(
            id=f"doc-a-{i}",  # unique ID
            workspace_id="ws-a",
            doc_type="paper",
            source_path=f"/test/a{i}.pdf",  # unique source_path
            title=f"Doc A {i}",
            l2_summary="",
            l3_outline="",
            metadata_json="{}",
            content_hash=f"hash-a-{i}",  # unique hash
        )
        store.save(doc)

    doc = Document(
        id="doc-b-1",
        workspace_id="ws-b",
        doc_type="paper",
        source_path="/test/b.pdf",
        title="Doc B",
        l2_summary="",
        l3_outline="",
        metadata_json="{}",
        content_hash="hash-b-1",
    )
    store.save(doc)

    ws_a_docs = store.list_by_workspace("ws-a")
    assert len(ws_a_docs) == 3

    ws_b_docs = store.list_by_workspace("ws-b")
    assert len(ws_b_docs) == 1


def test_document_store_delete(tmp_db):
    """Test document deletion."""
    store = DocumentStore(tmp_db)

    doc = Document(
        id="to-delete",
        workspace_id="ws",
        doc_type="paper",
        source_path="/test.pdf",
        title="To Delete",
        l2_summary="",
        l3_outline="",
        metadata_json="{}",
    )
    store.save(doc)

    assert store.get_by_id("to-delete") is not None

    store.delete("to-delete")
    assert store.get_by_id("to-delete") is None


def test_document_store_fts_search(tmp_db):
    """Test FTS5 search."""
    store = DocumentStore(tmp_db)

    doc = Document(
        id="fts-test",
        workspace_id="ws",
        doc_type="paper",
        source_path="/test.pdf",
        title="Machine Learning Basics",
        l2_summary="Introduction to ML concepts",
        l3_outline="",
        metadata_json="{}",
    )
    store.save(doc)
    idx = SearchIndex(DatabaseManager(tmp_db))
    idx.rebuild()

    results = list(idx.search("machine", workspace_id="ws"))
    assert len(results) == 1
    assert results[0].title == "Machine Learning Basics"
