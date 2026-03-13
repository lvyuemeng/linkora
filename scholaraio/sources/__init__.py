"""Data source adapters (local files, Paperlib, etc.)

Refactored to use PaperSource Protocol with unified interface.

Note: All source classes are lazy-imported to support optional dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scholaraio.sources.protocol import PaperSource, SourceError

if TYPE_CHECKING:
    from scholaraio.sources.local import LocalSource
    from scholaraio.sources.endnote import EndnoteSource
    from scholaraio.sources.zotero import ZoteroSource
    from scholaraio.sources.openalex import OpenAlexSource

__all__ = [
    "PaperSource",
    "SourceError",
]


def __getattr__(name: str):
    """Lazy import for source classes supporting optional dependencies."""
    if name == "LocalSource":
        from scholaraio.sources.local import LocalSource
        return LocalSource
    elif name == "EndnoteSource":
        from scholaraio.sources.endnote import EndnoteSource
        return EndnoteSource
    elif name == "ZoteroSource":
        from scholaraio.sources.zotero import ZoteroSource
        return ZoteroSource
    elif name == "OpenAlexSource":
        from scholaraio.sources.openalex import OpenAlexSource
        return OpenAlexSource
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
