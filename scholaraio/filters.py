"""
filters.py — ScholarAIO Paper Filter Module

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
                if not meta.get("year") or meta["year"] < min_year:
                    return False
            elif self.year.startswith("<"):
                max_year = int(self.year[1:])
                if not meta.get("year") or meta["year"] > max_year:
                    return False
            elif "-" in self.year:
                parts = self.year.split("-")
                if len(parts) == 2:
                    start, end = int(parts[0]), int(parts[1])
                    py = meta.get("year")
                    if not py or not (start <= py <= end):
                        return False

        # Journal filter
        if self.journal:
            journal = meta.get("journal", "").lower()
            if self.journal.lower() not in journal:
                return False

        # Paper type filter
        if self.paper_type:
            ptype = meta.get("paper_type", "").lower()
            if self.paper_type.lower() != ptype:
                return False

        # Author filter
        if self.author:
            authors = meta.get("authors", [])
            author_lower = self.author.lower()
            if not any(author_lower in a.lower() for a in authors):
                return False

        return True
