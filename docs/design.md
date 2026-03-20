# linkora Architecture Design

> Developer documentation for linkora architecture. Understand how components interact and how to extend the system.

---

## 1. Architecture Overview

### 1.1 Design Philosophy

linkora is built around three core principles:

1. **Local-First**: All data stays local — papers, indexes, and metadata are stored on your machine
2. **Workspace Isolation**: Each research project lives in its own workspace with independent data
3. **Single Source of Truth**: Configuration and data paths have canonical sources that all code references

### 1.2 Layer Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Entry Points                                          │
│   ├── cli/                  CLI commands & entry point        │
│   └── linkora/__init__.py   Python package entry               │
├─────────────────────────────────────────────────────────────────┤
│ Layer 2: Features                                              │
│   ├── topics.py             BERTopic clustering               │
│   ├── loader.py             PaperEnricher (TOC/conclusion)     │
│   └── sources/              PaperSource Protocol + impls       │
│       ├── protocol.py       PaperSource Protocol               │
│       ├── local.py          Multi-path LocalSource             │
│       ├── openalex.py       OpenAlex API                       │
│       ├── zotero.py         Zotero sync                        │
│       └── endnote.py        EndNote XML/RIS                    │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1: Core Data                                             │
│   ├── ingest/               Paper ingestion                    │
│   │   ├── matching.py       DefaultDispatcher                  │
│   │   ├── download.py      PDF download                        │
│   │   └── pipeline.py      Ingest pipeline                    │
│   ├── index/               FTS5 + FAISS search                 │
│   │   ├── text.py          Full-text search (FTS5)             │
│   │   └── vector.py        Semantic search (FAISS)            │
│   └── extract.py           Metadata extraction (regex/LLM)    │
├─────────────────────────────────────────────────────────────────┤
│ Layer 0: Foundation                                            │
│   ├── config.py            Configuration loading & resolution  │
│   ├── workspace.py          Workspace registry & path resolution│
│   ├── log.py                Logging singleton                  │
│   ├── papers.py             PaperStore, metadata, audit        │
│   ├── filters.py            QueryFilter for search            │
│   ├── llm.py                LLM client abstraction             │
│   ├── http.py               HTTP client Protocol               │
│   ├── mineru.py             PDF parsing (MinerU)               │
│   ├── metrics.py           Metrics collection                 │
│   ├── hash.py               Content hashing                    │
│   └── setup.py             Environment check & init           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Configuration System

### 2.1 Config Resolution

The config system follows a **single file wins** policy:

```
Priority (highest to lowest):
1. ~/.linkora/config.yml
2. ~/.config/linkora/config.yml  
3. Built-in defaults
```

**Key invariant**: Exactly ONE config file is used — there is NO merging. If multiple files exist, the highest-priority one wins and a warning is emitted.

### 2.2 Key Types

Located in [`linkora/config.py`](../linkora/config.py):

```python
# Top-level config
class AppConfig(BaseModel):
    sources: SourcesConfig
    index: IndexConfig
    llm: LLMConfig
    ingest: IngestConfig
    topics: TopicsConfig
    log: LogConfig

# Lazy API key resolution
AppConfig.resolve_llm_api_key() -> str
AppConfig.resolve_zotero_api_key() -> str
AppConfig.resolve_mineru_api_key() -> str
AppConfig.resolve_local_source_paths(config_dir: Path) -> list[Path]
```

### 2.3 ConfigLoader

```python
class ConfigLoader:
    @staticmethod
    def candidates() -> tuple[Path, ...]:  # All candidate paths
    
    @staticmethod
    def find_all() -> list[Path]:  # Existing config files
    
    @staticmethod
    def active_path() -> Path | None:  # Highest-priority existing file
    
    @staticmethod
    def default_write_path() -> Path:  # Where to write new config
    
    def load() -> tuple[AppConfig, Path | None]:  # Load active config
```

---

## 3. Workspace System

### 3.1 Concept

A **workspace** is a self-contained research environment. Each workspace has:
- Its own papers directory
- Its own search index (FTS5)
- Its own vector index (FAISS)
- Its own metadata (name, description, created_at)

Workspaces are **managed entirely by CLI commands** — not by user-editable config files.

### 3.2 Data Layout

```
<data_root>/                    # Platform-specific (see below)
└── workspace/
    ├── workspaces.json         # Registry: workspace names + default
    ├── default/                # "default" workspace
    │   ├── workspace.json      # Metadata (name, description, created_at)
    │   ├── papers/             # Paper directories (each has meta.json)
    │   ├── index.db            # FTS5 search index
    │   ├── vectors.faiss       # FAISS vector index
    │   └── logs/               # Workspace-specific logs
    └── <name>/                 # Other workspaces
        └── ...
```

### 3.3 Data Root Resolution

Located in [`linkora/workspace.py`](../linkora/workspace.py):

```python
def get_data_root() -> Path:
    """
    Platform-appropriate linkora data directory.
    Override via LINKORA_ROOT environment variable.
    """
    # Windows:   %APPDATA%/linkora
    # macOS:     ~/Library/Application Support/linkora
    # Linux:     $XDG_DATA_HOME/linkora (~/.local/share/linkora)
```

### 3.4 Key Types

```python
@dataclass(frozen=True)
class WorkspaceMetadata:
    """Persistent identity data - ONLY name, description, created_at."""
    name: str
    description: str = ""
    created_at: str = ""

@dataclass(frozen=True)
class WorkspacePaths:
    """Computed paths - NEVER stored on disk."""
    data_root: Path
    name: str
    
    @property
    def workspace_dir(self) -> Path: ...
    @property
    def papers_dir(self) -> Path: ...
    @property
    def index_db(self) -> Path: ...
    @property
    def vectors_file(self) -> Path: ...
    @property
    def metadata_file(self) -> Path: ...

class WorkspaceStore:
    """Manages workspace registry and metadata."""
    
    def list_workspaces(self) -> list[str]: ...
    def get_default(self) -> str: ...
    def set_default(self, name: str) -> None: ...
    def get_metadata(self, name: str) -> WorkspaceMetadata: ...
    def set_metadata(self, name: str, *, description: str) -> None: ...
    def create(self, name: str, description: str = "") -> WorkspacePaths: ...
    def delete(self, name: str) -> None: ...
    def migrate(self, source: str, target: str) -> int: ...  # Rename/relocate
    def paths(self, name: str) -> WorkspacePaths: ...
```

---

## 4. Data Flow

### 4.1 Paper Import Flow

```
User CLI Input (add command)
         ↓
    Config + Workspace
         ↓
┌─────────────────────────────────────────────────────────────┐
│ Sources Layer                                               │
│   DefaultDispatcher → LocalSource/OpenAlex/Zotero/Endnote  │
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
│   PaperEnricher: TOC + Conclusion extraction              │
│   Adds: l3_conclusion to meta.json                        │
└─────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│ Index Layer                                                │
│   SearchIndex (FTS5): title + abstract + l3_conclusion    │
│   VectorIndex (FAISS): title + abstract embeddings         │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Search Flow

```
User CLI Input (search command)
         ↓
    Config + Workspace
         ↓
┌─────────────────────────────────────────────────────────────┐
│ Search Modes                                                │
│   fulltext → SearchIndex (FTS5)                           │
│   author   → SearchIndex.author                           │
│   vector   → VectorIndex (FAISS)                          │
│   hybrid   → Combined (FTS5 + FAISS, RRF)                │
└─────────────────────────────────────────────────────────────┘
         ↓
    Search Results (JSON)
```

### 4.3 Index Independence

**Both indexes work independently and are NOT dependent on enrichment.**

| Index | Source | Depends on Enrichment? |
|-------|--------|------------------------|
| **SearchIndex (FTS5)** | title + abstract + l3_conclusion | No (l3_conclusion is optional) |
| **VectorIndex (FAISS)** | title + abstract | No |

---

## 5. Key Components

### 5.1 Sources Module (`sources/`)

**PaperSource Protocol** (`sources/protocol.py`):
```python
class PaperSource(Protocol):
    @property
    def name(self) -> str: ...

    def fetch(self, **kwargs) -> Iterator[PaperCandidate]: ...
    def count(self, **kwargs) -> int: ...
```

**LocalSource** (`sources/local.py`) - supports multiple paths:
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

### 5.2 Ingest Module (`ingest/`)

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

### 5.3 Index Module (`index/`)

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

### 5.4 Loader Module (`loader.py`)

**PaperEnricher** - Optional enrichment:
```python
class PaperEnricher:
    """Extract TOC and conclusion from papers (OPTIONAL)."""

    def enrich_toc(self, paper_id: str, *, force: bool = False) -> bool: ...
    def enrich_conclusion(self, paper_id: str, *, force: bool = False) -> bool: ...
    # Adds l3_conclusion to meta.json for enhanced search
```

### 5.5 CLI Context (`cli/context.py`)

**AppContext** - Lazy resource injection:
```python
@dataclass
class AppContext:
    config: Config
    workspace_name: str
    store: WorkspaceStore

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

## 6. Multi-Path Support

### 6.1 Design Decision

Multiple local paths are managed as a **single unified source** for efficiency:
- One shared index covering all paths
- Single file hash cache across all paths
- Deduplication at candidate level
- Single-threaded sequential scan

### 6.2 Implementation

**Config** (`config.py`):
```python
def resolve_local_source_paths(self, config_dir: Path) -> list[Path]:
    """Resolve all local source paths from config."""
    local = self.sources.local
    paths = []

    # Primary papers_dir (workspace-relative)
    if local.papers_dir:
        paths.append(self._resolve_path(local.papers_dir))

    # Additional paths (absolute or home-relative)
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

## 7. Filter System

### 7.1 QueryFilter (`filters.py`)

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

### 7.2 FilterParams (`index/text.py`)

FTS5 filter with SQL generation:
```python
@dataclass(frozen=True)
class FilterParams(QueryFilter):
    def to_sql(self) -> tuple[str, list[str]]: ...
```

---

## 8. Module Dependencies

```
linkora/
├── config.py         Config loading & resolution
├── workspace.py     Workspace registry & path resolution
├── papers.py        PaperStore, PaperMetadata, audit
├── filters.py       QueryFilter
├── hash.py          Content hashing
├── llm.py           LLM client
├── http.py          HTTP client Protocol
├── mineru.py        PDF parsing (MinerU)
├── loader.py        PaperEnricher (enrichment)
├── extract.py       Metadata extraction
├── metrics.py       Metrics
├── log.py           Logging
├── setup.py         Environment check & init
├── topics.py        Topic modeling (BERTopic)

linkora/sources/         Paper sources
├── protocol.py         PaperSource Protocol
├── local.py            LocalSource (multi-path)
├── openalex.py         OpenAlex API
├── zotero.py           Zotero
└── endnote.py          EndNote

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

## 9. Extension Points

### 9.1 Adding a New Source

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

### 9.2 Adding a New CLI Command

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

## 10. Design Patterns

### 10.1 Context Injection

Resources are lazy-loaded via AppContext:
```python
# Don't do this:
def cmd_search(args, ctx):
    store = PaperStore(ctx.config.papers_dir)  # Creates every time

# Do this:
def cmd_search(args, ctx):
    store = ctx.paper_store()  # Reuses cached instance
```

### 10.2 Protocol-Based Design

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

### 10.3 Immutable Data

Use frozen dataclasses for config and results:
```python
@dataclass(frozen=True)
class ExtractionResult:
    success: bool
    paper_id: str
    method: str
    error: str = ""
```

### 10.4 Single Source of Truth

All code references canonical sources:
- Data root: `get_data_root()` — never inline platform detection
- Config: `get_config()` — singleton, lazy-loaded
- Workspace paths: `WorkspacePaths` — computed, never stored

---

## 11. Testing Strategy

### 11.1 Unit Tests

Test pure functions and data transformations:
- `filters.py` - QueryFilter matching
- `hash.py` - Content hashing
- `audit rules` - Data quality checks
- `config.py` - Path resolution

### 11.2 Integration Tests

Test data flow end-to-end:
- Config resolution with mocked paths
- LocalSource multi-path scanning
- SearchIndex FTS queries
- PaperStore CRUD operations
- Workspace create/migrate/delete

### 11.3 What NOT to Test

External dependencies (mock-based tests don't add value):
- LLM API calls
- MinerU API calls
- Network I/O
- External ML libraries (FAISS, BERTopic)

---

## 12. Implementation Status

| Feature | Status | Location |
|---------|--------|----------|
| Multi-path local sources | ✅ Implemented | config.py, sources/local.py |
| QueryFilter | ✅ Implemented | filters.py |
| Workspace isolation | ✅ Implemented | workspace.py |
| Config single-file policy | ✅ Implemented | config.py |
| Lazy API key resolution | ✅ Implemented | config.py |
| FTS5 search | ✅ Implemented | index/text.py |
| FAISS vector search | ✅ Implemented | index/vector.py |
| Hybrid search | 🔄 Partial | index/*.py |
