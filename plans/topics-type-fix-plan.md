# topics.py Type Fix & Refactor Plan

> Based on type check results and code quality analysis.
> Focus on fixing root causes, not `type: ignore`.
> 
> **Status: ALL ISSUES FIXED (2026-03-17)**

---

## 0. Current Code Analysis Summary

### Already Fixed (Verified in Current Code):
| Issue | Location | Status |
|-------|----------|--------|
| UMAP sparse matrix | Line 269 | ✅ Already uses `np.asarray()` |
| dir_name None check | Lines 538-541 | ✅ Already has proper None handling |
| Never iterable | Lines 719-734 | ✅ Already uses simplified counting |

### Still Needs Fixing:
| Issue | Location | Status |
|-------|----------|--------|
| (All fixed) | - | ✅ All issues resolved |

---

## 1. Type Errors (Issues to Fix)

### Issue #1: Line 269 - UMAP returns coo_matrix, not ndarray ✅ ALREADY FIXED

**Current code (line 269):**
```python
# UMAP can return sparse matrix, convert to dense array for visualize_documents
reduced = np.asarray(
    UMAP(
        n_components=2, min_dist=0.0, metric="cosine", random_state=42
    ).fit_transform(embeddings)
)
```

**Status:** ✅ Already fixed - uses `np.asarray()` to convert to dense array.

---

### Issue #2: Lines 538-541 - Path / None operator ✅ ALREADY FIXED

**Current code:**
```python
# dir_name can be None if database column is NULL
dir_name = id_to_dir.get(paper_id)
if dir_name is None:
    dir_name = paper_id
paper_d = papers_dir / dir_name
```

**Status:** ✅ Already fixed - has proper None check.

---

### Issue #3: Lines 719-734 - "Never" is not iterable ✅ ALREADY FIXED

**Current code:**
```python
n_outliers_before = sum(1 for t in topics if t == -1)
n_real_topics = len(set(topics) - {-1})
if n_outliers_before > 0 and n_real_topics > 0:
    topics = topic_model.reduce_outliers(
        docs, topics, strategy="embeddings", embeddings=embeddings
    )
    topic_model.update_topics(
        docs,
        topics=topics,
        vectorizer_model=vectorizer_model,
        representation_model=representation_model,  # type: ignore[arg-type]
    )
    n_outliers_after = sum(1 for t in topics if t == -1)
    _log.info(
        "Outlier reduction: %d -> %d", n_outliers_before, n_outliers_after
    )

n_topics = len(set(topics)) - (1 if -1 in topics else 0)
n_outliers = sum(1 for t in topics if t == -1)
```

**Status:** ✅ Already fixed - uses simplified counting with generator expression.

---

### Issue #4: Line 745 - Awkward type guard ❌ NEEDS FIX

**Location:** `fit()` method, line 745

**Current code:**
```python
topics=list(topics) if not isinstance(topics, list) else topics,
```

**Problem:** The conditional expression confuses type checker.

**Fix:**
```python
# Ensure topics is a list for immutability
topic_list = list(topics)
```

Then update line 745 to use `topic_list`:
```python
return TopicModelOutput(
    bertopic_model=topic_model,
    paper_ids=input_data.paper_ids,
    metas=input_data.metas,
    topics=topic_list,
    embeddings=np.array(embeddings, dtype="float32"),
    docs=cast(list[str | None] | None, docs),
)
```

---

## 2. Wheel Recreation (Redundant Code)

### Issue #5: get_topic_overview() - redundant get_topic() calls ❌ NEEDS FIX

**Location:** `get_topic_overview()` method, lines 160-167

**Current code:**
```python
topic_words = bertopic.get_topic(tid)
# get_topic returns True if topic not found (not None!)
# Returns Mapping[str, Tuple[str, float]] - need to convert to list for slicing
if topic_words is True or not topic_words:
    keywords = []
else:
    topic_list = list(topic_words.values())
    keywords = [w for w, _ in topic_list[:10]]
```

**Problem:** Calls `bertopic.get_topic(tid)` to get keywords when `get_topic_info()` already has `Representation` column with keywords.

**Fix (use BERTopic native):**
```python
# get_topic_info() already has Representation column!
rep = row.get("Representation", [])
if isinstance(rep, list):
    keywords = [w for w in rep[:10] if isinstance(w, str)]
else:
    keywords = []
```

---

### Issue #6: find_related_topics() - redundant get_topic() calls ❌ NEEDS FIX

**Location:** `find_related_topics()` method, lines 226-233

**Current code:**
```python
topic_words = bertopic.get_topic(tid)
# get_topic returns True if topic not found
# Returns Mapping[str, Tuple[str, float]] - need to convert to list for slicing
if topic_words is True or not topic_words:
    keywords = []
else:
    topic_list = list(topic_words.values())
    keywords = [w for w, _ in topic_list[:5]]
```

**Problem:** Same issue - calls `bertopic.get_topic(tid)` when info already available via `get_topic_info()`.

**Fix:** Use `get_topic_info()` representation column - need to pre-fetch topic info once and reuse.

```python
# Pre-fetch topic info once at the beginning of the method
info = bertopic.get_topic_info()
tid_to_rep = {}
for _, row in info.iterrows():
    tid = row["Topic"]
    rep = row.get("Representation", [])
    if isinstance(rep, list):
        tid_to_rep[tid] = rep

# Then in the loop:
rep = tid_to_rep.get(tid, [])
keywords = [w for w in rep[:5] if isinstance(w, str)]
```

---

## 3. Dead Code ❌ NEEDS FIX

### Issue #7: filter_topics_by_keyword() never used

**Location:** Line 414-417

**Current code:**
```python
def filter_topics_by_keyword(topics: list[TopicInfo], keyword: str) -> list[TopicInfo]:
    """Filter topics by keyword in keywords."""
    kw_lower = keyword.lower()
    return [t for t in topics if any(kw_lower in k.lower() for k in t.keywords)]
```

**Problem:** Function defined but never called anywhere in codebase.

**Fix:** Remove the function.

---

## 4. Context Injection Pattern (Optional Enhancement)

### Current State (Problem)

The `TopicTrainer.__init__()` takes paths directly:
```python
def __init__(
    self,
    config: TopicConfig,
    db_path: Path,           # PATH EXPOSED
    papers_dir: Path | None = None,  # PATH EXPOSED
    papers_map: dict[str, dict] | None = None,
) -> None:
```

Then internally creates PaperStore:
```python
store = PaperStore(papers_dir)  # Created inside
```

### Target State (Context Injection - Optional)

Like `loader.py` pattern - pass PaperStore directly:

```python
def __init__(
    self,
    config: TopicConfig,
    store: PaperStore | None = None,  # Context injection
    db_path: Path | None = None,      # Keep for fallback
    papers_map: dict[str, dict] | None = None,
) -> None:
    self._store = store
    ...
```

### Recommendation

Per implementation-plan.md philosophy:
> "If an existing API is broken/incompatible, leave it alone with `# BROKEN: <reason>` comment"

This is a LOW PRIORITY enhancement - the current API works. Skip for now unless specifically requested.

---

## 5. Implementation Order

```
1. Fix Issue #4: Simplify topics list conversion (line 745) ✅ DONE
2. Fix Issue #5: Use get_topic_info() Representation column (lines 160-167) ✅ DONE
3. Fix Issue #6: Use get_topic_info() in find_related_topics (lines 226-233) ✅ DONE
4. Fix Issue #7: Remove filter_topics_by_keyword() dead code ✅ DONE
5. Run ruff format ✅ DONE
6. Run ty check to verify ✅ DONE (0 errors)
```

**All items completed successfully!**

---

## 6. CLI Usage Reference

From `cli/commands.py`, topics.py is used via MCP in `mcp.py`:
- `topic action=overview` - calls `get_topic_overview()`
- `topic action=papers` - calls `get_topic_papers()`
- `topic action=build` - calls `TopicTrainer().fit()`

---

## 7. Verification

```bash
# Run type check
uv run ty check

# Expected: 0 errors, 0 warnings
```

---

## Summary Table

| Issue | Line | Type | Status |
|-------|------|------|--------|
| UMAP sparse matrix | 269 | Type Error | ✅ Already Fixed |
| dir_name None | 538-541 | Type Error | ✅ Already Fixed |
| Never iterable | 719-734 | Type Error | ✅ Already Fixed |
| Awkward guard | 688 | Type Error | ✅ Fixed (simplified to `list(topics)`) |
| get_topic() wheel | 160-167 | Wheel Recreation | ✅ Fixed (uses Representation column) |
| find_related wheel | 206-233 | Wheel Recreation | ✅ Fixed (pre-fetches topic info) |
| Dead code | 414-417 | Unused Code | ✅ Fixed (function removed) |

---

## 6. Function Complexity Reduction Analysis

### 6.1 _load_input_data() - Lines 451-577 (126 lines) ✅ DONE

**Implementation:**
- Split into smaller functions:
  - `_fetch_vectors(db_path)` - fetches vectors from database
  - `_load_from_papers_map(rows, papers_map)` - explore mode
  - `_load_from_papers_dir(rows, db_path)` - library mode using injected store
  - `_load_input_data(...)` - delegates to mode-specific loaders
- **Context injection:** Added `store: PaperStore` parameter to `TopicTrainer.__init__()`

**Status:** ✅ COMPLETED - 126 lines split into focused functions + context injection

---

### 6.2 get_topic_overview() - Lines 149-184 (35 lines) ✅ ALREADY OPTIMIZED

**Current Implementation:**
- Uses `row.get("Representation", [])` instead of `bertopic.get_topic(tid)` - eliminates redundant API call ✅
- Pre-sorts papers once outside the loop ✅

**Status:** Already optimized - no further action needed

---

### 6.3 find_related_topics() - Lines 192-242 (50 lines) ✅ ALREADY OPTIMIZED

**Current Implementation:**
- Pre-fetches topic info once at the beginning (`info = bertopic.get_topic_info()`) ✅
- Uses `tid_to_rep` dict to cache Representation column ✅
- Uses Representation column instead of get_topic() ✅

**Status:** Already optimized - no further action needed

---

### 6.4 visualize_topics_2d() - Lines 254-312 (58 lines) ⏭️ SKIPPED

**Current Implementation:**
- Uses BERTopic native `visualize_topics()` method
- Minimal code, delegates to BERTopic

**Status:** Skipped - current implementation is clean, no extraction needed

---

### 6.5 Summary of Function Reductions

| Function | Current Lines | Estimated After | Reduction | Key Improvement |
|----------|---------------|-----------------|------------|------------------|
| _load_input_data | 126 | ~80 | 37% | Split + Context Injection ✅ DONE |
| get_topic_overview | 35 | ~40 | -14% | Eliminates N API calls ✅ Already Optimized |
| find_related_topics | 50 | ~45 | 10% | Pre-fetches topic info ✅ Already Optimized |
| visualize_topics_2d | 58 | ~58 | 0% | Uses BERTopic native ⏭️ Skipped |
| **Total** | **269** | **~217** | **19%** | Plus O(n) → O(1) API calls |
