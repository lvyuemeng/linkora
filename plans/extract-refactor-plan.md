# extract.py Refactoring Plan

> Issues found in `linkora/extract.py` and planned fixes based on implementation-plan.md philosophy.

---

## 1. Issues Found

### 1.1 Broken Imports (Critical)

| Line | Import Statement | Problem |
|------|------------------|---------|
| 68 | `from linkora.ingest.metadata import extract_metadata_from_markdown` | File `linkora/ingest/metadata.py` does NOT exist |
| 138 | Same as above | Same |
| 124-128 | `from linkora.ingest.metadata import (PaperMetadata, _extract_from_filename, _extract_lastname)` | - `PaperMetadata` is in `linkora.papers`<br>- `_extract_lastname` is in `linkora.papers`<br>- `_extract_from_filename` does NOT exist anywhere |

### 1.2 Missing Functions (Critical)

| Function | Referenced In | Problem |
|----------|---------------|---------|
| `extract_metadata_from_markdown` | Lines 68, 138 | Does NOT exist - file reference is broken |
| `_extract_from_filename` | Lines 154, 360 | Does NOT exist - needs to be implemented |

### 1.3 Code Style Violations

| Issue | Location | Fix |
|-------|----------|-----|
| Old logging style | Line 27: `_log = logging.getLogger(__name__)` | Use `from linkora.log import get_logger` |
| TYPE_CHECKING guard | Line 25 | Remove guard, import Path directly |
| Scattered imports | Lines 68, 124-128, 138, 292-296 | Move to module level |

---

## 2. Root Cause Analysis

The code in `extract.py` was written with references to a non-existent module `linkora/ingest/metadata.py`. This appears to be either:

1. A planned refactoring that was never completed
2. Code that was accidentally broken during a previous reorganization

The actual implementations exist in:
- `linkora.papers.PaperMetadata` ✅
- `linkora.papers._extract_lastname` ✅
- `linkora.papers._extract_from_filename` ❌ (MISSING - needs implementation)

---

## 3. Refactoring Plan

### 3.1 Step 1: Implement Missing Functions in papers.py

```python
# Add to linkora/papers.py

def _extract_from_filename(filepath: Path) -> "PaperMetadata":
    """Extract metadata from filename patterns.
    
    Handles patterns like:
        - "2024_Smith_DeepLearning.pdf"
        - "Deep Learning - Smith (2024).pdf"
        - "10.1234-example.pdf"
    
    Returns:
        PaperMetadata with fields extracted from filename.
    """
    # TODO: Implement based on common filename patterns
    meta = PaperMetadata()
    # ... implementation
    return meta
```

### 3.2 Step 2: Fix Imports in extract.py

Replace all broken imports:

```python
# OLD (broken):
from linkora.ingest.metadata import (
    PaperMetadata,
    _extract_from_filename,
    _extract_lastname,
)

# NEW (correct):
from linkora.papers import PaperMetadata
from linkora.papers import _extract_lastname, _extract_from_filename
```

### 3.3 Step 3: Implement extract_metadata_from_markdown

Either:
- Create `linkora/ingest/metadata.py` with this function, OR
- Move the function to `linkora/papers.py` and update imports

**Recommendation**: Create `linkora/ingest/metadata.py` as a thin wrapper that calls into papers.py, for backward compatibility if other modules reference it.

```python
# linkora/ingest/metadata.py (NEW FILE)
"""Metadata extraction utilities - backward compatibility wrapper."""

from pathlib import Path
from linkora.papers import PaperMetadata


def extract_metadata_from_markdown(filepath: Path) -> PaperMetadata:
    """Extract metadata from MinerU markdown output.
    
    Args:
        filepath: Path to .md file.
    
    Returns:
        PaperMetadata instance.
    """
    # TODO: Implement based on existing regex patterns
    # This is the core regex extraction logic
    pass
```

### 3.4 Step 4: Migrate to New Logging Style

```python
# OLD (line 27):
_log = logging.getLogger(__name__)

# NEW:
from linkora.log import get_logger
_log = get_logger(__name__)
```

### 3.5 Step 5: Remove TYPE_CHECKING Guard

```python
# OLD:
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pathlib import Path

# NEW:
from pathlib import Path  # Direct import
```

### 3.6 Step 6: Consolidate Imports to Module Level

Move all imports from inside methods to module level:

| Line | Import | Move To |
|------|---------|---------|
| 68 | `from linkora.ingest.metadata import extract_metadata_from_markdown` | Module level |
| 124-128 | `from linkora.ingest.metadata import (...)` | Module level |
| 138 | Same as line 68 | Module level |
| 168 | `from linkora.llm import LLMRunner, LLMRequest` | Module level |
| 292-296 | `from linkora.ingest.metadata import (...)` | Module level |

---

## 4. Implementation Order

```
1. Implement _extract_from_filename in papers.py
2. Create linkora/ingest/metadata.py with extract_metadata_from_markdown
3. Fix imports in extract.py (point to correct modules)
4. Migrate logging style to singleton pattern
5. Remove TYPE_CHECKING guard
6. Consolidate all imports to module level
7. Test that extract.py works end-to-end
```

---

## 5. Files Affected

| File | Action |
|------|--------|
| `linkora/papers.py` | Add `_extract_from_filename()` function |
| `linkora/ingest/metadata.py` | CREATE - backward compatibility wrapper |
| `linkora/extract.py` | Fix imports, logging, remove TYPE_CHECKING |

---

## 6. Configuration Reference

From `linkora/config.py`:
- `config.ingest.extractor` - Controls which extractor to use (regex/auto/robust/llm)
- Extractor mode is read in `get_extractor()` function (line 393-434)

---

## 7. Dependencies

- `linkora/log.py` - Logger singleton (NEW logging style)
- `linkora/config.py` - Configuration
- `linkora/papers.py` - PaperMetadata, helper functions
- `linkora/llm.py` - LLM client (used by LLMExtractor, RobustExtractor)
- `linkora/http.py` - HTTP client (RequestsClient)

---

## Summary

| Issue | Severity | Fix |
|-------|----------|-----|
| Missing `linkora/ingest/metadata.py` | Critical | Create file with `extract_metadata_from_markdown` |
| Missing `_extract_from_filename` | Critical | Implement in `papers.py` |
| Old logging style | Medium | Use singleton from `log.py` |
| TYPE_CHECKING guard | Low | Import Path directly |
| Scattered imports | Medium | Move to module level |

