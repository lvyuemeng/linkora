"""Integration test: LocalSource multi-path scanning.

Tests for LocalSource with multiple paths.
Focus on integrated tests for new functionality.
"""

import pytest
from linkora.sources.local import LocalSource
from linkora.sources.protocol import PaperQuery


class TestLocalSourceMultiPath:
    """Tests for LocalSource with multiple paths."""

    @pytest.fixture
    def multi_path_setup(self, tmp_path):
        """Create multiple directories with PDFs."""
        path1 = tmp_path / "papers1"
        path2 = tmp_path / "papers2"
        path1.mkdir()
        path2.mkdir()

        # Add PDF-like files to each path
        (path1 / "paper1.pdf").write_bytes(b"%PDF-1.4 test content 1")
        (path2 / "paper2.pdf").write_bytes(b"%PDF-1.4 test content 2")

        return path1, path2

    def test_single_path_scan(self, multi_path_setup):
        """Scan single path returns correct candidates."""
        path1, _ = multi_path_setup
        source = LocalSource(pdf_dirs=[path1])

        candidates = list(source.search(query=PaperQuery()))

        assert len(candidates) >= 1

    def test_multi_path_scan(self, multi_path_setup):
        """Scan multiple paths returns unified candidates."""
        path1, path2 = multi_path_setup
        source = LocalSource(pdf_dirs=[path1, path2])

        candidates = list(source.search(query=PaperQuery()))

        # Should find PDFs from both paths
        assert len(candidates) >= 2

    def test_multi_path_count(self, multi_path_setup):
        """Multiple paths count is sum of all paths."""
        path1, path2 = multi_path_setup
        source = LocalSource(pdf_dirs=[path1, path2])

        count = source.count()

        # Should count PDFs from all paths
        assert count >= 2

    def test_single_path_count(self, multi_path_setup):
        """Single path count is correct."""
        path1, _ = multi_path_setup
        source = LocalSource(pdf_dirs=[path1])

        count = source.count()

        assert count >= 1

    def test_empty_path_handling(self, tmp_path):
        """Empty directory is handled correctly."""
        empty_path = tmp_path / "empty"
        empty_path.mkdir()

        source = LocalSource(pdf_dirs=[empty_path])

        candidates = list(source.search(query=PaperQuery()))

        assert len(candidates) == 0

    def test_nonexistent_path_handling(self, tmp_path):
        """Nonexistent path is handled gracefully."""
        nonexistent = tmp_path / "nonexistent"

        # Should not raise, just skip
        source = LocalSource(pdf_dirs=[nonexistent])

        candidates = list(source.search(query=PaperQuery()))

        assert len(candidates) == 0

    def test_mixed_valid_invalid_paths(self, multi_path_setup):
        """Mixed valid and invalid paths work correctly."""
        path1, _ = multi_path_setup
        parent = path1.parent
        nonexistent = parent / "nonexistent"

        source = LocalSource(pdf_dirs=[path1, nonexistent])

        candidates = list(source.search(query=PaperQuery()))

        # Should find PDFs from valid path
        assert len(candidates) >= 1


class TestLocalSourceMultiPathQuery:
    """Tests for querying with multi-path LocalSource."""

    @pytest.fixture
    def setup_with_titles(self, tmp_path):
        """Create paths with different paper titles."""
        path1 = tmp_path / "physics"
        path2 = tmp_path / "math"
        path1.mkdir()
        path2.mkdir()

        # Physics paper
        (path1 / "einstein1905.pdf").write_bytes(b"%PDF-1.4")

        # Math paper
        (path2 / "eulerformula.pdf").write_bytes(b"%PDF-1.4")

        return path1, path2

    def test_query_filters_by_title(self, setup_with_titles):
        """Query with title filter works across paths."""
        path1, path2 = setup_with_titles
        source = LocalSource(pdf_dirs=[path1, path2])

        # Query for physics
        query = PaperQuery(title="einstein")
        candidates = list(source.search(query=query))

        # Should find the physics paper
        assert any("einstein" in c.title.lower() for c in candidates if c.title)


class TestLocalSourceMultiPathRecursive:
    """Tests for recursive scanning with multi-path."""

    def test_recursive_scan(self, tmp_path):
        """Recursive scanning finds nested PDFs."""
        # Create nested structure
        top = tmp_path / "top"
        sub1 = top / "sub1"
        sub2 = top / "sub2"
        top.mkdir()
        sub1.mkdir()
        sub2.mkdir()

        (top / "root.pdf").write_bytes(b"%PDF-1.4")
        (sub1 / "nested1.pdf").write_bytes(b"%PDF-1.4")
        (sub2 / "nested2.pdf").write_bytes(b"%PDF-1.4")

        source = LocalSource(pdf_dirs=[top], recursive=True)

        candidates = list(source.search(query=PaperQuery()))

        # Should find all 3 PDFs
        assert len(candidates) >= 3

    def test_non_recursive_scan(self, tmp_path):
        """Non-recursive scanning finds only top-level PDFs."""
        # Create nested structure
        top = tmp_path / "top"
        sub = top / "sub"
        top.mkdir()
        sub.mkdir()

        (top / "root.pdf").write_bytes(b"%PDF-1.4")
        (sub / "nested.pdf").write_bytes(b"%PDF-1.4")

        source = LocalSource(pdf_dirs=[top], recursive=False)

        candidates = list(source.search(query=PaperQuery()))

        # Should find only 1 PDF (root)
        assert len(candidates) >= 1
        assert not any("nested" in (c.source or "").lower() for c in candidates)
