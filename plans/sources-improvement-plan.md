# sources/ Module Improvement Plan

---

## Concrete Bloating Issues

### zotero.py (624 lines total)

| Problem | Location | Impact |
|---------|----------|--------|
| Legacy BROKEN functions | Lines 342-624 (~285 lines) | Duplicates class functionality |
| Deep nesting in `_fetch_local` | Lines 207-293 | 7+ levels of indentation |
| Duplicate code | `fetch_zotero_api` vs `_fetch_api` | Maintenance burden |
| Inconsistent return types | Legacy: `PaperMetadata`, Class: `dict` | Confusing API |

**Deep nesting example:**
```python
def _fetch_local(...):
    conn = sqlite3.connect(...)
    try:
        if collection_key:           # level 2
            ...
        if item_types:              # level 2
            ...
        for row in items_rows:      # level 3
            if item_id_filter:      # level 4
                ...
            for r in field_rows:    # level 5
                for c in creators:   # level 6
```

### endnote.py (357 lines total)

| Problem | Location | Impact |
|---------|----------|--------|
| Legacy BROKEN functions | Lines 252-357 (~105 lines) | Duplicates class |
| Redundant conversion | `_record_to_meta` → `_record_to_dict` | Unnecessary layer |
| Duplicate parsing logic | `parse_endnote()` vs class | Code duplication |

---

## Implementation Priority

| Priority | Task | Status |
|----------|------|--------|
| P0 | Update openalex.py to use HTTPClient | ✅ Done |
| P1 | Add tenacity retry to openalex.py | ✅ Done (via RequestsClient) |
| P2 | Add http_client to OpenAlexSource and ZoteroSource | ✅ Done |
| P3 | Refactor zotero.py to reduce nesting | ⬜ Pending |
| P4 | Remove legacy BROKEN functions | ⬜ Pending |
| P5 | LocalSource efficiency improvements | ✅ Done |

---

## Completed Changes

### openalex.py
- Uses HTTPClient Protocol (injected, required)
- Uses tenacity retry via RequestsClient
- Removed raw `requests` import
- No internal client initialization

### local.py
- Removed deprecated `iter_paper_dirs()` - uses direct `iterdir()`
- Removed `sorted()` - iteration doesn't need sorted output
- Uses exception handling instead of `exists()` + read
- Uses `json.loads()` directly

### zotero.py
- Added `http_client` field (required for API mode)
- Removed internal lazy initialization

---

## LocalSource Efficiency Improvements (Done)

### Changes Made

1. **Remove sorted()** - iteration doesn't need sorted output
2. **Single filesystem operation** - use exception handling
3. **Direct json parsing** - no helper function needed
