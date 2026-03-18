# Vector Index & TopicTrainer Improvement Plan

> **Goal**: Remove `db_path` from public API, encapsulate all functions, use Literal type for FAISS index, streamline data pipe.

---

## 1. Consolidation Analysis

### Current Private Methods (15 methods proposed)

| Method | Purpose | Used By | Can Merge? |
|--------|---------|---------|------------|
| `_ensure_connection()` | Lazy DB conn | All DB ops | → `_init_db()` |
| `_ensure_schema()` | Create/migrate table | rebuild, update | → `_init_db()` |
| `_pack()` | Vector → bytes | _save_embeddings | Use numpy directly |
| `_unpack()` | Bytes → vector | topics.py (external!) | → Use numpy directly |
| `_load_existing_hashes()` | Load hashes | update() only | → Inline into update() |
| `_save_embeddings()` | Save to DB | rebuild, update | → Inline into callers |
| `_table_exists()` | Check table | _load_metadata only | → Inline into _load_metadata() |
| `_load_metadata()` | Load meta | search() only | Keep (complex) |
| `_faiss_paths()` | Cache paths | Multiple | Keep (simple) |
| `_invalidate_cache()` | Delete cache | rebuild, update, _append | Keep |
| `_load_faiss_index()` | Load FAISS | _append, _ensure_faiss | → Merge into `_get_faiss()` |
| `_save_faiss_index()` | Save FAISS | _append, _build | → Merge into `_get_faiss()` |
| `_append_faiss()` | Append vectors | update() only | Keep (complex) |
| `_build_faiss_index()` | Build FAISS | _ensure_faiss only | → Merge into `_get_faiss()` |
| `_unpack_embeddings()` | DB rows → numpy | _build_faiss only | → Merge into `_get_faiss()` |

### After Consolidation (7 methods)

| Method | Purpose |
|--------|---------|
| `_init_db()` | Lazy connection + schema init |
| `_load_metadata()` | Load meta from DB |
| `_get_faiss()` | Load or build FAISS index (unified) |
| `_invalidate_cache()` | Delete cache files |
| `_append_to_faiss()` | Append new vectors |
| `_serialize()` | Vector ↔ bytes (numpy-based) |
| `_faiss_paths()` | Get cache paths |

---

## 2. Streamlined Implementation

### Step 1: Use numpy directly for serialization

Instead of `_pack()` / `_unpack()`, use numpy's tobytes() / frombuffer():

```python
def _serialize(self, vectors: np.ndarray, paper_ids: list[str]) -> tuple[list[bytes], list[str]]:
    """Serialize vectors to blobs using numpy."""
    # vectors is already float32, shape (N, dim)
    return vectors.tobytes(), paper_ids

def _deserialize(self, blobs: list[bytes]) -> tuple[list[str], np.ndarray]:
    """Deserialize blobs to vectors using numpy."""
    # Reconstruct from bytes - dim comes from first blob
    dim = len(blobs[0]) // 4
    vectors = np.frombuffer(b''.join(blobs), dtype=np.float32).reshape(-1, dim)
    return vectors
```

### Step 2: Unified _get_faiss() method

```python
def _get_faiss(self) -> tuple[faiss.Index, list[str]]:
    """Get FAISS index - load from cache or build from DB.
    
    Single entry point for all FAISS index operations.
    """
    if self._faiss_index is not None:
        return self._faiss_index, self._faiss_ids
    
    idx_p, ids_p = self._faiss_paths()
    
    # Try load from cache
    if idx_p.exists() and ids_p.exists():
        try:
            self._faiss_index = faiss.read_index(str(idx_p))
            self._faiss_ids = json.loads(ids_p.read_text("utf-8"))
            return self._faiss_index, self._faiss_ids
        except Exception as e:
            _log.debug("Failed to load FAISS cache: %s", e)
    
    # Build from database
    rows = self._connection.execute(
        "SELECT paper_id, embedding FROM paper_vectors"
    ).fetchall()
    
    if not rows:
        return None, []
    
    # Unpack and normalize
    paper_ids = [r[0] for r in rows]
    dim = len(rows[0][1]) // 4
    vectors = np.frombuffer(
        b''.join(r[1] for r in rows), dtype=np.float32
    ).reshape(-1, dim).astype(np.float32)
    faiss.normalize_L2(vectors)
    
    # Create index
    self._faiss_index = self._faiss_config.create_index(dim)
    self._faiss_index.add(vectors)
    self._faiss_ids = paper_ids
    
    # Save to cache
    faiss.write_index(self._faiss_index, str(idx_p))
    ids_p.write_text(json.dumps(paper_ids, ensure_ascii=False) + "\n")
    
    return self._faiss_index, self._faiss_ids
```

### Step 3: Unified _init_db() method

```python
def _init_db(self) -> sqlite3.Connection:
    """Initialize database connection and schema (lazy)."""
    if self._conn is None:
        self._conn = sqlite3.connect(self._db_path)
        
        # Ensure schema
        self._conn.execute(_SCHEMA)
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(paper_vectors)")}
        if "content_hash" not in cols:
            self._conn.execute(_MIGRATE_HASH)
    
    return self._conn
```

### Step 4: Inline simple operations

For `update()` method:

```python
def update(self, store) -> int:
    """Incrementally update vector index."""
    conn = self._init_db()
    
    # Inline: load existing hashes
    existing_hashes = {
        r[0]: r[1] for r in conn.execute(
            "SELECT paper_id, content_hash FROM paper_vectors"
        ).fetchall()
    }
    
    tasks = prepare_embed_tasks(store)
    to_embed, updated_ids = filter_tasks_by_hash(tasks, existing_hashes)
    
    if not to_embed:
        return 0
    
    _log.info("embedding %d papers", len(to_embed))
    results = self._store.embed_tasks(to_embed)
    
    # Inline: save embeddings
    for r in results:
        conn.execute(
            "INSERT OR REPLACE INTO paper_vectors (paper_id, embedding, content_hash) VALUES (?, ?, ?)",
            (r.paper_id, r.vector.tobytes(), r.content_hash),  # numpy direct
        )
    conn.commit()
    
    # Handle cache
    if updated_ids:
        self._invalidate_cache()
    elif results:
        self._append_to_faiss([x.paper_id for x in results], [x.vector for x in results])
    
    return len(results)
```

---

## 3. Complete Streamlined VectorIndex

```python
class VectorIndex:
    """Vector search index - fully encapsulated, streamlined."""
    
    def __init__(
        self, 
        db_path: Path, 
        config = None,
        faiss_config: FaissIndexConfig | None = None,
    ) -> None:
        self._db_path = db_path
        self._config = config
        self._faiss_config = faiss_config or FaissIndexConfig()
        self._conn: sqlite3.Connection | None = None
        self._faiss_index: faiss.Index | None = None
        self._faiss_ids: list[str] | None = None
        self._store = ModelStore(config)
    
    # --- Core Operations (7 methods only) ---
    
    def _init_db(self) -> sqlite3.Connection:
        """Initialize database connection and schema (lazy)."""
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute(_SCHEMA)
            cols = {row[1] for row in self._conn.execute("PRAGMA table_info(paper_vectors)")}
            if "content_hash" not in cols:
                self._conn.execute(_MIGRATE_HASH)
        return self._conn
    
    def _load_metadata(self) -> tuple[dict, dict]:
        """Load metadata from papers and papers_registry tables."""
        conn = self._init_db()
        meta_map, dir_map = {}, {}
        
        # Check tables exist using single query
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        
        if "papers" in tables:
            conn.row_factory = sqlite3.Row
            meta_map = {
                r["paper_id"]: dict(r) for r in conn.execute(
                    "SELECT paper_id, title, authors, year, journal, citation_count, paper_type FROM papers"
                )
            }
        
        if "papers_registry" in tables:
            dir_map = dict(conn.execute("SELECT id, dir_name FROM papers_registry"))
        
        return meta_map, dir_map
    
    def _faiss_paths(self) -> tuple[Path, Path]:
        """Get FAISS cache paths."""
        return self._db_path.parent / "faiss.index", self._db_path.parent / "faiss_ids.json"
    
    def _invalidate_cache(self) -> None:
        """Delete cached FAISS index files."""
        self._faiss_index = None
        self._faiss_ids = None
        for p in self._faiss_paths():
            p.unlink(missing_ok=True)
    
    def _get_faiss(self) -> tuple[faiss.Index, list[str]]:
        """Get FAISS index - load from cache or build from DB."""
        if self._faiss_index is not None:
            return self._faiss_index, self._faiss_ids
        
        idx_p, ids_p = self._faiss_paths()
        
        # Try load
        if idx_p.exists() and ids_p.exists():
            try:
                self._faiss_index = faiss.read_index(str(idx_p))
                self._faiss_ids = json.loads(ids_p.read_text("utf-8"))
                return self._faiss_index, self._faiss_ids
            except Exception:
                pass  # Cache corrupted, rebuild
        
        # Build from DB
        rows = self._init_db().execute(
            "SELECT paper_id, embedding FROM paper_vectors"
        ).fetchall()
        
        if not rows:
            return None, []
        
        paper_ids = [r[0] for r in rows]
        dim = len(rows[0][1]) // 4
        vectors = np.frombuffer(b''.join(r[1] for r in rows), dtype=np.float32).reshape(-1, dim)
        faiss.normalize_L2(vectors)
        
        self._faiss_index = self._faiss_config.create_index(dim)
        self._faiss_index.add(vectors)
        self._faiss_ids = paper_ids
        
        # Save
        faiss.write_index(self._faiss_index, str(idx_p))
        ids_p.write_text(json.dumps(paper_ids, ensure_ascii=False) + "\n")
        
        return self._faiss_index, self._faiss_ids
    
    def _append_to_faiss(self, new_ids: list[str], new_vecs: list[list[float]]) -> None:
        """Append new vectors to existing FAISS index."""
        idx_p, ids_p = self._faiss_paths()
        if not idx_p.exists() or not ids_p.exists():
            return
        
        index, paper_ids = self._load_faiss_index()
        
        # Handle None cases
        if index is None:
            self._invalidate_cache()
            return
        
        paper_ids = paper_ids or []
        if set(new_ids) & set(paper_ids):
            self._invalidate_cache()
            return
        
        arr = np.array(new_vecs, dtype="float32")
        faiss.normalize_L2(arr)
        index.add(arr)
        paper_ids.extend(new_ids)
        
        faiss.write_index(index, str(idx_p))
        ids_p.write_text(json.dumps(paper_ids, ensure_ascii=False) + "\n")
        self._faiss_index = index
        self._faiss_ids = paper_ids
    
    # --- Public API ---
    
    @property
    def db_path(self) -> Path:
        return self._db_path
    
    def get_vector_blobs(self) -> list[tuple[str, bytes]]:
        """Get all paper vectors as (paper_id, embedding_blob)."""
        return self._init_db().execute(
            "SELECT paper_id, embedding FROM paper_vectors"
        ).fetchall()
    
    def rebuild(self, store) -> int:
        """Full rebuild."""
        conn = self._init_db()
        conn.execute("DELETE FROM paper_vectors")
        
        tasks = prepare_embed_tasks(store)
        if not tasks:
            return 0
        
        results = self._store.embed_tasks(tasks)
        
        # Direct save
        for r in results:
            conn.execute(
                "INSERT OR REPLACE INTO paper_vectors (paper_id, embedding, content_hash) VALUES (?, ?, ?)",
                (r.paper_id, np.array(r.vector, dtype=np.float32).tobytes(), r.content_hash),
            )
        conn.commit()
        
        if results:
            self._invalidate_cache()
        return len(results)
    
    def update(self, store) -> int:
        """Incremental update."""
        conn = self._init_db()
        
        # Load hashes inline
        existing_hashes = {r[0]: r[1] for r in conn.execute(
            "SELECT paper_id, content_hash FROM paper_vectors"
        ).fetchall()}
        
        tasks = prepare_embed_tasks(store)
        to_embed, updated_ids = filter_tasks_by_hash(tasks, existing_hashes)
        
        if not to_embed:
            return 0
        
        results = self._store.embed_tasks(to_embed)
        
        # Direct save
        for r in results:
            conn.execute(
                "INSERT OR REPLACE INTO paper_vectors (paper_id, embedding, content_hash) VALUES (?, ?, ?)",
                (r.paper_id, np.array(r.vector, dtype=np.float32).tobytes(), r.content_hash),
            )
        conn.commit()
        
        if updated_ids:
            self._invalidate_cache()
        elif results:
            self._append_to_faiss([x.paper_id for x in results], [x.vector for x in results])
        
        return len(results)
    
    def search(self, query: str, top_k: int = 10, *, ...) -> list[dict]:
        """Semantic search."""
        conn = self._init_db()
        
        # Check vectors exist
        has_vectors = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_vectors'"
        ).fetchone()
        if not has_vectors:
            raise FileNotFoundError("Vector index not found. Run `linkora embed` first.")
        
        index, faiss_ids = self._get_faiss()
        if index is None:
            return []
        
        # Embed query
        q_vec = np.array([self._store.embed_text(query)], dtype="float32")
        q_vec /= np.linalg.norm(q_vec, axis=1, keepdims=True)
        
        # Search
        fetch_k = top_k * 5 if (year or journal or paper_type or paper_ids) else top_k
        fetch_k = min(fetch_k, index.ntotal)
        scores, indices = index.search(q_vec, fetch_k)
        
        # Load metadata and prepare results
        meta_map, dir_map = self._load_metadata()
        faiss_results = [(faiss_ids[idx], scores[0][i]) for i, idx in enumerate(indices[0]) if idx >= 0]
        results = prepare_search_results(faiss_results, meta_map, dir_map)
        
        # Filter
        filters = VectorFilterParams(year=year, journal=journal, paper_type=paper_type)
        filtered = filter_results(results, filters, paper_ids)
        
        return [ {...} for r in filtered[:top_k] ]
    
    def __enter__(self) -> "VectorIndex":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()
    
    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
        self._faiss_index = None
        self._faiss_ids = None
```

---

## 4. Summary: Before vs After

| Metric | Before | After |
|--------|--------|-------|
| Private methods | 15 | **7** |
| Exposed functions | 10+ | **0** |
| db_path in API | Yes | **No** |
| Lines of boilerplate | ~200 | **~100** |
| Type errors | Present | **Fixed** |

---

## 5. Implementation Order

```
1. Add FaissIndexConfig with Literal type
2. Implement streamlined VectorIndex (7 methods)
3. Clean up __init__.py exports
4. Refactor TopicTrainer to use VectorIndex
5. Remove TrainerContext
6. Update callers
```
