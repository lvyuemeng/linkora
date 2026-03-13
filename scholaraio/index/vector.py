"""
vectors.py — Vector Embedding and Semantic Search
=================================================

Uses Qwen3-Embedding-0.6B (local ModelScope cache) to generate paper embeddings.
Embedding text = title + abstract, stored in index.db's paper_vectors table.

Usage:
    from scholaraio.vectors import VectorIndex, ModelStore

    # With singleton model store
    index = VectorIndex(db_path, config)
    index.build(papers_dir)
    results = index.search("turbulent drag reduction", top_k=5)
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scholaraio.hash import compute_content_hash

_log = logging.getLogger(__name__)

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

    def __new__(cls, config=None) -> "ModelStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config=None) -> None:
        if self._initialized:
            return
        self._config = config
        self._model = None
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
        vec = model.encode([text], prompt_name="query", normalize_embeddings=True)
        return vec[0].tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts."""
        model = self.get_model()
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
        import numpy as np

        return np.array(self._store.embed_batch(list(documents)), dtype="float32")

    def embed_words(self, words, verbose=False):
        return self.embed_documents(words, verbose)


# ============================================================================
# Utility Functions (Pure or Minimal Side Effects)
# ============================================================================


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _faiss_paths(db_path: Path) -> tuple[Path, Path]:
    """Return (faiss_index_path, faiss_ids_path) next to the db file."""
    parent = db_path.parent
    return parent / "faiss.index", parent / "faiss_ids.json"


# ============================================================================
# Data Layer (No Side Effects)
# ============================================================================


def prepare_embed_tasks(papers_dir: Path) -> list[EmbedTask]:
    """Prepare embedding tasks from papers directory (pure data)."""
    from scholaraio.papers import PaperStore

    store = PaperStore(papers_dir)
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


def filter_results(
    results: list[SearchResult],
    filters: VectorFilterParams,
    paper_ids: set[str] | None = None,
) -> list[SearchResult]:
    """Filter search results (pure data)."""
    from scholaraio.papers import parse_year_range

    filtered = results

    if paper_ids is not None:
        filtered = [r for r in filtered if r.paper_id in paper_ids]

    if filters.year:
        start, end = parse_year_range(filters.year)

        def year_ok(r: SearchResult) -> bool:
            try:
                y = int(r.year) if r.year else None
                if y is None:
                    return False
                if start is not None and y < start:
                    return False
                if end is not None and y > end:
                    return False
                return True
            except (ValueError, TypeError):
                return False

        filtered = [r for r in filtered if year_ok(r)]

    if filters.journal:
        j_lower = filters.journal.lower()
        filtered = [r for r in filtered if j_lower in r.journal.lower()]

    if filters.paper_type:
        t_lower = filters.paper_type.lower()
        filtered = [r for r in filtered if t_lower in r.paper_type.lower()]

    return filtered


# ============================================================================
# Side Effect Layer (DB, FAISS)
# ============================================================================


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create paper_vectors table and migrate schema if needed."""
    conn.execute(_SCHEMA)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(paper_vectors)")}
    if "content_hash" not in cols:
        conn.execute(_MIGRATE_HASH)


def load_existing_hashes(conn: sqlite3.Connection) -> dict[str, str]:
    """Load existing content hashes from database."""
    return {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT paper_id, content_hash FROM paper_vectors"
        ).fetchall()
    }


def save_embeddings(conn: sqlite3.Connection, results: list[EmbedResult]) -> None:
    """Save embeddings to database."""
    for result in results:
        conn.execute(
            "INSERT OR REPLACE INTO paper_vectors "
            "(paper_id, embedding, content_hash) VALUES (?, ?, ?)",
            (result.paper_id, _pack(result.vector), result.content_hash),
        )


def load_metadata(conn: sqlite3.Connection) -> tuple[dict, dict]:
    """Load metadata from FTS5 table. Returns (meta_map, dir_map)."""
    meta_map: dict = {}
    has_fts = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='papers'"
    ).fetchone()
    if has_fts:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT paper_id, title, authors, year, journal, citation_count, paper_type FROM papers"
        ).fetchall():
            meta_map[row["paper_id"]] = dict(row)

    dir_map: dict = {}
    has_reg = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='papers_registry'"
    ).fetchone()
    if has_reg:
        for row in conn.execute("SELECT id, dir_name FROM papers_registry").fetchall():
            dir_map[row[0]] = row[1]

    return meta_map, dir_map


def invalidate_faiss(db_path: Path) -> None:
    """Delete cached FAISS index files."""
    for p in _faiss_paths(db_path):
        p.unlink(missing_ok=True)


def append_faiss(
    db_path: Path, new_ids: list[str], new_vecs: list[list[float]]
) -> None:
    """Append new vectors to existing FAISS index."""
    import faiss
    import numpy as np

    idx_p, ids_p = _faiss_paths(db_path)

    if not idx_p.exists() or not ids_p.exists():
        return

    try:
        index = faiss.read_index(str(idx_p))
        paper_ids = json.loads(ids_p.read_text("utf-8"))
    except Exception as e:
        _log.debug("failed to load FAISS cache, rebuilding: %s", e)
        invalidate_faiss(db_path)
        return

    if set(new_ids) & set(paper_ids):
        invalidate_faiss(db_path)
        return

    arr = np.array(new_vecs, dtype="float32")
    faiss.normalize_L2(arr)
    index.add(arr)
    paper_ids.extend(new_ids)

    faiss.write_index(index, str(idx_p))
    ids_p.write_text(json.dumps(paper_ids, ensure_ascii=False) + "\n", encoding="utf-8")


def build_faiss_index(db_path: Path) -> tuple:
    """Build or load FAISS index from database."""
    import faiss
    import numpy as np

    idx_p, ids_p = _faiss_paths(db_path)

    if idx_p.exists() and ids_p.exists():
        index = faiss.read_index(str(idx_p))
        paper_ids = json.loads(ids_p.read_text("utf-8"))
        return index, paper_ids

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT paper_id, embedding FROM paper_vectors").fetchall()
    finally:
        conn.close()

    if not rows:
        raise FileNotFoundError("Vector index empty. Run `scholaraio embed` first.")

    expected_blob_len = len(rows[0][1])
    dim = expected_blob_len // 4
    if expected_blob_len == 0 or expected_blob_len % 4 != 0:
        raise ValueError(
            f"First embedding blob has invalid length: {expected_blob_len}"
        )

    valid_rows = []
    for r in rows:
        if len(r[1]) != expected_blob_len:
            _log.warning(
                "Skipping paper %s: blob length %d != expected %d",
                r[0],
                len(r[1]),
                expected_blob_len,
            )
            continue
        valid_rows.append(r)

    if not valid_rows:
        raise FileNotFoundError("No valid embedding rows after dimension check")

    paper_ids = [r[0] for r in valid_rows]
    vecs = np.array(
        [list(struct.unpack(f"{dim}f", r[1])) for r in valid_rows],
        dtype="float32",
    )
    faiss.normalize_L2(vecs)

    index = faiss.IndexFlatIP(dim)
    index.add(vecs)

    faiss.write_index(index, str(idx_p))
    ids_p.write_text(json.dumps(paper_ids, ensure_ascii=False) + "\n", encoding="utf-8")
    return index, paper_ids


# ============================================================================
# Vector Index Class (Combines Data + Side Effects)
# ============================================================================


class VectorIndex:
    """Vector search index with encapsulated DB connection and FAISS."""

    def __init__(self, db_path: Path, config=None) -> None:
        """Initialize vector index.

        Args:
            db_path: SQLite database path.
            config: Optional Config instance for embedding model settings.
        """
        self._db_path = db_path
        self._config = config
        self._conn: sqlite3.Connection | None = None
        self._faiss_index = None
        self._faiss_ids: list[str] | None = None
        self._store = ModelStore(config)

    @property
    def db_path(self) -> Path:
        return self._db_path

    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._ensure_connection()
        _ensure_schema(conn)

    # -------------------------------------------------------------------------
    # FAISS Index Management
    # -------------------------------------------------------------------------

    def _ensure_faiss(self) -> tuple:
        if self._faiss_index is not None:
            return self._faiss_index, self._faiss_ids

        index, paper_ids = build_faiss_index(self._db_path)
        self._faiss_index = index
        self._faiss_ids = paper_ids
        return index, paper_ids

    def _invalidate_cache(self) -> None:
        self._faiss_index = None
        self._faiss_ids = None
        invalidate_faiss(self._db_path)

    # -------------------------------------------------------------------------
    # Index Build Methods
    # -------------------------------------------------------------------------

    def rebuild(self, papers_dir: Path) -> int:
        """Full rebuild of vector index."""
        self._ensure_schema()
        conn = self._ensure_connection()

        # Clear existing data
        conn.execute("DELETE FROM paper_vectors")

        # Data layer: prepare tasks
        tasks = prepare_embed_tasks(papers_dir)
        if not tasks:
            return 0

        _log.info("embedding %d papers", len(tasks))

        # Execution: embed
        results = self._store.embed_tasks(tasks)

        # Side effect: save to DB
        save_embeddings(conn, results)
        conn.commit()

        # Side effect: rebuild FAISS
        if results:
            self._invalidate_cache()

        return len(results)

    def update(self, papers_dir: Path) -> int:
        """Incrementally update vector index."""
        self._ensure_schema()
        conn = self._ensure_connection()

        # Data: load existing hashes
        existing_hashes = load_existing_hashes(conn)

        # Data: prepare tasks
        tasks = prepare_embed_tasks(papers_dir)
        to_embed, updated_ids = filter_tasks_by_hash(tasks, existing_hashes)

        if not to_embed:
            return 0

        _log.info("embedding %d papers", len(to_embed))

        # Execution: embed
        results = self._store.embed_tasks(to_embed)

        # Side effect: save to DB
        save_embeddings(conn, results)
        conn.commit()

        # Side effect: update FAISS
        if updated_ids:
            self._invalidate_cache()
        elif results:
            append_faiss(
                self._db_path,
                [r.paper_id for r in results],
                [r.vector for r in results],
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
        import numpy as np

        if not self._db_path.exists():
            raise FileNotFoundError(
                f"Index file not found: {self._db_path}\nRun `scholaraio index` first."
            )

        # Check vectors exist
        conn = self._ensure_connection()
        has_vectors = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_vectors'"
        ).fetchone()
        if not has_vectors:
            raise FileNotFoundError(
                "Vector index not found. Run `scholaraio embed` first."
            )

        index, faiss_ids = self._ensure_faiss()

        # Execution: embed query
        q_vec = np.array([self._store.embed_text(query)], dtype="float32")
        np.linalg.norm(q_vec, axis=1, keepdims=True)
        q_vec /= np.linalg.norm(q_vec, axis=1, keepdims=True)

        # Search FAISS
        fetch_k = top_k * 5 if (year or journal or paper_type or paper_ids) else top_k
        fetch_k = min(fetch_k, index.ntotal)
        scores, indices = index.search(q_vec, fetch_k)

        # Data: load metadata
        meta_map, dir_map = load_metadata(conn)

        # Data: prepare results
        faiss_results = [
            (faiss_ids[idx], scores[0][i])
            for i, idx in enumerate(indices[0])
            if idx >= 0
        ]
        results = prepare_search_results(faiss_results, meta_map, dir_map)

        # Data: filter
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


# ===========================================================================-
# Legacy API (Required by External Callers)
# ============================================================================


def build_vectors(
    papers_dir: Path,
    db_path: Path,
    rebuild: bool = False,
    cfg=None,
) -> int:
    """Build or incrementally update vector index.

    Args:
        papers_dir: Papers directory to scan.
        db_path: SQLite database path.
        rebuild: If True, clear old data before building.
        cfg: Optional Config for embedding model settings.

    Returns:
        Number of papers indexed.
    """
    index = VectorIndex(db_path, cfg)
    try:
        if rebuild:
            return index.rebuild(papers_dir)
        else:
            return index.update(papers_dir)
    finally:
        index.close()


def vsearch(
    query: str,
    db_path: Path,
    top_k: int | None = None,
    cfg=None,
    *,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """Semantic vector search.

    Args:
        query: Natural language query.
        db_path: SQLite database path.
        top_k: Max results (defaults to cfg.embed.top_k if cfg provided).
        cfg: Optional Config for embedding model.
        year: Year filter.
        journal: Journal filter.
        paper_type: Paper type filter.
        paper_ids: Paper UUID whitelist.

    Returns:
        List of paper dictionaries sorted by score.
    """
    if top_k is None:
        top_k = cfg.embed.top_k if cfg is not None else 10

    index = VectorIndex(db_path, cfg)
    try:
        return index.search(
            query,
            top_k,
            year=year,
            journal=journal,
            paper_type=paper_type,
            paper_ids=paper_ids,
        )
    finally:
        index.close()


# Internal helpers for external modules
def _load_model(cfg=None):
    """Load SentenceTransformer model."""
    store = ModelStore(cfg)
    return store.get_model()


def _embed_text(text: str, cfg=None) -> list[float]:
    """Embed single text."""
    store = ModelStore(cfg)
    return store.embed_text(text)


def _embed_batch(texts: list[str], cfg=None) -> list[list[float]]:
    """Embed multiple texts."""
    store = ModelStore(cfg)
    return store.embed_batch(texts)


def _build_faiss_index(db_path: Path):
    """Build FAISS index."""
    return build_faiss_index(db_path)


def _build_faiss_from_db(
    db_path: Path,
    index_path: Path,
    ids_path: Path,
    *,
    empty_msg: str = "Vector index empty. Run `scholaraio embed` first.",
):
    """Build FAISS from explicit paths."""
    return build_faiss_index_from_paths(db_path, index_path, ids_path, empty_msg)


def _vsearch_faiss(
    query: str,
    index,
    paper_ids: list[str],
    top_k: int,
    cfg=None,
) -> list[tuple[str, float]]:
    """Run FAISS similarity search."""
    import faiss
    import numpy as np

    q_vec = np.array([_embed_text(query, cfg)], dtype="float32")
    faiss.normalize_L2(q_vec)

    fetch_k = min(top_k, index.ntotal)
    scores, indices = index.search(q_vec, fetch_k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        results.append((paper_ids[idx], float(score)))
    return results


# ============================================================================
# Internal Helper for External Legacy Function
# ============================================================================


def build_faiss_index_from_paths(
    db_path: Path,
    index_path: Path,
    ids_path: Path,
    empty_msg: str = "Vector index empty. Run `scholaraio embed` first.",
):
    """Build FAISS from explicit paths (internal)."""
    import faiss
    import numpy as np

    if index_path.exists() and ids_path.exists():
        index = faiss.read_index(str(index_path))
        paper_ids = json.loads(ids_path.read_text("utf-8"))
        return index, paper_ids

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT paper_id, embedding FROM paper_vectors").fetchall()
    finally:
        conn.close()

    if not rows:
        raise FileNotFoundError(empty_msg)

    expected_blob_len = len(rows[0][1])
    dim = expected_blob_len // 4
    if expected_blob_len == 0 or expected_blob_len % 4 != 0:
        raise ValueError(
            f"First embedding blob has invalid length: {expected_blob_len}"
        )

    valid_rows = []
    for r in rows:
        if len(r[1]) != expected_blob_len:
            _log.warning(
                "Skipping paper %s: blob length %d != expected %d",
                r[0],
                len(r[1]),
                expected_blob_len,
            )
            continue
        valid_rows.append(r)

    if not valid_rows:
        raise FileNotFoundError("No valid embedding rows after dimension check")

    paper_ids = [r[0] for r in valid_rows]
    vecs = np.array(
        [list(struct.unpack(f"{dim}f", r[1])) for r in valid_rows],
        dtype="float32",
    )
    faiss.normalize_L2(vecs)

    index = faiss.IndexFlatIP(dim)
    index.add(vecs)

    faiss.write_index(index, str(index_path))
    ids_path.write_text(
        json.dumps(paper_ids, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return index, paper_ids
