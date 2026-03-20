# linkora Architecture Design

> Developer documentation for linkora architecture. Understand how components interact and how to extend the system.

---

## 1. Architecture Overview

### 1.1 Layer Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Entry Points                                          │
│   ├── cli/           CLI commands                               │
│   ├── cli/__init__.py Entry point & AppContext                 │
│   └── cli/commands.py CLI command handlers                     │
├─────────────────────────────────────────────────────────────────┤
│ Layer 2: Features                                               │
│   ├── topics.py       BERTopic clustering                       │
│   ├── loader.py       PaperEnricher (TOC/conclusion)           │
│   └── sources/        PaperSource Protocol + implementations    │
│       ├── protocol.py PaperSource Protocol                     │
│       ├── local.py    Multi-path LocalSource                   │
│       ├── openalex.py OpenAlex API                             │
│       ├── zotero.py   Zotero sync                             │
│       └── endnote.py  Endnote XML/RIS                          │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1: Core Data                                             │
│   ├── ingest/         Paper ingestion                          │
│   │   ├── matching.py DefaultDispatcher                        │
│   │   ├── download.py PDF download                              │
│   │   └── pipeline.py Ingest pipeline                          │
│   ├── index/          FTS5 + FAISS search                     │
│   │   ├── text.py    Full-text search (FTS5)                 │
│   │   └── vector.py  Semantic search (FAISS)                   │
│   └── extract.py      Metadata extraction (regex/LLM)          │
├─────────────────────────────────────────────────────────────────┤
│ Layer 0: Foundation                                             │
│   ├── config.py      Configuration loading & resolution          │
│   ├── log.py        Logging singleton                         │
│   ├── papers.py     PaperStore, metadata, audit               │
│   ├── filters.py    QueryFilter for search                   │
│   ├── llm.py       LLM client abstraction                    │
│   ├── http.py       HTTP client Protocol                      │
│   ├── mineru.py     PDF parsing (MinerU)                      │
│   ├── metrics.py    Metrics collection                         │
│   ├── hash.py       Content hashing                           │
│   └── setup.py      Environment check & init                    │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Data Flow

```
User CLI Input
      ↓
Config (workspace + sources + paths)
      ↓
┌─────────────────────────────────────────────────────────────┐
│ Sources Layer                                               │
│   DefaultDispatcher → LocalSource/OpenAlex/Zotero/Endnote    │
│   Output: PaperCandidate                                   │
└─────────────────────────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────────────────────┐
│ Ingest Pipeline                                            │
│   Download → Parse (MinerU) → Extract metadata              │
│   Output: IngestResult                                     │
└─────────────────────────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────────────────────┐
│ PaperStore (Storage Layer)                                  │
│   Stores: meta.json + paper.md                             │
│   L1: title, authors, year, journal, doi                   │
│   L2: abstract                                             │
│   L3: l3_conclusion (optional, from enrichment)           │
│   L4: paper.md (full markdown)                            │
└─────────────────────────────────────────────────────────────┘
      ↓ Optional
┌─────────────────────────────────────────────────────────────┐
│ Enrichment (Loader)                                        │
│   PaperEnricher: TOC + Conclusion extraction               │
│   Adds: l3_conclusion to meta.json                        │
└─────────────────────────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────────────────────┐
│ Index Layer                                                │
│   SearchIndex (FTS5): title + abstract + l3_conclusion    │
│   VectorIndex (FAISS): title + abstract embeddings         │
└─────────────────────────────────────────────────────────────┘
      ↓
Search Results (JSON)
```

### 1.3 Search Index Types

**Both indexes work independently and are NOT dependent on enrichment.**

| Index | Source | Depends on Enrichment? |
|-------|---------|------------------------|
| **SearchIndex (FTS5)** | title + abstract + l3_conclusion | No (l3_conclusion is optional) |
| **VectorIndex (FAISS)** | title + abstract | No |

- **FTS5 (Full-Text Search)**: Searches text content. If enriched, includes `l3_conclusion` for better coverage.
- **FAISS (Semantic Search)**: Searches by semantic similarity using embeddings of title + abstract.

---

## 2. Key Components

### 2.1 Config Module (`config.py`)

**Responsibility**: Configuration loading, workspace resolution, path resolution.

**Key Types**:
- `Config` - Main configuration object
- `WorkspaceConfig` - Workspace identity
- `SourcesConfig` - Data source settings
- `IndexConfig` - Search index settings
- `LLMConfig` - LLM client settings

**Key Methods**:
```python
# Path resolution
cfg.resolve_local_source_paths()  # list[Path] - all local paths

# API key resolution
cfg.resolve_llm_api_key()         # str
cfg.resolve_mineru_api_key()      # str

# Derived paths
cfg.workspace_dir    # Path
cfg.papers_dir       # Path
cfg.index_db         # Path
cfg.vectors_file     # Path
```

### 2.2 Sources Module (`sources/`)

**PaperSource Protocol** (`sources/protocol.py`):
```python
class PaperSource(Protocol):
    @property
    def name(self) -> str: ...

    def fetch(self, **kwargs) -> Iterator[PaperCandidate]: ...
    def count(self, **kwargs) -> int: ...
```

**LocalSource** (`sources/local.py`) - supports multi-path:
```python
@dataclass
class LocalSource:
    pdf_dirs: list[Path]        # Multiple paths
    recursive: bool = True

    # Unified index (built once)
    _index: dict[str, Path]
    _file_hashes: dict[str, str]
    _path_sources: dict[Path, str]
```

### 2.3 Ingest Module (`ingest/`)

**DefaultDispatcher** (`ingest/matching.py`):
```python
class DefaultDispatcher:
    def __init__(
        self,
        local_pdf_dirs: list[Path] | None = None,
        http_client=None,
    ): ...

    def match_papers(self, query: PaperQuery) -> list[PaperCandidate]: ...
    def score_candidate(self, candidate: PaperCandidate, query: PaperQuery) -> float: ...
```

**Pipeline** (`ingest/pipeline.py`):
```python
def ingest(
    candidate: PaperCandidate,
    client: PDFClient,
    papers_dir: Path,
    http_client: HTTPClient | None = None,
) -> IngestResult: ...
```

### 2.4 Index Module (`index/`)

**SearchIndex** (`index/text.py`) - FTS5 full-text search:
```python
class SearchIndex:
    """Full-text search using SQLite FTS5."""

    def search(self, query: str, top_k: int = 20, **filters) -> list[dict]: ...
    def search_author(self, author: str, top_k: int = 20) -> list[dict]: ...
    def top_cited(self, top_k: int = 20, **filters) -> list[dict]: ...
```

**VectorIndex** (`index/vector.py`) - FAISS semantic search:
```python
class VectorIndex:
    """Semantic search using FAISS."""

    def search(self, query: str, top_k: int = 10, **filters) -> list[dict]: ...
```

### 2.5 Loader Module (`loader.py`)

**PaperEnricher** - Optional enrichment:
```python
class PaperEnricher:
    """Extract TOC and conclusion from papers (OPTIONAL)."""

    def enrich_toc(self, paper_id: str, *, force: bool = False) -> bool: ...
    def enrich_conclusion(self, paper_id: str, *, force: bool = False) -> bool: ...
    # Adds l3_conclusion to meta.json for enhanced search
```

### 2.6 CLI Context (`cli/context.py`)

**AppContext** - Lazy resource injection:
```python
@dataclass
class AppContext:
    config: Config

    # Lazy resources (created on first access)
    def http_client(self) -> HTTPClient: ...
    def llm_runner(self) -> LLMRunner: ...
    def paper_store(self) -> PaperStore: ...
    def search_index(self) -> SearchIndex: ...
    def vector_index(self) -> VectorIndex: ...
    def paper_enricher(self) -> PaperEnricher: ...
    def source_dispatcher(self) -> DefaultDispatcher: ...
```

---

## 3. Multi-Path Support

### 3.1 Design Decision

Multiple local paths are managed as a **single unified source** for efficiency:
- One shared index covering all paths
- Single file hash cache across all paths
- Deduplication at candidate level
- Single-threaded sequential scan

### 3.2 Implementation

**Config** (`config.py`):
```python
def resolve_local_source_paths(self) -> list[Path]:
    """Resolve all local source paths from config."""
    local = self.sources.local
    paths = []

    # Primary papers_dir
    if local.papers_dir:
        paths.append(self._resolve_path(local.papers_dir))

    # Additional paths
    for path_str in local.paths or []:
        if path_str:
            paths.append(self._resolve_path(path_str))

    return paths
```

**LocalSource** (`sources/local.py`):
```python
@dataclass
class LocalSource:
    pdf_dirs: list[Path]  # Multiple paths
    recursive: bool = True

    _index: dict[str, Path] = field(default_factory=dict)
    _file_hashes: dict[str, str] = field(default_factory=dict)
    _path_sources: dict[Path, str] = field(default_factory=dict)
```

**Dispatcher** (`ingest/matching.py`):
```python
class DefaultDispatcher:
    def __init__(
        self,
        local_pdf_dirs: list[Path] | None = None,
        http_client=None,
    ):
        self._local_pdf_dirs = local_pdf_dirs or []
        self._http_client = http_client
        self._local_source: PaperSource | None = None

    def _ensure_sources(self) -> None:
        """Create single LocalSource with all paths."""
        if self._local_pdf_dirs:
            self._local_source = LocalSource(pdf_dirs=self._local_pdf_dirs)
```

---

## 4. Filter System

### 4.1 QueryFilter (`filters.py`)

Unified filter for all operations:
```python
@dataclass(frozen=True)
class QueryFilter:
    year: str | None = None      # "2024", ">2020", "2020-2024"
    journal: str | None = None    # Partial match
    paper_type: str | None = None # Exact match
    author: str | None = None     # Partial match

    def matches(self, meta: dict) -> bool: ...
```

### 4.2 FilterParams (`index/text.py`)

FTS5 filter with SQL generation:
```python
@dataclass(frozen=True)
class FilterParams(QueryFilter):
    def to_sql(self) -> tuple[str, list[str]]: ...
```

---

## 5. Module Dependencies

```
linkora/
├── config.py        Config loading & resolution
├── papers.py       PaperStore, PaperMetadata, audit
├── filters.py      QueryFilter
├── hash.py         Content hashing
├── llm.py          LLM client
├── http.py         HTTP client Protocol
├── mineru.py       PDF parsing (MinerU)
├── loader.py       PaperEnricher (enrichment)
├── extract.py      Metadata extraction
├── metrics.py      Metrics
├── log.py          Logging
├── setup.py        Environment check & init
├── topics.py       Topic modeling (BERTopic)

linkora/sources/         Paper sources
├── protocol.py         PaperSource Protocol
├── local.py            LocalSource (multi-path)
├── openalex.py         OpenAlex API
├── zotero.py           Zotero
└── endnote.py         Endnote

linkora/ingest/         Paper ingestion
├── matching.py         DefaultDispatcher
├── download.py         PDF download
└── pipeline.py         Ingest pipeline

linkora/index/          Search indexes
├── text.py            SearchIndex (FTS5)
└── vector.py          VectorIndex (FAISS)

linkora/cli/           CLI
├── __init__.py        AppContext, CLI entry
├── commands.py        Command handlers
├── context.py         Lazy resource injection
├── output.py          UI formatting
└── errors.py          Error handling
```

---

## 6. Extension Points

### 6.1 Adding a New Source

1. Create `sources/mysource.py`:
```python
@dataclass(frozen=True)
class MySource:
    @property
    def name(self) -> str:
        return "mysource"

    def fetch(self, **kwargs) -> Iterator[PaperCandidate]: ...
    def count(self, **kwargs) -> int: ...
```

2. Register in `DefaultDispatcher`:
```python
# In _ensure_sources()
if self._my_config:
    self._my_source = MySource(...)
```

### 6.2 Adding a New CLI Command

1. Add handler in `cli/commands.py`:
```python
def cmd_mycommand(args: argparse.Namespace, ctx: AppContext) -> None:
    # Use ctx for resources
    store = ctx.paper_store()
    # ...
```

2. Register in `cli/__init__.py`:
```python
parser = subparsers.add_parser("mycommand")
parser.set_defaults(func=cmd_mycommand)
```

---

## 7. Design Patterns

### 7.1 Context Injection

Resources are lazy-loaded via AppContext:
```python
# Don't do this:
def cmd_search(args, ctx):
    store = PaperStore(ctx.config.papers_dir)  # Creates every time

# Do this:
def cmd_search(args, ctx):
    store = ctx.paper_store()  # Reuses cached instance
```

### 7.2 Protocol-Based Design

Use Protocol for interfaces:
```python
class PDFClient(Protocol):
    @property
    def name(self) -> str: ...
    def call(self, pdf_path: Path, opts: ParseOptions) -> dict: ...

# Implementations:
@dataclass(frozen=True)
class LocalClient:
    base_url: str = "http://localhost:8000"
    def call(self, pdf_path: Path, opts: ParseOptions) -> dict: ...

@dataclass(frozen=True)
class CloudClient:
    api_key: str
    def call(self, pdf_path: Path, opts: ParseOptions) -> dict: ...
```

### 7.3 Immutable Data

Use frozen dataclasses for config and results:
```python
@dataclass(frozen=True)
class ExtractionResult:
    success: bool
    paper_id: str
    method: str
    error: str = ""
```

---

## 8. Testing Strategy

### 8.1 Unit Tests

Test pure functions and data transformations:
- `filters.py` - QueryFilter matching
- `hash.py` - Content hashing
- `audit rules` - Data quality checks
- `config.py` - Path resolution

### 8.2 Integration Tests

Test data flow end-to-end:
- Config resolution with mocked paths
- LocalSource multi-path scanning
- SearchIndex FTS queries
- PaperStore CRUD operations

### 8.3 What NOT to Test

External dependencies (mock-based tests don't add value):
- LLM API calls
- MinerU API calls
- Network I/O
- External ML libraries (FAISS, BERTopic)

---

## 9. Implementation Status

| Feature | Status | Location |
|---------|--------|----------|
| Multi-path local sources | ✅ Implemented | config.py, sources/local.py |
| QueryFilter | ✅ Implemented | filters.py |
| AppContext | ✅ Implemented | cli/context.py |
| Layered config | ✅ Implemented | config.py |
| Protocol-based sources | ✅ Implemented | sources/protocol.py |
| Protocol-based HTTP | ✅ Implemented | http.py |
| PaperEnricher | ✅ Implemented | loader.py |
