"""scholaraio.index — Search Index Module

This module provides FTS5 full-text search and vector semantic search.

Usage:
    from scholaraio.index import SearchIndex, VectorIndex

    # FTS5 search
    index = SearchIndex(db_path)
    results = index.search("turbulence")

    # Vector search
    vindex = VectorIndex(db_path)
    results = vindex.search("turbulence drag reduction", top_k=10)
"""

from scholaraio.index.text import SearchIndex, FilterParams, SearchMode
from scholaraio.index.vector import (
    VectorIndex,
    Embedder,
    ModelStore,
    build_vectors,
    vsearch,
    _unpack,
    build_faiss_index,
    load_existing_hashes,
    save_embeddings,
    load_metadata,
    invalidate_faiss,
)

__all__ = [
    # FTS
    "SearchIndex",
    "FilterParams",
    "SearchMode",
    # Vector
    "VectorIndex",
    "Embedder",
    "ModelStore",
    "build_vectors",
    "vsearch",
    "_unpack",
    "build_faiss_index",
    "load_existing_hashes",
    "save_embeddings",
    "load_metadata",
    "invalidate_faiss",
]
