"""
filters.py — linkora Paper Filter Module

Contains filter types and protocols.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


# ============================================================================
#  Filter Protocol
# ============================================================================


class PaperFilter(Protocol):
    """Protocol for paper filters."""

    def matches(self, meta: dict) -> bool:
        """Check if paper metadata matches filter."""
        ...


# ============================================================================
#  Filter Parameters
# ============================================================================


@dataclass(frozen=True)
class PaperFilterParams:
    """Immutable filter parameters."""

    year: str | None = None
    journal: str | None = None
    paper_type: str | None = None
    author: str | None = None

    def matches(self, meta: dict) -> bool:
        """Check if paper metadata matches filter."""
        # Year filter
        if self.year:
            if self.year.startswith(">"):
                min_year = int(self.year[1:])
                py = meta.get("year")
                # year > N: return False if year <= N
                if not isinstance(py, int) or py <= min_year:
                    return False
            elif self.year.startswith("<"):
                max_year = int(self.year[1:])
                py = meta.get("year")
                # year < N: return False if year >= N
                if not isinstance(py, int) or py >= max_year:
                    return False
            elif "-" in self.year:
                parts = self.year.split("-")
                if len(parts) == 2:
                    start, end = int(parts[0]), int(parts[1])
                    py = meta.get("year")
                    if not isinstance(py, int) or not (start <= py <= end):
                        return False
            else:
                # Exact year match
                target_year = int(self.year)
                py = meta.get("year")
                if not isinstance(py, int) or py != target_year:
                    return False

        # Journal filter
        if self.journal:
            journal = meta.get("journal")
            if not journal or not isinstance(journal, str):
                return False
            if self.journal.lower() not in journal.lower():
                return False

        # Paper type filter
        if self.paper_type:
            ptype = meta.get("paper_type")
            if not ptype or not isinstance(ptype, str):
                return False
            if self.paper_type.lower() != ptype.lower():
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
