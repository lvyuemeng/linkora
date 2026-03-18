"""
vectors.py — Vector Embedding and Semantic Search
=================================================

Uses Qwen3-Embedding-0.6B (local ModelScope cache) to generate paper embeddings.
Embedding text = title + abstract, stored in index.db's paper_vectors table.

Usage:
    from linkora.vectors import VectorIndex, ModelStore

    # With singleton model store
    index = VectorIndex(db_path, config)
    index.build(papers_dir)
    results = index.search("turbulent drag reduction", top_k=5)
"""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

import faiss
import numpy as np

from linkora.hash import compute_content_hash
from linkora.log import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_log = get_logger(__name__)

# ============================================================================
# Data Structures (Pure Data, No Side Effects)
# ============================================================================


@dataclass(frozen=True)
class VectorFilterParams:
    """Filter parameters for vector search (immutable)."""

    year: str | None = None
    journal: str | None = None
    paper_type: str | None = None


@dataclass(frozen=True)
class EmbedTask:
    """Embedding task - pure data."""

    paper_id: str
    title: str
    abstract: str
    content_hash: str

    def to_text(self) -> str:
        """Combine title and abstract for embedding."""
        parts = [p for p in [self.title, self.abstract] if p]
        return "\n\n".join(parts)


@dataclass(frozen=True)
class EmbedResult:
    """Embedding result - pure data."""

    paper_id: str
    vector: list[float]
    content_hash: str


@dataclass(frozen=True)
class SearchResult:
    """Search result - pure data."""

    paper_id: str
    dir_name: str
    title: str
    authors: str
    year: str
    journal: str
    citation_count: str
    paper_type: str
    score: float


# ============================================================================
# Embedder Protocol (Dependency Injection)
# ============================================================================


class Embedder(Protocol):
    """Protocol for embedding models - enables dependency injection."""

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts."""
        ...


# ============================================================================
# FAISS Index Configuration
# ============================================================================


type FaissIndexType = Literal[
    "Flat", "FlatIP", "HNSW", "IVF256", "IVF512", "IVF1024", "IVF4096"
]


@dataclass(frozen=True)
class FaissIndexConfig:
    """Configuration for FAISS index.

    Args:
        index_type: Index type - "Flat", "FlatIP", "HNSW", or "IVF{size}".
        nlist: Number of clusters for IVF (default: 100).
        nprobe: Number of clusters to search for IVF (default: 10).
        hnsw_m: Number of connections for HNSW (default: 32).
        hnsw_ef: Search depth for HNSW (default: 128).
    """

    index_type: FaissIndexType = "FlatIP"
    nlist: int = 100
    nprobe: int = 10
    hnsw_m: int = 32
    hnsw_ef: int = 128

    def create_index(self, dim: int) -> faiss.Index:
        """Create FAISS index based on config."""
        if self.index_type == "Flat":
            return faiss.IndexFlatL2(dim)
        elif self.index_type == "FlatIP":
            return faiss.IndexFlatIP(dim)
        elif self.index_type == "HNSW":
            index = faiss.IndexHNSWFlat(dim, self.hnsw_m)
            index.hnsw.efSearch = self.hnsw_ef
            return index
        elif self.index_type.startswith("IVF"):
            nlist = int(self.index_type[3:])
            quantizer = faiss.IndexFlatIP(dim)
            return faiss.IndexIVFFlat(quantizer, dim, nlist)
        else:
            return faiss.IndexFlatIP(dim)


# ============================================================================
# Schemas (Constants)
# ============================================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_vectors (
    paper_id     TEXT PRIMARY KEY,
    embedding    BLOB NOT NULL,
    content_hash TEXT NOT NULL DEFAULT ''
);
"""

_MIGRATE_HASH = (
    "ALTER TABLE paper_vectors ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''"
)

# ============================================================================
# ModelStore Singleton (Resource Management)
# ============================================================================


class ModelStore:
    """Singleton model store with config resolution and method chaining.

    Manages SentenceTransformer model lifecycle with caching.
    Supports fluent API for configuration.
    """

    _instance: "ModelStore | None" = None
    _model_cache: dict = {}
    _initialized: bool = False

    def __new__(cls, config=None) -> "ModelStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config=None) -> None:
        if self._initialized:
            return
        self._config = config
        self._model: "SentenceTransformer | None" = None
        self._initialized = True

    def config(self, config) -> "ModelStore":
        """Set configuration and return self for chaining."""
        self._config = config
        return self

    def _resolve_config(self) -> tuple:
        """Resolve model config with defaults."""
        if self._config is not None:
            model_name = self._config.embed.model
            cache_dir = os.path.expanduser(self._config.embed.cache_dir)
            device_cfg = self._config.embed.device
            source = self._config.embed.source
        else:
            model_name = "Qwen/Qwen3-Embedding-0.6B"
            cache_dir = os.path.expanduser("~/.cache/modelscope/hub/models")
            device_cfg = "auto"
            source = "modelscope"

        # Resolve device
        if device_cfg == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
        else:
            device = device_cfg

        return model_name, cache_dir, device, source

    def _resolve_model_path(
        self, model_name: str, cache_dir: str, source: str
    ) -> str | None:
        """Find local model path or download via ModelScope."""
        if source != "modelscope":
            return None

        try:
            from modelscope import snapshot_download
        except ImportError:
            return None

        try:
            local_path = snapshot_download(
                model_name, cache_dir=cache_dir, local_files_only=True
            )
            return local_path
        except Exception as e:
            _log.debug("model not cached locally: %s", e)

        try:
            _log.info("[embed] downloading model %s from ModelScope", model_name)
            return snapshot_download(model_name, cache_dir=cache_dir)
        except Exception as e:
            _log.warning(
                "[embed] ModelScope download failed: %s, falling back to HuggingFace", e
            )
        return None

    def get_model(self):
        """Get or create SentenceTransformer model."""
        if self._model is not None:
            return self._model

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        SentenceTransformer = importlib.import_module(
            "sentence_transformers"
        ).SentenceTransformer

        model_name, cache_dir, device, source = self._resolve_config()
        cache_key = (model_name, cache_dir, device)

        if cache_key in self._model_cache:
            self._model = self._model_cache[cache_key]
            return self._model

        local_path = self._resolve_model_path(model_name, cache_dir, source)
        if local_path:
            self._model = SentenceTransformer(local_path, device=device)
        else:
            _log.info("[embed] downloading model %s from HuggingFace", model_name)
            self._model = SentenceTransformer(model_name, device=device)

        self._model_cache[cache_key] = self._model
        return self._model

    def embed_text(self, text: str) -> list[float]:
        """Embed single text."""
        model = self.get_model()
        assert model is not None
        vec = model.encode([text], prompt_name="query", normalize_embeddings=True)
        return vec[0].tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts."""
        model = self.get_model()
        assert model is not None
        vecs = model.encode(texts, normalize_embeddings=True, batch_size=16)
        return vecs.tolist()

    def embed_task(self, task: EmbedTask) -> EmbedResult:
        """Embed single task."""
        text = task.to_text()
        vec = self.embed_text(text)
        return EmbedResult(task.paper_id, vec, task.content_hash)

    def embed_tasks(self, tasks: list[EmbedTask]) -> list[EmbedResult]:
        """Embed multiple tasks."""
        if not tasks:
            return []
        texts = [t.to_text() for t in tasks]
        vecs = self.embed_batch(texts)
        return [EmbedResult(t.paper_id, v, t.content_hash) for t, v in zip(tasks, vecs)]

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None
        cls._model_cache.clear()


# ============================================================================
# QwenEmbedder (BERTopic-Compatible Wrapper)
# ============================================================================


class QwenEmbedder:
    """BERTopic-compatible embedder wrapping ModelStore.

    Args:
        config: Optional Config for embedding model settings.
    """

    def __init__(self, config=None):
        self._store = ModelStore(config)

    def embed_documents(self, documents, verbose=False):

        return np.array(self._store.embed_batch(list(documents)), dtype="float32")

    def embed_words(self, words, verbose=False):
        return self.embed_documents(words, verbose)


# ============================================================================
# Utility Functions (Pure or Minimal Side Effects)
# ============================================================================


# ============================================================================
# Data Layer (No Side Effects)
# ============================================================================


def prepare_embed_tasks(store) -> list[EmbedTask]:
    """Prepare embedding tasks from PaperStore (pure data)."""
    tasks: list[EmbedTask] = []
    for pdir in store.iter_papers():
        try:
            meta = store.read_meta(pdir)
        except (ValueError, FileNotFoundError):
            continue

        paper_id = meta.get("id") or pdir.name
        title = (meta.get("title") or "").strip()
        abstract = (meta.get("abstract") or "").strip()

        if not title and not abstract:
            continue

        h = compute_content_hash(title, abstract)
        tasks.append(EmbedTask(paper_id, title, abstract, h))

    return tasks


def filter_tasks_by_hash(
    tasks: list[EmbedTask], existing_hashes: dict[str, str]
) -> tuple[list[EmbedTask], set[str]]:
    """Filter tasks by content hash (pure data).

    Returns:
        (tasks_to_embed, updated_ids)
    """
    to_embed = []
    updated_ids = set()

    for task in tasks:
        existing = existing_hashes.get(task.paper_id)
        if existing == task.content_hash:
            continue  # unchanged
        if existing is not None:
            updated_ids.add(task.paper_id)
        to_embed.append(task)

    return to_embed, updated_ids


def prepare_search_results(
    faiss_results: list[tuple[str, float]],
    meta_map: dict,
    dir_map: dict,
) -> list[SearchResult]:
    """Prepare search results from FAISS results (pure data)."""
    results = []
    for paper_id, score in faiss_results:
        meta = meta_map.get(paper_id, {})
        results.append(
            SearchResult(
                paper_id=paper_id,
                dir_name=dir_map.get(paper_id, ""),
                title=meta.get("title") or paper_id,
                authors=meta.get("authors") or "",
                year=meta.get("year") or "",
                journal=meta.get("journal") or "",
                citation_count=meta.get("citation_count") or "",
                paper_type=meta.get("paper_type") or "",
                score=float(score),
            )
        )
    return results


def _year_in_range(year_str: str, start: int | None, end: int | None) -> bool:
    """Check if year is within range (pure data)."""
    try:
        y = int(year_str) if year_str else None
        if y is None:
            return False
        if start is not None and y < start:
            return False
        if end is not None and y > end:
            return False
        return True
    except (ValueError, TypeError):
        return False


def filter_results(
    results: list[SearchResult],
    filters: VectorFilterParams,
    paper_ids: set[str] | None = None,
) -> list[SearchResult]:
    """Filter search results (pure data)."""
    from linkora.papers import parse_year_range

    filtered = results

    # Filter by paper IDs
    if paper_ids is not None:
        filtered = [r for r in filtered if r.paper_id in paper_ids]

    # Filter by year range
    if filters.year:
        start, end = parse_year_range(filters.year)
        filtered = [r for r in filtered if _year_in_range(r.year, start, end)]

    # Filter by journal
    if filters.journal:
        j_lower = filters.journal.lower()
        filtered = [r for r in filtered if j_lower in r.journal.lower()]

    # Filter by paper type
    if filters.paper_type:
        t_lower = filters.paper_type.lower()
        filtered = [r for r in filtered if t_lower in r.paper_type.lower()]

    return filtered


# ============================================================================
# Vector Index Class (Combines Data + Side Effects)
# ============================================================================


class VectorIndex:
    """Vector search index - fully encapsulated, streamlined."""

    def __init__(
        self,
        db_path: Path,
        config=None,
        faiss_config: FaissIndexConfig | None = None,
    ) -> None:
        """Initialize vector index.

        Args:
            db_path: SQLite database path.
            config: Optional Config instance for embedding model settings.
            faiss_config: Optional FAISS index configuration.
        """
        self._db_path = db_path
        self._config = config
        self._faiss_config = faiss_config or FaissIndexConfig()
        self._conn: sqlite3.Connection | None = None
        self._faiss_index: faiss.Index | None = None
        self._faiss_ids: list[str] | None = None
        self._store = ModelStore(config)

    @property
    def db_path(self) -> Path:
        """Database path (read-only)."""
        return self._db_path

    # -------------------------------------------------------------------------
    # Core Operations (7 private methods)
    # -------------------------------------------------------------------------

    def _init_db(self) -> sqlite3.Connection:
        """Initialize database connection and schema (lazy)."""
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute(_SCHEMA)
            cols = {
                row[1] for row in self._conn.execute("PRAGMA table_info(paper_vectors)")
            }
            if "content_hash" not in cols:
                self._conn.execute(_MIGRATE_HASH)
        return self._conn

    def _load_metadata(self) -> tuple[dict, dict]:
        """Load metadata from papers and papers_registry tables."""
        conn = self._init_db()
        meta_map, dir_map = {}, {}

        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "papers" in tables:
            conn.row_factory = sqlite3.Row
            meta_map = {
                r["paper_id"]: dict(r)
                for r in conn.execute(
                    "SELECT paper_id, title, authors, year, journal, citation_count, paper_type FROM papers"
                )
            }

        if "papers_registry" in tables:
            dir_map = dict(conn.execute("SELECT id, dir_name FROM papers_registry"))

        return meta_map, dir_map

    def _faiss_paths(self) -> tuple[Path, Path]:
        """Get FAISS cache paths."""
        return (
            self._db_path.parent / "faiss.index",
            self._db_path.parent / "faiss_ids.json",
        )

    def _invalidate_cache(self) -> None:
        """Delete cached FAISS index files."""
        self._faiss_index = None
        self._faiss_ids = None
        for p in self._faiss_paths():
            p.unlink(missing_ok=True)

    def _get_faiss(self) -> tuple[faiss.Index, list[str]]:
        """Get FAISS index - load from cache or build from DB."""
        if self._faiss_index is not None and self._faiss_ids is not None:
            return self._faiss_index, self._faiss_ids

        idx_p, ids_p = self._faiss_paths()

        # Try load from cache
        if idx_p.exists() and ids_p.exists():
            try:
                self._faiss_index = faiss.read_index(str(idx_p))
                self._faiss_ids = json.loads(ids_p.read_text("utf-8"))
                if self._faiss_ids is None:
                    self._faiss_ids = []
                return self._faiss_index, self._faiss_ids  # type: ignore[return-value]
            except Exception as e:
                _log.debug("Failed to load FAISS cache: %s", e)

        # Build from database
        conn = self._init_db()
        rows = conn.execute("SELECT paper_id, embedding FROM paper_vectors").fetchall()

        if not rows:
            raise FileNotFoundError("No vectors in database")

        paper_ids = [r[0] for r in rows]
        dim = len(rows[0][1]) // 4
        vectors = (
            np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32)
            .reshape(-1, dim)
            .astype(np.float32)
        )
        faiss.normalize_L2(vectors)

        self._faiss_index = self._faiss_config.create_index(dim)
        self._faiss_index.add(vectors)  # type: ignore[no-untyped-call]
        self._faiss_ids = paper_ids

        # Save to cache
        faiss.write_index(self._faiss_index, str(idx_p))
        ids_p.write_text(json.dumps(paper_ids, ensure_ascii=False) + "\n")

        return self._faiss_index, self._faiss_ids

    def _append_to_faiss(self, new_ids: list[str], new_vecs: list[list[float]]) -> None:
        """Append new vectors to existing FAISS index."""
        idx_p, ids_p = self._faiss_paths()
        if not idx_p.exists() or not ids_p.exists():
            return

        index, paper_ids = self._get_faiss()

        # Handle None cases - FIX: proper null handling
        if index is None:
            self._invalidate_cache()
            return

        if paper_ids is None:
            paper_ids = []

        if set(new_ids) & set(paper_ids):
            self._invalidate_cache()
            return

        arr = np.array(new_vecs, dtype="float32")
        faiss.normalize_L2(arr)
        index.add(arr)  # type: ignore[no-untyped-call]
        paper_ids.extend(new_ids)

        faiss.write_index(index, str(idx_p))  # type: ignore[no-untyped-call]
        ids_p.write_text(json.dumps(paper_ids, ensure_ascii=False) + "\n")
        self._faiss_index = index
        self._faiss_ids = paper_ids

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_vector_blobs(self) -> list[tuple[str, bytes]]:
        """Get all paper vectors as (paper_id, embedding_blob).

        Used when you need raw blobs.
        """
        return (
            self._init_db()
            .execute("SELECT paper_id, embedding FROM paper_vectors")
            .fetchall()
        )

    def get_vectors(self) -> tuple[list[str], np.ndarray]:
        """Get all paper vectors as numpy array.

        Returns:
            Tuple of (paper_ids, embeddings_matrix).

        Used by TopicTrainer for topic modeling.
        """
        rows = self.get_vector_blobs()
        if not rows:
            return [], np.array([])

        paper_ids = [r[0] for r in rows]
        dim = len(rows[0][1]) // 4
        vectors = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(
            -1, dim
        )
        faiss.normalize_L2(vectors)
        return paper_ids, vectors

    def rebuild(self, store) -> int:
        """Full rebuild of vector index.

        Args:
            store: PaperStore instance.
        """
        conn = self._init_db()
        conn.execute("DELETE FROM paper_vectors")

        tasks = prepare_embed_tasks(store)
        if not tasks:
            return 0

        _log.info("embedding %d papers", len(tasks))
        results = self._store.embed_tasks(tasks)

        # Direct save using numpy
        for r in results:
            conn.execute(
                "INSERT OR REPLACE INTO paper_vectors (paper_id, embedding, content_hash) VALUES (?, ?, ?)",
                (
                    r.paper_id,
                    np.array(r.vector, dtype=np.float32).tobytes(),
                    r.content_hash,
                ),
            )
        conn.commit()

        if results:
            self._invalidate_cache()

        return len(results)

    def update(self, store) -> int:
        """Incrementally update vector index.

        Args:
            store: PaperStore instance.
        """
        conn = self._init_db()

        # Load existing hashes inline
        existing_hashes = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT paper_id, content_hash FROM paper_vectors"
            ).fetchall()
        }

        tasks = prepare_embed_tasks(store)
        to_embed, updated_ids = filter_tasks_by_hash(tasks, existing_hashes)

        if not to_embed:
            return 0

        _log.info("embedding %d papers", len(to_embed))
        results = self._store.embed_tasks(to_embed)

        # Direct save using numpy
        for r in results:
            conn.execute(
                "INSERT OR REPLACE INTO paper_vectors (paper_id, embedding, content_hash) VALUES (?, ?, ?)",
                (
                    r.paper_id,
                    np.array(r.vector, dtype=np.float32).tobytes(),
                    r.content_hash,
                ),
            )
        conn.commit()

        if updated_ids:
            self._invalidate_cache()
        elif results:
            self._append_to_faiss(
                [x.paper_id for x in results], [x.vector for x in results]
            )

        return len(results)

    # -------------------------------------------------------------------------
    # Search Methods
    # -------------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        year: str | None = None,
        journal: str | None = None,
        paper_type: str | None = None,
        paper_ids: set[str] | None = None,
    ) -> list[dict]:
        """Semantic vector search using FAISS.

        Args:
            query: Natural language query text.
            top_k: Maximum number of results.
            year: Year filter.
            journal: Journal name filter.
            paper_type: Paper type filter.
            paper_ids: Optional paper UUID whitelist.

        Returns:
            List of paper dictionaries with paper_id, title, authors, year, journal, score.
        """
        if not self._db_path.exists():
            raise FileNotFoundError(
                f"Index file not found: {self._db_path}\nRun `linkora index` first."
            )

        # Check vectors exist
        conn = self._init_db()
        has_vectors = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_vectors'"
        ).fetchone()
        if not has_vectors:
            raise FileNotFoundError(
                "Vector index not found. Run `linkora embed` first."
            )

        index, faiss_ids = self._get_faiss()
        if index is None or not faiss_ids:
            return []

        # Embed query
        q_vec = np.array([self._store.embed_text(query)], dtype="float32")
        q_vec /= np.linalg.norm(q_vec, axis=1, keepdims=True)

        # Search FAISS
        fetch_k = top_k * 5 if (year or journal or paper_type or paper_ids) else top_k
        fetch_k = min(fetch_k, index.ntotal)
        scores, indices = index.search(q_vec, fetch_k)  # type: ignore[no-untyped-call]

        # Load metadata and prepare results
        meta_map, dir_map = self._load_metadata()
        faiss_results = [
            (faiss_ids[idx], scores[0][i])
            for i, idx in enumerate(indices[0])
            if idx >= 0
        ]
        results = prepare_search_results(faiss_results, meta_map, dir_map)

        # Filter
        filters = VectorFilterParams(year=year, journal=journal, paper_type=paper_type)
        filtered = filter_results(results, filters, paper_ids)

        return [
            {
                "paper_id": r.paper_id,
                "dir_name": r.dir_name,
                "title": r.title,
                "authors": r.authors,
                "year": r.year,
                "journal": r.journal,
                "citation_count": r.citation_count,
                "paper_type": r.paper_type,
                "score": r.score,
            }
            for r in filtered[:top_k]
        ]

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    def __enter__(self) -> "VectorIndex":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
        self._faiss_index = None
        self._faiss_ids = None
