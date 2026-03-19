"""Data source adapters (local files, remote APIs).

Redesigned to use PaperSource Protocol with unified interface.
No backward compatibility - fresh Protocol design.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from linkora.sources.protocol import (
    PaperCandidate,
    PaperQuery,
    PaperSource,
    SourceDispatcher,
    SourceError,
    matches_query,
)

if TYPE_CHECKING:
    from linkora.sources.local import LocalSource
    from linkora.sources.endnote import EndnoteSource
    from linkora.sources.zotero import ZoteroSource
    from linkora.sources.openalex import OpenAlexSource

__all__ = [
    # Protocol and types
    "PaperSource",
    "PaperQuery",
    "PaperCandidate",
    "SourceDispatcher",
    "SourceError",
    "matches_query",
    # Source classes
    "LocalSource",
    "EndnoteSource",
    "ZoteroSource",
    "OpenAlexSource",
]

_SOURCE_DEPENDENCIES = {
    "EndnoteSource": "endnote-utils (pip install endnote-utils)",
    "ZoteroSource": "pyzotero (pip install pyzotero)",
}


def __getattr__(name: str):
    """Lazy import for source classes supporting optional dependencies."""
    if name == "LocalSource":
        from linkora.sources.local import LocalSource

        return LocalSource
    elif name == "EndnoteSource":
        try:
            from linkora.sources.endnote import EndnoteSource
        except ImportError as e:
            raise ImportError(
                f"{name} requires optional dependency: {_SOURCE_DEPENDENCIES[name]}"
            ) from e

        return EndnoteSource
    elif name == "ZoteroSource":
        try:
            from linkora.sources.zotero import ZoteroSource
        except ImportError as e:
            raise ImportError(
                f"{name} requires optional dependency: {_SOURCE_DEPENDENCIES[name]}"
            ) from e

        return ZoteroSource
    elif name == "OpenAlexSource":
        from linkora.sources.openalex import OpenAlexSource

        return OpenAlexSource
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
