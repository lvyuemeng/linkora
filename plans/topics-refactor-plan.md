# topics.py Analysis & Refactoring Status

> Analysis of `scholaraio/topics.py` alignment with AGENT.md philosophy.

---

## 1. Current Module Relationships

### 1.1 Dependency Graph

```mermaid
graph TD
    topics[scholaraio/topics.py] --> log[scholaraio/log.py]
    topics --> index[scholaraio/index]
    topics --> papers[scholaraio/papers.py]
    topics --> bertopic[bertopic (external)]
    topics --> numpy[numpy (external)]
    
    index --> vector[scholaraio/index/vector.py]
    index --> log
    
    papers --> log
    
    style topics fill:#e1f5fe
    style index fill:#fff3e0
    style log fill:#e8f5e9
```

### 1.2 Direct Module Imports

| Module | topics.py | extract.py | vector.py | config.py |
|--------|-----------|------------|-----------|-----------|
| `scholaraio.log` | ✓ `get_logger` | ✓ | ✓ | — |
| `scholaraio.index` | ✓ `_unpack`, `Embedder` | — | ✓ | — |
| `scholaraio.papers` | ✓ `PaperStore` | ✓ | — | — |
| `scholaraio.config` | — | ✓ | — | — |
| `scholaraio.extract` | — | — | — | — |

### 1.3 Data Flow Relationships

| From | To | Relationship |
|------|-----|--------------|
| `topics.py` | `vector.py` | Indirect: reads `paper_vectors` table (produced by vector.py embed pipeline) |
| `topics.py` | `config.py` | No direct import - uses hardcoded defaults |
| `topics.py` | `extract.py` | No dependency - separate pipeline |

---

## 2. Refactoring Status: ALREADY COMPLETE ✓

### 2.1 Logging Pattern (Previously Issue #1)

| Location | Old (Plan) | Current | Status |
|----------|-----------|---------|--------|
| Line 30 | `import logging` | Not present | ✓ Fixed |
| Line 39 | — | `from scholaraio.log import get_logger` | ✓ Correct |
| Line 44 | `_log = logging.getLogger(__name__)` | `_log = get_logger(__name__)` | ✓ Correct |

### 2.2 TYPE_CHECKING Guard (Previously Issue #2)

| Location | Old (Plan) | Current | Status |
|----------|-----------|---------|--------|
| Lines 35-41 | `if TYPE_CHECKING: import numpy, bertopic` | `import numpy as np` (line 36) | ✓ Fixed |
| — | — | `from bertopic import BERTopic` (line 37) | ✓ Fixed |
| Lines 41-42 | — | `if TYPE_CHECKING: from scholaraio.index import Embedder` | ✓ Correct |

The use of `TYPE_CHECKING` for `Embedder` is **intentional and correct** because:
- `Embedder` is a Protocol (lines 97-106 in vector.py)
- Protocols are only needed at type-check time
- Runtime only needs concrete `QwenEmbedder`

---

## 3. Remaining Issues Found

### 3.1 Runtime Import Inside Function (Line 441)

```python
def _load_input_data(self, ...):
    """Load input data from database."""
    import numpy as np  # ← Redundant - already imported at module level
```

**Status**: Low priority - module-level import exists (line 36), function-level is redundant but harmless.

### 3.2 No config.py Integration

`topics.py` does not use `scholaraio/config.py` for settings like:
- `topics.min_topic_size`
- `topics.nr_topics`
- `topics.model_dir`

These are hardcoded in `TopicConfig` (line 89-100):
```python
@dataclass(frozen=True)
class TopicConfig:
    embedder: "Embedder"
    min_topic_size: int = 5      # Should use config.topics.min_topic_size
    nr_topics: int | str | None = "auto"  # Should use config.topics.nr_topics
```

**Status**: Enhancement opportunity - not a bug.

---

## 4. Verification

```bash
uv run ruff check scholaraio/topics.py
uv run ruff format scholaraio/topics.py
```

---

## 5. Summary

| Item | Status |
|------|--------|
| Logging pattern | ✓ Already correct |
| TYPE_CHECKING usage | ✓ Already correct |
| Module imports | ✓ Clean |
| Redundant numpy import in function | Low priority |
| config.py integration | Enhancement opportunity |

**Conclusion**: The refactoring described in this plan has already been completed. No code changes are required for AGENT.md compliance.
