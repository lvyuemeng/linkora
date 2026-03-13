# ScholarAIO Refactoring Roadmap

> Strategic overview and design principles for refactoring.

## Design Principles

1. **Pure English** - Code, comments, docstrings in English
2. **Interface-Based** - Abstract to interfaces, not implementations
3. **Type Safety** - Full type hints, TypedDict, Protocol
4. **Functional Design** - Pure functions, pipeline composition, dataclass-based state
5. **No Repetition** - Extract common patterns to shared utilities
6. **No Huge Arguments** - Use dataclasses/config objects
7. **Integrated Flow** - No isolated side-effect functions
8. **No Side-Effect Exposure** - Paths (db_path, papers_dir) should not be function parameters
9. **Config/Side-Effect Separation** - Separate configuration from resource building
10. **Pipe Flow** - All operations chained via data structures, no list returns
11. **Breaking API Policy** - If an existing API is broken/incompatible, leave it alone with `# BROKEN: <reason>` comment, focus on new design rather than backward compatibility
11. **Breaking API Handling** - If an API breaks/changes incompletely, leave it as-is with comment ` # BROKEN: <reason>`, do NOT attempt backward compatibility; focus on new design instead

---

## Code Style Guidelines

### Logging (from log.py)

**Old (ugly):**
```python
import logging
_log = logging.getLogger(__name__)
```

**New (use singleton):**
```python
from scholaraio.log import get_logger, ui

_log = get_logger(__name__)  # or just use get_logger() where needed

# For user-facing output:
ui("Processing %d files", count)
```

### Type Imports

**Old:**
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
```

**New (force import):**
```python
from pathlib import Path  # No TYPE_CHECKING guard needed
```

---

## Completed Modules

| Module | Status | Key Changes |
|--------|--------|-------------|
| log.py | ✅ | LoggerManager singleton, HasLogConfig Protocol |
| papers.py | ✅ | PaperStore, PaperMetadata, YearRange, Issue, PaperFilter |
| index.py | ✅ | SearchIndex class, SearchMode factory, FilterParams |
| vectors.py | ✅ | VectorIndex, Embedder Protocol, ModelStore |
| loader.py | ✅ | StrategyRegistry, PromptTemplate, PaperEnricher |
| topics.py | ✅ | TopicConfig, TopicTrainer, TopicModelOutput |
| cli/ | ✅ | 5 commands (~200 lines total) |
| llm.py | ✅ | LLM client abstraction |
| extract.py | ✅ | Extraction utilities |

---

## CLI Design

### Design Rule: Merge Similar Commands

**After** (5 unified commands):
```
search  --mode fts|author|vector|hybrid|cited
index   --type fts|vector
audit, setup, metrics
```

---

## Data Structure Patterns

Key patterns to reuse across modules:

```python
# Immutable dataclass for state
@dataclass(frozen=True)
class PaperMetadata:
    id: str
    title: str

# Filter with matching method
@dataclass(frozen=True)
class PaperFilter:
    year: str | None = None
    def matches(self, meta: dict) -> bool: ...
```

---

## PDF Parser Module Refactor (mineru.py)

### Current Issues

| Issue | Description |
|-------|-------------|
| Hardcoded URLs | `DEFAULT_API_URL`, `CLOUD_API_URL` as constants |
| Hardcoded endpoints | `PARSE_ENDPOINT = "/file_parse"` |
| Duplicated code | `convert_pdf` and `convert_pdf_cloud` share ~60% logic |
| No Protocol | Hardcoded to MinerU API |
| State leakage | `ConvertResult` mutated during process |
| Factory pattern | Separate Factory class instead of __init__ |
| Cloud/Local coupling | `_api_key` and `_is_cloud` fields in PDFParser - should inject client |

### Refactor Design: Client Injection Pattern

**Key principle**: Separate HTTP client as injectable Protocol, eliminate cloud/local branching inside PDFParser.

**1. Client Protocol (like vectors.py Embedder Protocol)**

```python
from typing import Protocol

class PDFClient(Protocol):
    """Protocol for PDF parsing clients (local MinerU or cloud API)."""
    
    def check_health(self) -> bool: ...
    
    def call(self, pdf_path: Path, opts: ParseOptions) -> dict: ...
    
    @property
    def name(self) -> str: ...
```

**2. Client Implementations**

```python
@dataclass(frozen=True)
class LocalClient:
    """Local MinerU API client."""
    base_url: str = "http://localhost:8000"
    timeout: int = 600
    
    @property
    def name(self) -> str:
        return "local"
    
    def check_health(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/docs", timeout=5)
            return resp.status_code == 200
        except requests.ConnectionError:
            return False
    
    def call(self, pdf_path: Path, opts: ParseOptions) -> dict:
        # Local API call logic
        ...


@dataclass(frozen=True)
class CloudClient:
    """MinerU cloud API client."""
    api_key: str
    base_url: str = "https://mineru.net/api/v4"
    timeout: int = 600
    
    @property
    def name(self) -> str:
        return "cloud"
    
    def check_health(self) -> bool:
        # Cloud health check (ping endpoint)
        ...
    
    def call(self, pdf_path: Path, opts: ParseOptions) -> dict:
        # Cloud API call logic (upload -> poll -> download)
        ...
```

**3. PDFParser with Injected Client**

```python
class PDFParser:
    """PDF Parser with injectable client - no cloud/local branching."""
    
    def __init__(self, client: PDFClient):
        self._client = client
    
    # Pipeline methods unchanged - client handles API differences
    def call_api(self, pdf_input: PDFInput) -> APIResponse | ParseError:
        t0 = time.time()
        try:
            response = self._client.call(pdf_input.pdf_path, pdf_input.opts)
            return APIResponse(
                pdf_path=pdf_input.pdf_path,
                response=response,
                elapsed=time.time() - t0,
            )
        except Exception as e:
            return ParseError(
                pdf_path=pdf_input.pdf_path,
                stage="api",
                error=str(e),
            )
```

### Benefits

| Before | After |
|--------|-------|
| `PDFParser._is_cloud` branching | Single code path via client |
| Duplicated upload/poll logic | Each client handles its own protocol |
| Hard to test | Clients can be mocked via Protocol |
| Cloud/Local tightly coupled | Clients are independent implementations |

### Separated States (unchanged)

- `PDFInput`: pdf_path + opts
- `APIResponse`: pdf_path + response + elapsed
- `ExtractedContent`: pdf_path + content + opts
- `ParseResult`: pdf_path + md_path + md_size + elapsed
- `ParseError`: pdf_path + stage + error

---

## Pipeline Refactor (ingest/)

### Current Issues

1. **State leakage** - Mutable context dict
2. No dataclasses

### Refactor: Each Module Has Own State - Pipeline.py Unnecessary

**Current pipeline.py problem:**
- `InboxCtx` is a mutable context that passes through all steps
- Reconstructs state transition that already exists in each module

**New design:**
Each module already has its own separated states:
- `mineru.py`: PDFInput → APIResponse → ExtractedContent → ParseResult
- `extractor.py`: Markdown → ExtractedMeta
- `loader.py`: PaperEnricher handles toc/l3

**Conclusion:**
- Pipeline.py is **unnecessary** - each module handles its own state
- Only need CLI-level orchestration (calling modules in sequence)
- No need for `InboxCtx` - delete it
- Keep simple runner that calls: mineru.parse() → extractor.extract() → ...

---

## Data Sources Pattern (sources/)

### Current Modules

| Module | Source Type | Data Flow |
|--------|-------------|----------|
| local.py | Local directory | Scan existing papers |
| endnote.py | Local files | Parse XML/RIS → PaperMetadata |
| zotero.py | Remote API / Local DB | Fetch from API or parse SQLite |
| explore.py | Remote API | OpenAlex → JSONL → PaperMap |

### Analysis

**All sources follow the same pattern:** fetch → parse → extract paper data

| Aspect | local.py | endnote.py | zotero.py | explore.py |
|--------|----------|------------|-----------|------------|
| Input | Local dir | Files | API/SQLite | Remote API |
| Output | Iterator | List | List | JSONL + Map |
| Target | Main library | Main library | Main library | Explore DB |

### Unified Protocol

```python
class PaperSource(Protocol):
    """Protocol for paper data sources (local files, remote APIs, databases)."""
    
    @property
    def name(self) -> str: ...
    
    def fetch(self, **kwargs) -> Iterator[dict]: ...
    
    def count(self, **kwargs) -> int: ...
```

**Implementations:**

```python
@dataclass(frozen=True)
class LocalSource:
    """Scan local papers directory."""
    papers_dir: Path
    
    @property
    def name(self) -> str:
        return "local"
    
    def fetch(self, **kwargs) -> Iterator[dict]: ...
    
    def count(self, **kwargs) -> int: ...


@dataclass(frozen=True)
class EndnoteSource:
    """Parse Endnote XML/RIS files."""
    
    @property
    def name(self) -> str:
        return "endnote"
    
    def fetch(self, paths: list[Path], **kwargs) -> Iterator[dict]: ...


@dataclass(frozen=True)
class ZoteroSource:
    """Import from Zotero API or local SQLite."""
    library_id: str = ""
    api_key: str = ""
    
    @property
    def name(self) -> str:
        return "zotero"
    
    def fetch(self, db_path: Path | None = None, **kwargs) -> Iterator[dict]: ...


@dataclass(frozen=True)
class OpenAlexSource:
    """Fetch from OpenAlex API for journal exploration."""
    
    @property
    def name(self) -> str:
        return "openalex"
    
    def fetch(self, issn: str, year_range: str | None = None, **kwargs) -> Iterator[dict]: ...
```

### Key Insight

The difference is only in **input source** and **target storage** - the fetch/parse/extract pattern is the same for all.

---  

## Sources Module Migration (sources/)

### Current Structure

```
scholaraio/sources/
├── __init__.py       # Empty
├── local.py          # iter_papers() - scan data/papers/
├── endnote.py       # parse_endnote() - parse XML/RIS
└── zotero.py        # fetch_zotero_api(), parse_zotero_local()
```

### Target Structure

```
scholaraio/sources/
├── __init__.py       # Exports: PaperSource, all Source classes
├── protocol.py      # PaperSource Protocol
├── local.py         # LocalSource - scan data/papers/
├── openalex.py     # OpenAlexSource - fetch from OpenAlex
├── endnote.py       # EndnoteSource - parse XML/RIS
└── zotero.py        # ZoteroSource - import from Zotero
```

**explore.py**: DELETE - fetch moved to sources/, process to vectors/topics

### Explore Separation

**Current**: explore.py mixes fetch + process

**Target**: 
- Delete explore.py entirely
- Move fetch to sources/ (PaperSource)
- Move process to functional modules (vectors, topics)

```
scholaraio/sources/    # Fetch: PaperSource + all implementations
scholaraio/vectors.py  # Already has build methods
scholaraio/topics.py  # Already has build methods
```

### Target Structure

```
scholaraio/sources/
├── __init__.py       # Exports: PaperSource, LocalSource, EndnoteSource, ZoteroSource
├── protocol.py      # PaperSource Protocol
├── local.py         # LocalSource implementation
├── endnote.py       # EndnoteSource implementation
└── zotero.py        # ZoteroSource implementation
```

### Migration Steps

| Step | Action |
|------|--------|
| 1 | Create `protocol.py` with PaperSource Protocol |
| 2 | Refactor `local.py` → LocalSource class |
| 3 | Refactor `endnote.py` → EndnoteSource class |
| 4 | Refactor `zotero.py` → ZoteroSource class |
| 5 | Update `__init__.py` to export new classes |
| 6 | Delete old standalone functions (marked BROKEN) |

### Design (same as explore.py)

```python
# protocol.py
class PaperSource(Protocol):
    @property
    def name(self) -> str: ...
    
    def fetch(self, **kwargs) -> Iterator[dict]: ...
    
    def count(self, **kwargs) -> int: ...


# local.py
@dataclass(frozen=True)
class LocalSource:
    papers_dir: Path
    
    @property
    def name(self) -> str:
        return "local"
    
    def fetch(self, **kwargs) -> Iterator[dict]:
        for paper_id, meta, md_path in iter_papers(self.papers_dir):
            yield {...}


# endnote.py  
@dataclass(frozen=True)
class EndnoteSource:
    @property
    def name(self) -> str:
        return "endnote"
    
    def fetch(self, paths: list[Path], **kwargs) -> Iterator[dict]:
        for meta in parse_endnote(paths):
            yield {...}


# zotero.py
@dataclass(frozen=True)
class ZoteroSource:
    library_id: str = ""
    api_key: str = ""
    
    @property
    def name(self) -> str:
        return "zotero"
    
    def fetch(self, db_path: Path | None = None, **kwargs) -> Iterator[dict]:
        ...
```

---

## Module Dependency

```
Layer 0: Foundation
├── config.py
├── log.py ✅
└── papers.py ✅ (patterns)

Layer 1: Core Data
├── loader.py ✅
├── index.py ✅
└── vectors.py ✅ (Protocol pattern)

Layer 2: Features
├── topics.py ✅
└── sources/ ✅ (fetch: Local, OpenAlex, Endnote, Zotero)

Layer 3: Pipeline
├── ingest/mineru.py ✅ (refactored: client injection)
├── ingest/extractor.py ⬜
├── ingest/pipeline.py ⬜ (DELETE - each module has own states)
└── ingest/metadata/* ⬜ (delete)

Layer 4: Entry Points
├── cli/           ✅
├── mcp_server.py  ⬜
├── setup.py
└── export.py
```

**Note**: explore.py is deleted - fetch moved to sources/, process (vectors/topics) remains in respective modules.

---

## Remaining Tasks

| Phase | Task | Description |
|-------|------|-------------|
| 1 | mineru.py | Refactor: client injection pattern |
| 2 | sources/ | Refactor: create protocol.py + move all Source classes |
| 2 | explore.py | **DELETE** - fetch to sources/, process to vectors/topics |
| 2 | pipeline.py | **DELETE** - each module has own states |
| 2 | metadata/* | Delete incompatible modules |
| 3 | mcp_server.py | Redesign to use new APIs |

---

## Checklist

| Status | Module | Task |
|--------|--------|------|
| ✅ Done | log.py | Protocol-based singleton |
| ✅ Done | papers.py | PaperStore + dataclasses |
| ✅ Done | index.py | SearchIndex class |
| ✅ Done | loader.py | StrategyRegistry + PaperEnricher |
| ✅ Done | vectors.py | VectorIndex + Embedder Protocol |
| ✅ Done | topics.py | Separate trainer/output |
| ✅ Done | cli/ | Unified CLI (5 commands) |
| ✅ Done | mineru.py | Refactor: client injection pattern |
| ✅ Done | explore.py | Refactor: unified PaperSource Protocol |
| ⬜ TODO | sources/ | Refactor: create protocol.py + Source classes |
| ⬜ DELETE | pipeline.py | Unnecessary - each module has own states |
| ⬜ TODO | mcp_server.py | Redesign |
| ⬜ TODO | ingest/metadata/* | Delete |

---

## Final Structure

```
scholaraio/
├── config.py
├── log.py          ✅
├── papers.py       ✅
├── index.py        ✅
├── vectors.py      ✅
├── loader.py       ✅
├── topics.py       ✅
├── llm.py          ✅
├── extract.py      ✅
├── sources/        ✅ (fetch: Local, OpenAlex, Endnote, Zotero)
├── ingest/
│   ├── mineru.py   ✅
│   ├── extractor.py
│   ├── pipeline.py # DELETE - each module has own states
│   └── metadata/   # DELETE
├── cli/            ✅
├── cli_legacy.py
├── mcp_server.py   # BROKEN
├── setup.py
└── export.py
```
