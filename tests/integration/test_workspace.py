"""
test_workspace.py — Unit and integration tests for WorkspaceStore,
WorkspaceMetadata, and WorkspacePaths.

Covers:
  - WorkspaceMetadata creation, serialisation, and legacy-field stripping
  - WorkspaceStore: create / list / exists / default / metadata / delete
  - WorkspaceStore: registry persistence across instances
  - WorkspaceStore: migrate (rename and absolute-path relocation)
  - WorkspaceStore: paper counting
  - WorkspaceStore: fallback directory scan when registry is missing
  - Legacy data: 'root' and 'is_default' fields silently stripped on rewrite
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from linkora.workspace import (
    WorkspaceMetadata,
    WorkspacePaths,
    WorkspaceStore,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Fresh data root for each test."""
    return tmp_path / "linkora_data"


@pytest.fixture
def store(root: Path) -> WorkspaceStore:
    return WorkspaceStore(root)


# ---------------------------------------------------------------------------
# WorkspaceMetadata
# ---------------------------------------------------------------------------


class TestWorkspaceMetadata:
    def test_create_sets_name_and_timestamp(self):
        meta = WorkspaceMetadata.create("ml")
        assert meta.name == "ml"
        assert meta.created_at.endswith("Z")
        assert meta.description == ""

    def test_to_dict_roundtrip(self):
        meta = WorkspaceMetadata.create("physics")
        restored = WorkspaceMetadata.from_dict(meta.to_dict())
        assert restored == meta

    def test_from_dict_ignores_legacy_root(self):
        data = {
            "name": "old",
            "description": "legacy",
            "created_at": "2024-01-01T00:00:00Z",
            "root": "/some/absolute/path",  # legacy field
            "is_default": True,  # legacy field
        }
        meta = WorkspaceMetadata.from_dict(data)
        assert meta.name == "old"
        assert meta.description == "legacy"
        # WorkspaceMetadata has no 'root' or 'is_default' attribute.
        assert not hasattr(meta, "root")
        assert not hasattr(meta, "is_default")

    def test_frozen(self):
        meta = WorkspaceMetadata.create("test")
        with pytest.raises(Exception):
            meta.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# WorkspaceStore — create and basic listing
# ---------------------------------------------------------------------------


class TestWorkspaceStoreCreate:
    def test_create_makes_directories(self, store, root):
        paths = store.create("ml")
        assert paths.papers_dir.exists()
        assert (paths.workspace_dir / "logs").exists()

    def test_create_writes_metadata(self, store):
        store.create("ml", description="Machine learning papers")
        meta = store.get_metadata("ml")
        assert meta.name == "ml"
        assert meta.description == "Machine learning papers"
        assert meta.created_at != ""

    def test_create_registers_workspace(self, store):
        store.create("physics")
        assert store.exists("physics")
        assert "physics" in store.list_workspaces()

    def test_create_duplicate_raises(self, store):
        store.create("ml")
        with pytest.raises(FileExistsError, match="already exists"):
            store.create("ml")

    def test_create_returns_workspace_paths(self, store):
        paths = store.create("ml")
        assert isinstance(paths, WorkspacePaths)
        assert paths.name == "ml"


# ---------------------------------------------------------------------------
# WorkspaceStore — listing, existence, persistence
# ---------------------------------------------------------------------------


class TestWorkspaceStoreListing:
    def test_list_empty_store_has_default(self, store):
        """Registry default seeds 'default' even before any workspace is created."""
        names = store.list_workspaces()
        assert "default" in names

    def test_exists_false_for_unknown(self, store):
        assert not store.exists("nonexistent")

    def test_exists_true_after_create(self, store):
        store.create("ml")
        assert store.exists("ml")

    def test_registry_persists_across_instances(self, root):
        """A second WorkspaceStore on the same root must see workspaces from the first."""
        store_a = WorkspaceStore(root)
        store_a.create("ml")
        store_a.create("physics")

        store_b = WorkspaceStore(root)
        assert store_b.exists("ml")
        assert store_b.exists("physics")

    def test_list_metadata_returns_all(self, store):
        store.create("a", description="A")
        store.create("b", description="B")
        all_meta = store.list_metadata()
        names = [m.name for m in all_meta]
        assert "a" in names
        assert "b" in names


# ---------------------------------------------------------------------------
# WorkspaceStore — default management
# ---------------------------------------------------------------------------


class TestWorkspaceStoreDefault:
    def test_initial_default_is_default(self, store):
        assert store.get_default() == "default"

    def test_set_default(self, store):
        store.create("ml")
        store.set_default("ml")
        assert store.get_default() == "ml"

    def test_set_default_unknown_raises(self, store):
        with pytest.raises(KeyError, match="not found"):
            store.set_default("nonexistent")

    def test_set_default_persists_across_instances(self, root):
        store_a = WorkspaceStore(root)
        store_a.create("ml")
        store_a.set_default("ml")

        store_b = WorkspaceStore(root)
        assert store_b.get_default() == "ml"


# ---------------------------------------------------------------------------
# WorkspaceStore — metadata
# ---------------------------------------------------------------------------


class TestWorkspaceStoreMetadata:
    def test_set_description(self, store):
        store.create("ml")
        store.set_metadata("ml", description="Updated description")
        assert store.get_metadata("ml").description == "Updated description"

    def test_set_metadata_strips_legacy_root(self, store, root):
        """Writing metadata via set_metadata must strip any legacy 'root' key."""
        store.create("legacy")
        meta_path = store.paths("legacy").metadata_file

        # Inject a legacy 'root' field directly into the JSON file.
        raw = json.loads(meta_path.read_text())
        raw["root"] = "/some/old/path"
        meta_path.write_text(json.dumps(raw))

        # Trigger a metadata rewrite.
        store.set_metadata("legacy", description="cleaned")

        rewritten = json.loads(meta_path.read_text())
        assert "root" in rewritten is False or "root" not in rewritten
        assert rewritten.get("description") == "cleaned"

    def test_set_metadata_strips_is_default(self, store, root):
        store.create("old")
        meta_path = store.paths("old").metadata_file
        raw = json.loads(meta_path.read_text())
        raw["is_default"] = True
        meta_path.write_text(json.dumps(raw))

        store.set_metadata("old", description="x")
        rewritten = json.loads(meta_path.read_text())
        assert "is_default" not in rewritten

    def test_get_metadata_for_unregistered_returns_default(self, store):
        """get_metadata on a workspace with no file returns a fresh default."""
        meta = store.get_metadata("phantom")
        assert meta.name == "phantom"
        assert meta.description == ""


# ---------------------------------------------------------------------------
# WorkspaceStore — delete
# ---------------------------------------------------------------------------


class TestWorkspaceStoreDelete:
    def test_delete_removes_directory(self, store):
        store.create("ml")
        ws_dir = store.paths("ml").workspace_dir
        store.delete("ml")
        assert not ws_dir.exists()

    def test_delete_removes_from_registry(self, store):
        store.create("ml")
        store.delete("ml")
        assert not store.exists("ml")

    def test_delete_default_raises(self, store):
        with pytest.raises(ValueError, match="Cannot delete the default"):
            store.delete("default")

    def test_delete_nonexistent_does_not_raise(self, store):
        """Deleting a workspace with no directory should not crash."""
        store.create("ml")
        # Manually remove directory before calling delete.
        import shutil

        shutil.rmtree(store.paths("ml").workspace_dir)
        store.delete("ml")  # should not raise
        assert not store.exists("ml")


# ---------------------------------------------------------------------------
# WorkspaceStore — migrate (rename / relocate)
# ---------------------------------------------------------------------------


class TestWorkspaceStoreMigrate:
    def test_rename_within_root(self, store):
        store.create("old")
        store.migrate("old", "new")
        assert store.exists("new")
        assert not store.exists("old")

    def test_rename_moves_directory(self, store):
        store.create("old")
        old_dir = store.paths("old").workspace_dir
        store.migrate("old", "new")
        assert not old_dir.exists()
        assert store.paths("new").workspace_dir.exists()

    def test_rename_updates_metadata_name(self, store):
        store.create("old", description="desc")
        store.migrate("old", "new")
        meta = store.get_metadata("new")
        assert meta.name == "new"
        assert meta.description == "desc"

    def test_rename_strips_legacy_fields_from_metadata(self, store, root):
        store.create("old")
        meta_path = store.paths("old").metadata_file
        raw = json.loads(meta_path.read_text())
        raw["root"] = "/legacy/path"
        meta_path.write_text(json.dumps(raw))

        store.migrate("old", "new")
        meta_path_new = store.paths("new").metadata_file
        rewritten = json.loads(meta_path_new.read_text())
        assert "root" not in rewritten

    def test_migrate_updates_default_when_renamed(self, store):
        store.create("ml")
        store.set_default("ml")
        store.migrate("ml", "ml_v2")
        assert store.get_default() == "ml_v2"

    def test_migrate_to_absolute_path(self, store, tmp_path):
        store.create("old")
        _seed_papers(store.paths("old").papers_dir, 3)
        dst = tmp_path / "external_ws"

        count = store.migrate("old", str(dst))
        assert dst.exists()
        assert count == 3

    def test_migrate_nonexistent_raises(self, store):
        with pytest.raises(FileNotFoundError, match="not found"):
            store.migrate("ghost", "new")

    def test_migrate_to_existing_raises(self, store):
        store.create("a")
        store.create("b")
        with pytest.raises(FileExistsError, match="already exists"):
            store.migrate("a", "b")


# ---------------------------------------------------------------------------
# WorkspaceStore — paper counting
# ---------------------------------------------------------------------------


class TestWorkspaceStorePaperCount:
    def test_empty_workspace_is_zero(self, store):
        store.create("ml")
        assert store.get_paper_count("ml") == 0

    def test_counts_paper_directories(self, store):
        store.create("ml")
        _seed_papers(store.paths("ml").papers_dir, 5)
        assert store.get_paper_count("ml") == 5

    def test_ignores_directories_without_meta_json(self, store):
        store.create("ml")
        papers_dir = store.paths("ml").papers_dir
        # Directory without meta.json — should not be counted.
        (papers_dir / "not_a_paper").mkdir(parents=True)
        assert store.get_paper_count("ml") == 0

    def test_nonexistent_workspace_is_zero(self, store):
        assert store.get_paper_count("phantom") == 0


# ---------------------------------------------------------------------------
# WorkspaceStore — registry fallback (directory scan)
# ---------------------------------------------------------------------------


class TestWorkspaceStoreFallback:
    def test_fallback_scan_when_registry_missing(self, root):
        """
        When workspaces.json does not exist, list_workspaces() should scan
        for workspace.json sentinel files.
        """
        # Create a workspace directory structure manually without a registry.
        ws_dir = root / "workspace" / "orphan"
        ws_dir.mkdir(parents=True)
        (ws_dir / "workspace.json").write_text(
            json.dumps(WorkspaceMetadata.create("orphan").to_dict()),
            encoding="utf-8",
        )

        store = WorkspaceStore(root)
        # Registry file does not exist — fallback scan must find 'orphan'.
        names = store.list_workspaces()
        assert "orphan" in names


# ---------------------------------------------------------------------------
# WorkspacePaths — paths factory
# ---------------------------------------------------------------------------


class TestWorkspacePathsFactory:
    def test_paths_returns_workspace_paths(self, store):
        paths = store.paths("default")
        assert isinstance(paths, WorkspacePaths)

    def test_paths_uses_store_data_root(self, store, root):
        paths = store.paths("ml")
        assert paths.data_root == root
        assert paths.name == "ml"

    def test_paths_are_consistent_with_create(self, store, root):
        created_paths = store.create("ml")
        retrieved_paths = store.paths("ml")
        assert created_paths.workspace_dir == retrieved_paths.workspace_dir
        assert created_paths.papers_dir == retrieved_paths.papers_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_papers(papers_dir: Path, count: int) -> None:
    """Create *count* fake paper subdirectories each containing meta.json."""
    papers_dir.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        paper_dir = papers_dir / f"paper_{i:04d}"
        paper_dir.mkdir()
        (paper_dir / "meta.json").write_text(
            json.dumps({"id": f"paper_{i:04d}", "title": f"Paper {i}"}),
            encoding="utf-8",
        )
