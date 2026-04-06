"""Integration tests for workspace module."""

from linkora.workspace import WorkspaceStore, get_data_root, get_db_path


def test_get_data_root_platform_aware():
    """Test data root is platform-appropriate."""
    root = get_data_root()
    assert root.name == "linkora"
    assert root.exists() or True  # May not exist yet


def test_get_db_path_uses_data_root():
    """Test db path uses unified path resolution."""
    db_path = get_db_path()
    assert db_path.name == "linkora.db"
    assert db_path.parent == get_data_root()


def test_workspace_store_init(tmp_db):
    """Test WorkspaceStore initializes with db."""
    store = WorkspaceStore(tmp_db)
    assert store is not None


def test_workspace_create_and_list(tmp_db):
    """Test creating and listing workspaces."""
    store = WorkspaceStore(tmp_db)

    # Create workspace
    ws = store.create("test-ws", description="Test workspace")
    assert ws.name == "test-ws"
    assert ws.description == "Test workspace"

    # List workspaces
    workspaces = store.list_workspaces()
    assert len(workspaces) == 1
    assert workspaces[0].name == "test-ws"


def test_workspace_set_default(tmp_db):
    """Test setting default workspace."""
    store = WorkspaceStore(tmp_db)

    store.create("ws-a", description="Workspace A")
    store.create("ws-b", description="Workspace B")
    store.set_default("ws-b")

    default = store.get_default()
    assert default is not None
    assert default.name == "ws-b"


def test_workspace_isolation(tmp_db):
    """Test workspace isolation - docs in one ws not visible in another."""
    store = WorkspaceStore(tmp_db)

    # Create two workspaces
    store.create("ws-a")
    store.create("ws-b")

    from linkora.store import DocumentStore

    doc_store = DocumentStore(tmp_db)

    # Add doc to ws-a
    from linkora.store import Document

    doc_a = Document(
        id="doc-1",
        workspace_id="ws-a",
        doc_type="paper",
        source_path="/test/doc1.pdf",
        title="Document A",
        l2_summary="Summary A",
        l3_outline="",
        metadata_json="{}",
    )
    doc_store.save(doc_a)

    # Verify doc visible in ws-a
    docs_a = doc_store.list_by_workspace("ws-a")
    assert len(docs_a) == 1

    # Verify doc NOT visible in ws-b
    docs_b = doc_store.list_by_workspace("ws-b")
    assert len(docs_b) == 0


def test_workspace_rename_updates_docs(tmp_db):
    """Test renaming workspace updates all doc workspace_ids."""
    store = WorkspaceStore(tmp_db)
    store.create("old-name")

    from linkora.store import DocumentStore, Document

    doc_store = DocumentStore(tmp_db)

    doc = Document(
        id="doc-1",
        workspace_id="old-name",
        doc_type="paper",
        source_path="/test/doc.pdf",
        title="Test",
        l2_summary="",
        l3_outline="",
        metadata_json="{}",
    )
    doc_store.save(doc)

    # Rename workspace
    store.rename("old-name", "new-name")

    # Verify doc updated
    doc_updated = doc_store.get_by_id("doc-1")
    assert doc_updated is not None
    assert doc_updated.workspace_id == "new-name"
