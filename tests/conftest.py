"""Shared pytest fixtures."""

import pytest
from pathlib import Path


@pytest.fixture
def fixtures_dir():
    """Return fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_paper_metadata():
    """Sample paper metadata for testing."""
    return {
        "id": "test-123",
        "title": "Test Paper Title",
        "authors": ["John Smith", "Jane Doe"],
        "year": 2024,
        "journal": "Nature",
        "doi": "10.1234/test",
        "abstract": "This is a test abstract.",
        "paper_type": "article",
    }


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace structure."""
    workspace = tmp_path / "workspace" / "default"
    workspace.mkdir(parents=True)
    (workspace / "papers").mkdir()

    yield workspace
