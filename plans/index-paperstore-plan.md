# Index Module - PaperStore Integration Plan

## Goal
Pass `PaperStore` directly instead of `papers_dir: Path` to remove fragile directory state leak.

## Changes Required

### 1. vector.py - Change method signatures

**Before:**
```python
def prepare_embed_tasks(papers_dir: Path) -> list[EmbedTask]:
    store = PaperStore(papers_dir)
    ...

def rebuild(self, papers_dir: Path) -> int:
    tasks = prepare_embed_tasks(papers_dir)
    ...

def update(self, papers_dir: Path) -> int:
    tasks = prepare_embed_tasks(papers_dir)
    ...
```

**After:**
```python
def prepare_embed_tasks(store: PaperStore) -> list[EmbedTask]:
    for pdir in store.iter_papers():
        meta = store.read_meta(pdir)
        ...

def rebuild(self, store: PaperStore) -> int:
    tasks = prepare_embed_tasks(store)
    ...

def update(self, store: PaperStore) -> int:
    tasks = prepare_embed_tasks(store)
    ...
```

### 2. text.py - Same changes

**Before:**
```python
def rebuild(self, papers_dir: Path) -> int:
    store = PaperStore(papers_dir)
    ...

def update(self, papers_dir: Path) -> int:
    store = PaperStore(papers_dir)
    ...
```

**After:**
```python
def rebuild(self, store: PaperStore) -> int:
    for pdir in store.iter_papers():
        meta = store.read_meta(pdir)
        ...

def update(self, store: PaperStore) -> int:
    for pdir in store.iter_papers():
        meta = store.read_meta(pdir)
        ...
```

### 3. Simplify FAISS helper functions (optional)

Current functions:
- `load_faiss_index()` - loads from cache
- `save_faiss_index()` - saves to cache  
- `append_faiss()` - appends to existing
- `unpack_embeddings()` - extracts from DB rows
- `build_faiss_index()` - main builder

Can consolidate into fewer functions:
- Merge `load_faiss_index` + `save_faiss_index` into single `FaissCache` class
- Keep `unpack_embeddings` as-is (pure function)
- Keep `build_faiss_index` as main entry point

### 4. CLI commands.py - Update callers

**Before:**
```python
def cmd_index(args, cfg):
    with SearchIndex(cfg.index_db) as idx:
        idx.rebuild(cfg.papers_dir)
```

**After:**
```python
def cmd_index(args, cfg):
    from scholaraio.papers import PaperStore
    store = PaperStore(cfg.papers_dir)
    with SearchIndex(cfg.index_db) as idx:
        idx.rebuild(store)
```

## Implementation Order

1. Update `prepare_embed_tasks` in vector.py to accept PaperStore
2. Update `rebuild`/`update` in VectorIndex to accept PaperStore
3. Update `rebuild`/`update` in SearchIndex to accept PaperStore
4. Update CLI commands to create PaperStore
5. Run ruff check/format
6. Run mypy

## Files Affected

| File | Changes |
|------|---------|
| scholaraio/index/vector.py | Change method signatures |
| scholaraio/index/text.py | Change method signatures |
| scholaraio/cli/commands.py | Create PaperStore before calling |
