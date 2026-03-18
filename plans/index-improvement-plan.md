# index/ Module Improvement Plan

> Refactor `linkora/index/text.py` (FTS5) and `linkora/index/vector.py` (FAISS) to align with AGENT.md philosophy.
> Based on `docs/AGENT.md` coding standards.

---

## 0. Executive Summary

Reduce lines in clean logic by removing legacy/unused code and fixing broken CLI.

---

## 1. Issues Found

### 1.1 Legacy Unused Functions (vector.py) - REMOVE

| Function | Lines | Status |
|----------|-------|--------|
| `_load_model()` | 899-902 | UNUSED - remove |
| `_embed_text()` | 905-908 | UNUSED - remove |
| `_embed_batch()` | 911-914 | UNUSED - remove |
| `_build_faiss_index()` | 917-919 | UNUSED - remove |
| `_build_faiss_from_db()` | 922-930 | UNUSED - remove |
| `_vsearch_faiss()` | 933-954 | UNUSED - remove |
| `build_faiss_index_from_paths()` | 962-1021 | UNUSED - remove |

### 1.2 Public API (KEEP)

These are used by MCP server and CLI - KEEP:
- `build_vectors()` - used by MCP
- `vsearch()` - used by MCP

### 1.3 Broken CLI Command (FIX)

| File | Issue |
|------|-------|
| cli/commands.py:81 | Calls `idx.unified_search()` which doesn't exist |
| Fix | Change to use `idx.search()` |

### 1.4 Logging Pattern (FIX)

| File | Line | Fix |
|------|------|-----|
| vector.py | 31 | Change to use `get_logger` singleton |

### 1.5 TYPE_CHECKING (No Action)

| File | Status |
|------|--------|
| text.py | ✅ Already correct - Path imported directly |
| vector.py | ✅ Correct - TYPE_CHECKING for Protocol |

---

## 2. Implementation Steps

### Step 1: Remove Legacy Functions from vector.py

Delete lines ~823-1021 (Legacy API section), keep only:
- `build_vectors()` 
- `vsearch()`

### Step 2: Fix Logging in vector.py

```python
# Remove: import logging
# Add:
from linkora.log import get_logger
_log = get_logger(__name__)
```

### Step 3: Fix Broken CLI Command

In `cli/commands.py` line 81, change:
```python
# FROM:
results = idx.unified_search(...)

# TO:
results = idx.search(...)
```

### Step 4: Update __init__.py

Remove exports for deleted functions (if any were exported).

### Step 5: Verify

```bash
uv run ruff check linkora/index/
uv run ruff format linkora/index/
uv run mypy linkora/index/
```

---

## 3. Expected Reduction

| File | Before | After | Reduction |
|------|--------|-------|-----------|
| vector.py | 1021 | ~680 | ~340 lines (33%) |

---

## 4. Files Affected

| File | Action |
|------|--------|
| linkora/index/vector.py | Remove legacy functions, fix logging |
| linkora/cli/commands.py | Fix broken unified_search call |
| linkora/index/__init__.py | Update exports if needed |
