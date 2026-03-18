# Type Check Fix Plan - Comprehensive

> Fix all type check errors from `ty check` output

---

## Error Summary

| # | Category | File | Lines | Issue |
|---|----------|------|-------|-------|
| 1 | FAISS Type Stubs | linkora/index/vector.py | 594, 625 | `add()` missing `x` parameter |
| 2 | FAISS Type Stubs | linkora/index/vector.py | 800 | `search()` missing `k`, `distances`, `labels` |
| 3 | Unresolved Import | linkora/mcp.py | 15 | `mcp.server.fastmcp` |
| 4 | Unresolved Import | linkora/sources/endnote.py | 13 | `endnote_utils.core` |
| 5 | Unresolved Import | linkora/sources/zotero.py | 278 | `pyzotero` |
| 6 | Invalid Arg Type | linkora/topics.py | 678, 696 | `representation_model` |

---

## 1. FAISS Type Stubs Fix

### Problem Analysis
The FAISS Python bindings have type stubs that don't match the high-level Python API:

**Type Stubs Expect (C-style):**
- `Index.add(n: int, x: np.ndarray) -> None`
- `Index.search(n: int, x: np.ndarray, k: int, distances, labels, params=None)`

**Actual Python API:**
- `index.add(vectors: np.ndarray) -> None`
- `index.search(query: np.ndarray, k: int) -> tuple[distances, indices]`

### Solution: Use Type Ignore Comments
Since this is a type stub mismatch (not a code bug), use explicit type ignores:

```python
# Line 594 - add vectors to index
self._faiss_index.add(vectors)  # type: ignore[missing-argument]

# Line 625 - append to index  
index.add(arr)  # type: ignore[missing-argument]

# Line 800 - search index
scores, indices = index.search(q_vec, fetch_k)  # type: ignore[missing-argument]
```

---

## 2. Unresolved Imports Fix

### Problem Analysis
These are optional dependencies. The type checker can't find them because:
1. They may not be installed in the type check environment
2. They're conditionally used

### Solution Strategy

#### Option A: Create Stub Modules (Recommended)
Create stub files in a `stubs/` directory for type checking:

```
stubs/
├── mcp/
│   └── server/
│       └── fastmcp.pyi
├── endnote_utils/
│   └── core.pyi
└── pyzotero/
    └── zotero.pyi
```

#### Option B: Conditional Import Handling
Use `TYPE_CHECKING` blocks and cast to `Any`:

```python
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# Runtime - handle import error
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = Any  # type: ignore[misc,assignment]
```

#### Option C: Ignore at Import Site (Simplest)
Add ignore comments at the specific import lines:

```python
from mcp.server.fastmcp import FastMCP  # type: ignore[unresolved-import]
from endnote_utils.core import (  # type: ignore[unresolved-import]
    iter_records_ris,
    iter_records_xml,
    process_record_xml,
)
from pyzotero import zotero as pyzotero  # type: ignore[unresolved-import]
```

---

## 3. BERTopic representation_model Fix

### Already Documented in Existing Plan
See `plans/type-check-fix-plan.md` lines 190-221.

### Quick Summary
The issue is that `representation_model` expects `BaseRepresentation` but receives `list[KeyBERTInspired | MaximalMarginalRelevance]`.

**Fix:** Use `# type: ignore[invalid-argument-type]` on the BERTopic calls:

```python
topic_model = BERTopic(
    # ... other params
    representation_model=representation_model,  # type: ignore[invalid-argument-type]
)

topic_model.update_topics(
    # ... params
    representation_model=representation_model,  # type: ignore[invalid-argument-type]
)
```

---

## Implementation Steps

### Step 1: Fix FAISS Type Stubs (vector.py)
1. Add `# type: ignore[missing-argument]` to line 594
2. Add `# type: ignore[missing-argument]` to line 625
3. Add `# type: ignore[missing-argument]` to line 800

### Step 2: Fix Unresolved Imports
Choose one strategy (Option C is simplest):

**For mcp.py (line 15):**
```python
from mcp.server.fastmcp import FastMCP  # type: ignore[unresolved-import]
```

**For endnote.py (lines 13-17):**
```python
from endnote_utils.core import (  # type: ignore[unresolved-import]
    iter_records_ris,
    iter_records_xml,
    process_record_xml,
)
```

**For zotero.py (line 278):**
```python
from pyzotero import zotero as pyzotero  # type: ignore[unresolved-import]
```

### Step 3: Fix BERTopic representation_model (topics.py)
Add type ignores to lines 678 and 696 as shown above.

### Step 4: Verify
```bash
uv run ty check
```

Expected result: 0 errors

---

## Files to Modify

| File | Changes |
|------|---------|
| linkora/index/vector.py | Add 3 type ignore comments |
| linkora/mcp.py | Add 1 type ignore comment |
| linkora/sources/endnote.py | Add 1 type ignore comment |
| linkora/sources/zotero.py | Add 1 type ignore comment |
| linkora/topics.py | Add 2 type ignore comments |

---

## Mermaid: Fix Workflow

```mermaid
graph TD
    A[Start: Type Check Errors] --> B[FAISS Type Stubs]
    B --> C[Add type ignore to add() calls]
    C --> D[Add type ignore to search() call]
    D --> E[Unresolved Imports]
    
    E --> F[mcp.py: Add type ignore]
    F --> G[endnote.py: Add type ignore]
    G --> H[zotero.py: Add type ignore]
    H --> I[BERTopic representation_model]
    
    I --> J[topics.py: Add type ignore]
    J --> K[Run ty check]
    K --> L{0 Errors?}
    L -->|Yes| M[Done]
    L -->|No| N[Debug Remaining]
```
