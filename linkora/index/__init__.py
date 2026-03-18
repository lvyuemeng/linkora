"""linkora.index — Search Index Module

This module provides FTS5 full-text search and vector semantic search.

Usage:
    from linkora.index import SearchIndex, VectorIndex

    # FTS5 search
    index = SearchIndex(db_path)
    results = index.search("turbulence")

    # Vector search
    vindex = VectorIndex(db_path)
    results = vindex.search("turbulent drag reduction", top_k=10)
"""

from linkora.index.text import SearchIndex, FilterParams, SearchMode
from linkora.index.vector import (
    VectorIndex,
    FaissIndexConfig,
    Embedder,
    ModelStore,
)

__all__ = [
    # FTS
    "SearchIndex",
    "FilterParams",
    "SearchMode",
    # Vector
    "VectorIndex",
    "FaissIndexConfig",
    "Embedder",
    "ModelStore",
]
