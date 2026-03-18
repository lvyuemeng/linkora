"""Unit tests for filters.py - PaperFilterParams.matches() + edge cases."""

from linkora.filters import PaperFilterParams


class TestPaperFilterParams:
    """Tests for PaperFilterParams.matches()."""

    def test_no_filters(self):
        """No filters = match all."""
        f = PaperFilterParams()
        assert f.matches({"title": "Test"}) is True

    # === Year Filter Tests ===

    def test_year_exact(self):
        """Exact year match."""
        f = PaperFilterParams(year="2024")
        assert f.matches({"year": 2024}) is True
        assert f.matches({"year": 2023}) is False

    def test_year_greater_than(self):
        """Year > N filter."""
        f = PaperFilterParams(year=">2020")
        assert f.matches({"year": 2024}) is True
        assert f.matches({"year": 2020}) is False
        assert f.matches({"year": 2019}) is False

    def test_year_less_than(self):
        """Year < N filter."""
        f = PaperFilterParams(year="<2025")
        assert f.matches({"year": 2024}) is True
        assert f.matches({"year": 2025}) is False

    def test_year_range(self):
        """Year range filter."""
        f = PaperFilterParams(year="2020-2024")
        assert f.matches({"year": 2022}) is True
        assert f.matches({"year": 2019}) is False
        assert f.matches({"year": 2025}) is False

    def test_year_missing(self):
        """Missing year field."""
        f = PaperFilterParams(year=">2020")
        assert f.matches({}) is False

    # === Journal Filter Tests ===

    def test_journal_partial(self):
        """Partial journal match (case-insensitive)."""
        f = PaperFilterParams(journal="nature")
        assert f.matches({"journal": "Nature Physics"}) is True
        assert f.matches({"journal": "NATURE"}) is True
        assert f.matches({"journal": "Science"}) is False

    # === Paper Type Filter Tests ===

    def test_paper_type_exact(self):
        """Exact paper type match."""
        f = PaperFilterParams(paper_type="article")
        assert f.matches({"paper_type": "article"}) is True
        assert f.matches({"paper_type": "review"}) is False

    # === Author Filter Tests ===

    def test_author_partial(self):
        """Partial author match (case-insensitive)."""
        f = PaperFilterParams(author="smith")
        assert f.matches({"authors": ["John Smith", "Jane Doe"]}) is True
        assert f.matches({"authors": ["John Smith"]}) is True
        assert f.matches({"authors": ["John Doe"]}) is False

    # === Combined Filters ===

    def test_combined_filters(self):
        """Multiple filters together."""
        f = PaperFilterParams(year=">2020", journal="nature")
        assert f.matches({"year": 2024, "journal": "Nature Physics"}) is True
        assert f.matches({"year": 2024, "journal": "Science"}) is False
        assert f.matches({"year": 2019, "journal": "Nature Physics"}) is False

    # === Edge Cases ===

    def test_year_invalid_format(self):
        """Edge: Invalid year format (should not crash)."""
        f = PaperFilterParams(year="not-a-year")
        # Should return False for non-numeric comparison
        result = f.matches({"year": 2024})
        assert isinstance(result, bool)

    def test_year_out_of_range(self):
        """Edge: Year far outside typical range."""
        f = PaperFilterParams(year="1800-1900")
        assert f.matches({"year": 2024}) is False
        assert f.matches({"year": 1850}) is True

    def test_journal_none(self):
        """Edge: Journal field is None."""
        f = PaperFilterParams(journal="nature")
        assert f.matches({"journal": None}) is False

    def test_authors_not_list(self):
        """Edge: Authors is not a list."""
        f = PaperFilterParams(author="smith")
        # String instead of list
        assert f.matches({"authors": "John Smith"}) is False
        # Integer instead of list
        assert f.matches({"authors": 123}) is False

    def test_year_string_instead_of_int(self):
        """Edge: Year is string instead of int."""
        f = PaperFilterParams(year=">2020")
        assert f.matches({"year": "2024"}) is False
        assert f.matches({"year": "not-a-number"}) is False

    def test_combined_edge_cases(self):
        """Edge: Multiple edge cases combined."""
        f = PaperFilterParams(year=">2020", journal="nature", author="smith")

        # Missing fields
        assert f.matches({}) is False

        # Wrong types
        assert f.matches({"year": "2024", "journal": None, "authors": 123}) is False

        # Valid
        assert (
            f.matches(
                {
                    "year": 2024,
                    "journal": "Nature Physics",
                    "authors": ["John Smith"],
                }
            )
            is True
        )

    def test_year_zero(self):
        """Edge: Year is 0."""
        f = PaperFilterParams(year=">2000")
        assert f.matches({"year": 0}) is False

    def test_year_negative(self):
        """Edge: Year is negative."""
        f = PaperFilterParams(year=">2000")
        assert f.matches({"year": -1}) is False
