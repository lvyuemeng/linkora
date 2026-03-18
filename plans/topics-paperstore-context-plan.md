# TopicTrainer - PaperStore Context Plan (No Backward Compatibility)

> Refactor `TopicTrainer` in `linkora/topics.py` to use unified PaperStore context.
> NO backward compatibility - clean break per AGENT.md philosophy.
> Based on `implementation-plan.md`: "If an existing API is broken/incompatible, leave it alone"

---

## 0. Executive Summary

**Problem**: `TopicTrainer` has inconsistent path injection:
- `db_path: Path` - fragile path exposure
- `papers_dir: Path` - legacy, duplicates PaperStore
- `store: PaperStore` - good, but not the only option

**Solution**: Single entry point via `TrainerContext` - NO backward compatibility.

---

## 1. Current State (To Be Replaced)

### Current Signature (topics.py:379-386)

```python
def __init__(
    self,
    config: TopicConfig,
    db_path: Path | None = None,
    papers_dir: Path | None = None,
    papers_map: dict[str, dict] | None = None,
    store: "PaperStore | None" = None,
) -> None:
```

**Issues:**
- Multiple ways to provide the same data
- Path exposure (db_path, papers_dir) - fragile
- Creates PaperStore internally from papers_dir (line 405)

---

## 2. Target Design (Clean Break)

### 2.1 TrainerContext

```python
@dataclass(frozen=True)
class TrainerContext:
    """Unified context for topic training - ONLY entry point.
    
    Args:
        store: PaperStore instance for paper operations.
        db_path: Database path. If None, derived from store.papers_dir.parent / "index.db"
    """
    store: PaperStore
    db_path: Path | None = None
```

### 2.2 New TopicTrainer Signature

```python
def __init__(
    self,
    config: TopicConfig,
    context: TrainerContext,
    papers_map: dict[str, dict] | None = None,
) -> None:
```

**SIMPLE - only context + optional papers_map for explore mode**

---

## 3. Implementation

### Step 1: Add TrainerContext to topics.py

```python
# Add after imports, before TopicTrainer class

@dataclass(frozen=True)
class TrainerContext:
    """Unified context for topic training - ONLY entry point.
    
    No backward compatibility - use this or nothing.
    """
    store: PaperStore
    db_path: Path | None = None
    
    @property
    def resolved_db_path(self) -> Path:
        """Lazy resolve db_path from store."""
        if self.db_path is not None:
            return self.db_path
        return self.store.papers_dir.parent / "index.db"
```

### Step 2: Refactor TopicTrainer.__init__

```python
def __init__(
    self,
    config: TopicConfig,
    context: TrainerContext,
    papers_map: dict[str, dict] | None = None,
) -> None:
    """Initialize trainer - ONLY accepts TrainerContext.
    
    Args:
        config: TopicConfig with embedder and parameters.
        context: TrainerContext with store and optional db_path.
        papers_map: paper_id -> metadata dict (explore mode, overrides store).
    """
    self._config = config
    self._context = context
    self._input_data = self._load_input_data(papers_map)
```

### Step 3: Update _load_input_data

```python
def _load_input_data(
    self,
    papers_map: dict[str, dict] | None = None,
) -> TopicInputData:
    """Load input data from context."""
    db_path = self._context.resolved_db_path
    rows = self._fetch_vectors(db_path)
    
    if papers_map is not None:
        return self._load_from_papers_map(rows, papers_map)
    return self._load_from_papers_dir(rows)
```

### Step 4: Update _load_from_papers_dir

```python
def _load_from_papers_dir(
    self,
    rows: list[tuple[str, bytes]],
) -> TopicInputData:
    """Load data from papers directory using context."""
    store = self._context.store
    db_path = self._context.resolved_db_path
    
    # ... rest uses store and db_path from context
```

### Step 5: Add class-level _fetch_vectors (or keep as method)

Keep existing `_fetch_vectors` method but have it use context:

```python
def _fetch_vectors(self, db_path: Path) -> list[tuple[str, bytes]]:
    """Fetch vectors from database."""
    # ... existing implementation
```

---

## 4. Migration (No Backward Compatibility)

### Before (REMOVED):
```python
# OLD API - NO LONGER WORKS
trainer = TopicTrainer(config, db_path=db_path)
trainer = TopicTrainer(config, papers_dir=papers_dir)
trainer = TopicTrainer(config, store=store, db_path=db_path)
```

### After (ONLY WAY):
```python
# NEW API - ONLY WAY
context = TrainerContext(store=store)
trainer = TopicTrainer(config, context=context)

# Or with explicit db_path
context = TrainerContext(store=store, db_path=db_path)
trainer = TopicTrainer(config, context=context)

# Explore mode (papers_map overrides store)
context = TrainerContext(store=store)
trainer = TopicTrainer(config, context=context, papers_map=papers_map)
```

---

## 5. Files Affected

| File | Changes |
|------|---------|
| `linkora/topics.py` | Add TrainerContext, refactor TopicTrainer.__init__ |
| `linkora/mcp.py` | Update topic build to use TrainerContext |
| `linkora/cli/commands.py` | Update if topics command exists |

---

## 6. Verification

```bash
# Type check
uv run ty check linkora/topics.py

# Format
uv run ruff format linkora/topics.py
uv run ruff check linkora/topics.py
```

---

## 7. Why No Backward Compatibility?

Per `implementation-plan.md` philosophy:
> "If an existing API is broken/incompatible, leave it alone with `# BROKEN: <reason>` comment, focus on new design rather than backward compatibility"

And AGENT.md:
> **No repetition**: Extract common patterns to shared utilities

The old API had multiple entry points causing confusion:
- `db_path` + `store`
- `papers_dir` (creates store internally)
- `papers_map` (explore mode)

The new API has ONE entry point:
- `TrainerContext` (store + optional db_path)

This is cleaner and follows the "No repetition" principle.

---

## 8. Related Plans

- `index-paperstore-plan.md` - VectorIndex/SearchIndex use PaperStore
- `topics-type-fix-plan.md` - Identified this as "Optional Enhancement" - now implemented
