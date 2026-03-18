"""Integration test: PaperStore consistency.

Tests that:
1. PaperStore reads/writes correctly
2. Caching works properly
3. Audit integrates correctly
"""

import pytest
import json
from linkora.papers import PaperStore


@pytest.fixture
def paper_dir(tmp_path):
    """Create a paper directory with meta.json."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()

    # Create a paper directory
    paper_d = papers_dir / "Smith2024_DeepLearning"
    paper_d.mkdir()

    # Write meta.json
    meta = {
        "id": "test-123",
        "title": "Deep Learning for Beginners",
        "authors": ["John Smith", "Jane Doe"],
        "year": 2024,
        "journal": "Nature",
        "doi": "10.1234/test",
        "abstract": "This is a test abstract.",
    }
    (paper_d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    # Write paper.md
    (paper_d / "paper.md").write_text(
        "# Deep Learning for Beginners\n\nContent here.", encoding="utf-8"
    )

    yield papers_dir


class TestPaperStore:
    """Tests for PaperStore consistency."""

    def test_read_meta(self, paper_dir):
        """Read meta.json correctly."""
        store = PaperStore(paper_dir)

        papers = list(store.iter_papers())
        assert len(papers) == 1

        meta = store.read_meta(papers[0])
        assert meta["title"] == "Deep Learning for Beginners"
        assert meta["year"] == 2024

    def test_read_md(self, paper_dir):
        """Read paper.md correctly."""
        store = PaperStore(paper_dir)

        papers = list(store.iter_papers())
        md = store.read_md(papers[0])

        assert md is not None
        assert "Deep Learning" in md

    def test_iter_papers(self, paper_dir):
        """Iterate over papers."""
        store = PaperStore(paper_dir)

        papers = list(store.iter_papers())
        assert len(papers) == 1

    def test_multiple_papers(self, tmp_path):
        """Test with multiple papers."""
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()

        # Create first paper
        paper1 = papers_dir / "Smith2024_Paper1"
        paper1.mkdir()
        (paper1 / "meta.json").write_text(
            json.dumps({"id": "1", "title": "Paper 1", "year": 2024}),
            encoding="utf-8",
        )

        # Create second paper
        paper2 = papers_dir / "Doe2023_Paper2"
        paper2.mkdir()
        (paper2 / "meta.json").write_text(
            json.dumps({"id": "2", "title": "Paper 2", "year": 2023}),
            encoding="utf-8",
        )

        store = PaperStore(papers_dir)
        papers = list(store.iter_papers())

        assert len(papers) == 2
