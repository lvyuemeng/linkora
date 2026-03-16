# CLI Commands Refactoring Plan

> Analysis of `scholaraio/cli/commands.py` with context injection design.
> Based on `plans/implementation-plan.md` philosophy and `docs/AGENT.md` standards.

---

## 1. Completed Items

### 1.1 Logging Pattern ✅

| Location | Before | After |
|----------|--------|-------|
| `commands.py` line 15 | `_log = logging.getLogger(__name__)` | `_log = get_logger(__name__)` |

### 1.2 Command Consolidation ✅

**Before (10 commands):**
```
search, search-author, vsearch, usearch, top-cited, index, embed, audit, setup, metrics
```

**After (6 commands):**
```
search --mode fts|author|vector|hybrid|cited
index --type fts|vector
audit
setup
metrics
```

### 1.3 Type Safety with Literal ✅

```python
# Type aliases for clarity
SearchMode = Literal["fts", "author", "vector", "hybrid", "cited"]
IndexType = Literal["fts", "vector"]
```

### 1.4 Context Injection ✅

Created [`scholaraio/cli/context.py`](scholaraio/cli/context.py) with lazy-initialized resources:
- `http_client()` - HTTP client
- `llm_runner()` - LLM runner
- `paper_store()` - Paper store
- `search_index()` - FTS index
- `vector_index()` - Vector index

### 1.5 Fixed Pre-existing Bugs ✅

- Fixed `cfg.search.top_k` → `cfg.index.top_k`
- Fixed `cfg.embed.top_k` → `cfg.index.embed_top_k`
- Fixed broken `usearch` (was calling FTS instead of hybrid)

---

## 2. Implementation Details

### 2.1 Unified Search Command

```python
def cmd_search(args: argparse.Namespace, cfg) -> None:
    """Unified search with --mode flag."""
    mode: SearchMode = getattr(args, "mode", "fts")
    
    if mode == "fts":
        _search_fts(...)
    elif mode == "author":
        _search_author(...)
    elif mode == "vector":
        _search_vector(...)
    elif mode == "hybrid":
        _search_hybrid(...)
    elif mode == "cited":
        _search_cited(...)
```

### 2.2 Unified Index Command

```python
def cmd_index(args: argparse.Namespace, cfg) -> None:
    """Unified index with --type flag."""
    index_type: IndexType = getattr(args, "type", "fts")
    
    if index_type == "fts":
        # Build FTS index
    elif index_type == "vector":
        # Build vector index
```

### 2.3 AppContext Design

```python
@dataclass
class AppContext:
    """Lazy-initialized context for CLI commands."""
    config: Config
    
    def http_client(self) -> HTTPClient:
        if self._http_client is None:
            from scholaraio.http import RequestsClient
            self._http_client = RequestsClient()
        return self._http_client
    
    # ... other lazy resources
```

---

## 3. Files Changed

| File | Status |
|------|--------|
| `scholaraio/cli/commands.py` | ✅ Refactored |
| `scholaraio/cli/context.py` | ✅ Created |

---

## 4. CLI Usage

### Search
```bash
# Full-text search (default)
scholaraio search "turbulence"

# Search by author
scholaraio search "John Smith" --mode author

# Vector search
scholaraio search "machine learning" --mode vector

# Hybrid search
scholaraio search "deep learning" --mode hybrid

# Top cited
scholaraio search --mode cited
```

### Index
```bash
# Build FTS index (default)
scholaraio index

# Build vector index
scholaraio index --type vector

# Rebuild index
scholaraio index --rebuild
scholaraio index --type vector --rebuild
```

---

## 5. Checklist

- [x] Fix logging pattern
- [x] Create AppContext
- [x] Use Literal type for SearchMode
- [x] Use Literal type for IndexType
- [x] Remove legacy commands (search-author, vsearch, usearch, top-cited, embed)
- [x] Consolidate search commands with --mode
- [x] Consolidate index commands with --type
- [x] Fix pre-existing bugs (cfg.search, cfg.embed)
- [x] Test CLI works
- [x] Run ruff check
- [x] Run ruff format