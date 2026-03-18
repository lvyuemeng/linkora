"""Unit tests for hash.py - pure functions + edge cases."""

import pytest
from linkora.hash import compute_content_hash, compute_full_hash


class TestComputeContentHash:
    """Tests for compute_content_hash()."""

    def test_basic_title(self):
        """Simple title hash."""
        result = compute_content_hash("Deep Learning")
        assert len(result) == 12

    def test_title_with_abstract(self):
        """Title + abstract hash."""
        result = compute_content_hash(
            "Deep Learning",
            abstract="This paper proposes...",
        )
        assert len(result) == 12

    def test_empty_title(self):
        """Edge case: empty title."""
        result = compute_content_hash("")
        assert len(result) == 12

    def test_unicode_title(self):
        """Unicode handling."""
        result = compute_content_hash("深度学习")
        assert len(result) == 12

    def test_deterministic(self):
        """Same input → same output."""
        h1 = compute_content_hash("Test", "Abstract")
        h2 = compute_content_hash("Test", "Abstract")
        assert h1 == h2

    # Edge cases
    def test_very_long_title(self):
        """Edge: Very long title (10KB)."""
        long_title = "A" * 10000
        result = compute_content_hash(long_title)
        assert len(result) == 12

    def test_special_characters(self):
        """Edge: Special characters in title."""
        result = compute_content_hash("Test: Paper (2024) - vol. 1")
        assert len(result) == 12

    def test_abstract_none(self):
        """Edge: None abstract."""
        result = compute_content_hash("Title", None)
        assert len(result) == 12

    def test_abstract_empty_string(self):
        """Edge: Empty string abstract."""
        result = compute_content_hash("Title", "")
        assert len(result) == 12


class TestComputeFullHash:
    """Tests for compute_full_hash()."""

    def test_full_metadata(self):
        """Complete metadata hash."""
        meta = {
            "title": "Test Paper",
            "authors": ["Smith", "Doe"],
            "year": 2024,
            "journal": "Nature",
            "abstract": "Test abstract",
            "doi": "10.1234/test",
            "paper_type": "article",
        }
        result = compute_full_hash(meta)
        assert len(result) == 12

    def test_missing_fields(self):
        """Handle missing optional fields."""
        meta = {"title": "Test"}
        result = compute_full_hash(meta)
        assert len(result) == 12

    def test_citation_count_dict(self):
        """Citation count as dict."""
        meta = {"title": "Test", "citation_count": {"s2": 10, "openalex": 5}}
        result = compute_full_hash(meta)
        assert len(result) == 12

    def test_references_list(self):
        """References as list."""
        meta = {"title": "Test", "references": ["10.1/a", "10.1/b"]}
        result = compute_full_hash(meta)
        assert len(result) == 12

    # Edge cases
    def test_full_hash_empty_metadata(self):
        """Edge: Empty metadata dict."""
        result = compute_full_hash({})
        assert len(result) == 12

    def test_full_hash_citation_none(self):
        """Edge: Citation count as None."""
        meta = {"title": "Test", "citation_count": None}
        result = compute_full_hash(meta)
        assert len(result) == 12

    def test_full_hash_citation_wrong_type(self):
        """Edge: Citation count as wrong type (string)."""
        meta = {"title": "Test", "citation_count": "not-a-dict"}
        result = compute_full_hash(meta)
        assert len(result) == 12

    def test_full_hash_all_fields_none(self):
        """Edge: All optional fields are None or empty."""
        meta = {
            "title": None,
            "authors": None,
            "year": None,
            "journal": None,
            "abstract": None,
            "l3_conclusion": None,
            "doi": None,
            "paper_type": None,
            "citation_count": None,
            "references": None,
        }
        result = compute_full_hash(meta)
        assert len(result) == 12
