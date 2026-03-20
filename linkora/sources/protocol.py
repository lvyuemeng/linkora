"""sources/protocol.py — PaperSource Protocol for all data sources.

Redesigned from scratch - no backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Iterator


# ============================================================================
#  Query Types
# ============================================================================


@dataclass(frozen=True)
class PaperQuery:
    """Structured query for paper search.

    All fields optional - sources handle field combinations.
    """

    doi: str = ""
    issn: str = ""
    author: str = ""
    title: str = ""
    year_start: int | None = None
    year_end: int | None = None

    @property
    def is_empty(self) -> bool:
        """Check if query has no criteria."""
        return not any(
            x
            for x in (self.doi, self.issn, self.author, self.title, self.year_start)
            if x
        )

    @property
    def has_structured(self) -> bool:
        """Check if using structured query."""
        return any(
            x
            for x in (self.doi, self.issn, self.author, self.title, self.year_start)
            if x
        )


# ============================================================================
#  Result Types
# ============================================================================


@dataclass(frozen=True)
class PaperCandidate:
    """Standardized paper result from any source.

    All fields required except optional ones marked with = None.
    """

    id: str  # Unique identifier (DOI preferred)
    doi: str  # DOI (bare, no URL prefix)
    title: str  # Paper title
    authors: list[str]  # List of author names
    source: str  # Source name (e.g., "openalex")
    year: int | None = None  # Publication year
    journal: str | None = None
    abstract: str | None = None
    cited_by_count: int = 0
    paper_type: str | None = None
    pdf_url: str | None = None  # URL to download PDF
    source_id: str | None = None  # Source-specific ID


# ============================================================================
#  Source Protocol
# ============================================================================


class PaperSource(Protocol):
    """Protocol for paper data sources.

    Redesigned from scratch - no backward compatibility.
    """

    @property
    def name(self) -> str:
        """Return source name (e.g., 'local', 'openalex', 'zotero')."""
        ...

    def search(self, query: PaperQuery) -> Iterator[PaperCandidate]:
        """Search papers matching query.

        Args:
            query: PaperQuery with search criteria

        Yields:
            PaperCandidate instances matching the query
        """
        ...

    def fetch_by_id(self, paper_id: str) -> PaperCandidate | None:
        """Fetch single paper by ID.

        Args:
            paper_id: DOI (preferred) or source-specific ID

        Returns:
            PaperCandidate if found, None otherwise
        """
        ...


class SourceDispatcher(Protocol):
    """Protocol for selecting sources based on query."""

    def select(self, query: PaperQuery) -> list[PaperSource]:
        """Select sources to query based on query fields.

        Args:
            query: PaperQuery to determine which sources to use

        Returns:
            List of source instances to query
        """
        ...


# ============================================================================
#  Shared Helper Functions
# ============================================================================


def matches_query(candidate: PaperCandidate, query: PaperQuery) -> bool:
    """Check if candidate matches query - shared implementation.

    Args:
        candidate: PaperCandidate to check
        query: PaperQuery with search criteria

    Returns:
        True if candidate matches query, False otherwise
    """
    # DOI exact match
    if query.doi and candidate.doi:
        if query.doi.lower() == candidate.doi.lower():
            return True
        if query.doi.lower() in candidate.doi.lower():
            return True

    # Title fuzzy match
    if query.title and candidate.title:
        if query.title.lower() in candidate.title.lower():
            return True

    # Author match
    if query.author and candidate.authors:
        author_lower = query.author.lower()
        for author in candidate.authors:
            if author_lower in author.lower():
                return True

    # Year range match
    if query.year_start and candidate.year:
        year_end = query.year_end or query.year_start
        if not (query.year_start <= candidate.year <= year_end):
            return False

    # If query has criteria but none matched, skip
    if query.has_structured and not (
        (query.doi and candidate.doi)
        or (query.title and candidate.title)
        or (query.author and candidate.authors)
        or query.year_start
    ):
        return False

    return True


# ============================================================================
#  Exceptions
# ============================================================================


class SourceError(Exception):
    """Base exception for source errors."""

    pass
