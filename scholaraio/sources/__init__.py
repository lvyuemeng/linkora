"""Data source adapters (local files, Paperlib, etc.)

Refactored to use PaperSource Protocol with unified interface.
"""

from scholaraio.sources.protocol import PaperSource, SourceError
from scholaraio.sources.local import LocalSource
from scholaraio.sources.endnote import EndnoteSource
from scholaraio.sources.zotero import ZoteroSource

__all__ = [
    "PaperSource",
    "SourceError",
    "LocalSource",
    "EndnoteSource",
    "ZoteroSource",
]
