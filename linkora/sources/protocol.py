"""sources/protocol.py — PaperSource Protocol for all data sources."""

from __future__ import annotations

from typing import Protocol, Iterator


class PaperSource(Protocol):
    """Protocol for paper data sources (local files, remote APIs, databases).

    All paper sources (local directory, Endnote, Zotero, OpenAlex) implement
    this interface for unified access.

    Example:
        source: PaperSource = LocalSource(papers_dir=Path("data/papers"))
        for paper in source.fetch():
            print(paper["title"])
    """

    @property
    def name(self) -> str:
        """Return source name (e.g., 'local', 'endnote', 'zotero', 'openalex')."""
        ...

    def fetch(self, **kwargs) -> Iterator[dict]:
        """Fetch papers from source.

        Yields:
            Paper dict with standardized fields (id, title, authors, year, etc.)

        Raises:
            SourceError: If fetch fails
        """
        ...

    def count(self, **kwargs) -> int:
        """Count total papers available in source.

        Returns:
            Number of papers available

        Raises:
            SourceError: If count fails
        """
        ...


class SourceError(Exception):
    """Base exception for source errors."""

    pass
