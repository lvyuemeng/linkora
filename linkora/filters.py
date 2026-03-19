"""
filters.py — linkora Unified Filter Parameters

Unified filter parameters for all operations:
- In-memory filtering (matches method)
- SQL query generation (to_sql method)
- Vector search filtering

Uses data pipe flow pattern per AGENT.md philosophy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


# ============================================================================
#  Year Range Parsing (Pure Functions)
# ============================================================================


def parse_year_range(year: str) -> tuple[int | None, int | None]:
    """Parse year filter string to (start, end) tuple.

    Args:
        year: Year filter like "2024", ">2020", "<2024", "2020-2024"

    Returns:
        (start, end) tuple with None for unbounded
        Returns (None, None) for invalid format
    """
    year = year.strip()

    if not year:
        return None, None

    # Handle comparison operators (> or <)
    if year.startswith(">") or year.startswith("<"):
        op = year[0]
        num_str = year[1:].strip()
        if not num_str:
            return None, None
        try:
            val = int(num_str)
        except ValueError:
            return None, None
        return (val, None) if op == ">" else (None, val)

    # Range: "2020-2024" or "2020-" or "-2024"
    if "-" in year:
        parts = year.split("-", 1)
        start_str, end_str = parts[0], parts[1]

        try:
            start = int(start_str) if start_str.strip() else None
        except ValueError:
            start = None
        try:
            end = int(end_str) if end_str.strip() else None
        except ValueError:
            end = None

        return start, end

    # Single year
    try:
        return int(year), int(year)
    except ValueError:
        return None, None


def _year_matches(year: int, filter_str: str) -> bool:
    """Check if year matches filter string - flattened implementation.

    Args:
        year: Paper year
        filter_str: Filter like ">2020", "<2024", "2020-2024", "2024"

    Returns:
        True if year matches filter
    """
    # Exact year (no prefix, no dash)
    if not filter_str.startswith((">", "<")) and "-" not in filter_str:
        return year == int(filter_str)

    # Greater than: ">2020"
    if filter_str.startswith(">"):
        return year > int(filter_str[1:])

    # Less than: "<2024"
    if filter_str.startswith("<"):
        return year < int(filter_str[1:])

    # Range: "2020-2024"
    if "-" in filter_str:
        start, end = parse_year_range(filter_str)
        if start and year < start:
            return False
        if end and year > end:
            return False
        return True

    return True


# ============================================================================
#  Query Filter (Unified)
# ============================================================================


@dataclass(frozen=True)
class QueryFilter:
    """Unified filter parameters for all operations.

    Used by:
    - PaperStore.select() for in-memory filtering
    - SearchIndex for FTS queries
    - VectorIndex for semantic search

    Fields:
        year: Year filter (">2020", "<2024", "2020-2024", "2024")
        journal: Journal name (case-insensitive partial match)
        paper_type: Paper type (case-insensitive partial match)
        author: Author name (case-insensitive partial match in authors list)
    """

    year: str | None = None
    journal: str | None = None
    paper_type: str | None = None
    author: str | None = None

    def matches(self, meta: dict) -> bool:
        """Check if paper metadata matches filter - flattened implementation.

        Uses early returns to avoid deep nesting.

        Args:
            meta: Paper metadata dictionary

        Returns:
            True if all non-None filters match
        """
        # Year filter
        if self.year:
            py = meta.get("year")
            if not isinstance(py, int):
                return False
            if not _year_matches(py, self.year):
                return False

        # Journal filter
        if self.journal:
            j = meta.get("journal")
            if not j or not isinstance(j, str):
                return False
            if self.journal.lower() not in j.lower():
                return False

        # Paper type filter
        if self.paper_type:
            pt = meta.get("paper_type")
            if not pt or not isinstance(pt, str):
                return False
            if self.paper_type.lower() != pt.lower():
                return False

        # Author filter
        if self.author:
            authors = meta.get("authors")
            if not authors or not isinstance(authors, list):
                return False
            author_lower = self.author.lower()
            if not any(
                isinstance(a, str) and author_lower in a.lower() for a in authors
            ):
                return False

        return True

    def to_sql(self) -> tuple[str, list[str]]:
        """Convert to SQL WHERE clause and params.

        Returns:
            (where_clause, params) tuple
        """
        clauses: list[str] = []
        params: list[str] = []

        # Year filter
        if self.year:
            start, end = parse_year_range(self.year)
            if start is not None and end is not None:
                if start == end:
                    clauses.append("year = ?")
                    params.append(str(start))
                else:
                    clauses.append("year >= ? AND year <= ?")
                    params.extend([str(start), str(end)])
            elif start is not None:
                clauses.append("year >= ?")
                params.append(str(start))
            elif end is not None:
                clauses.append("year <= ?")
                params.append(str(end))

        # Journal filter
        if self.journal:
            clauses.append("journal LIKE ?")
            params.append(f"%{self.journal}%")

        # Paper type filter
        if self.paper_type:
            clauses.append("paper_type LIKE ?")
            params.append(f"%{self.paper_type}%")

        return (" AND ".join(clauses), params) if clauses else ("", [])


# ============================================================================
#  Protocol for Filter Consumers
# ============================================================================


class FilterConsumer(Protocol):
    """Protocol for objects that accept QueryFilter."""

    def select(self, filter: QueryFilter | None = None):
        """Select papers with filter."""
        ...

    def select_meta(self, filter: QueryFilter | None = None):
        """Select paper metadata with filter."""
        ...


__all__ = [
    "QueryFilter",
    "parse_year_range",
]
