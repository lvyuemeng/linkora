# ScholarAIO Implementation Plan

> Connecting design, concrete modules, commands, and configurations.

---

## 1. Design Principles

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

---

## 2. Code Style Guidelines

### Logging
```python
# Old (ugly):
import logging
_log = logging.getLogger(__name__)

# New (use singleton):
from scholaraio.log import get_logger, ui
_log = get_logger(__name__)
ui("Processing %d files", count)
```

### Type Imports
```python
# Old:
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pathlib import Path

# New (force import):
from pathlib import Path  # No TYPE_CHECKING guard needed
```

---

## 3. CLI Design (5 Unified Commands + Export)

| Command | Flags | Function |
|---------|-------|----------|
| search | --mode fts\|author\|vector\|hybrid\|cited | Full-text, author, semantic, hybrid, citation search |
| index | --type fts\|vector | Build FTS or vector index |
| audit | - | Data quality audit |
| setup | - | Environment setup wizard |
| metrics | - | Performance metrics |
| export | - | BibTeX export |

---

## 4. Module Restructure

### 4.1 Delete explore.py
- Fetch logic → `sources/openalex.py` (DONE)
- Process logic → `vectors.py`, `topics.py` (already separate)
- Remove `explore.py` entirely

### 4.2 Create index/ Module

```
scholaraio/index/
├── __init__.py          # Exports: SearchIndex, VectorIndex
├── text.py             # FTS5 full-text search (renamed from index.py)
└── vector.py           # FAISS semantic search (renamed from vectors.py)
```

**Why**: Group related search functionality together, clear separation of concerns.

### 4.3 Module Dependency

```
scholaraio/
├── config.py           # Configuration (see Section 5)
├── papers.py           # Paper storage & metadata
├── loader.py           # L1-L4 layered loading
├── llm.py              # LLM client
├── mineru.py           # PDF parsing (PDFClient Protocol)
├── extract.py          # Metadata extraction
├── topics.py           # Topic modeling (BERTopic)
├── index/             # SEARCH MODULE
│   ├── text.py        # FTS5 search
│   └── vector.py      # FAISS semantic search
├── sources/           # DATA SOURCES
│   ├── protocol.py    # PaperSource Protocol
│   ├── local.py       # Local directory scan
│   ├── openalex.py    # OpenAlex API
│   ├── zotero.py      # Zotero API/SQLite
│   └── endnote.py     # Endnote XML/RIS
└── cli/               # Commands
```

---

## 5. Configuration Redesign

### Current Issues
| Issue | Example |
|-------|---------|
| Vague naming | `EmbedConfig`, `SearchConfig`, `TopicsConfig` |
| Overlap | `IngestConfig` overlaps with `mineru.py` |
| Shared not clear | `PathsConfig` used by all |
| Redundant | `zotero` source mixed with services |

### New Design: Group by Functionality

```
Config
├── workspace       # Workspace identity (multi-tenancy)
├── paths           # Storage paths (RESOLVED from workspace)
├── index           # Search configuration
├── sources         # Data source configuration
├── ingest          # PDF processing (mineru)
├── llm             # AI processing
└── logging         # Monitoring
```

### 5.1 WorkspaceConfig (NEW)
```python
@dataclass(frozen=True)
class WorkspaceConfig:
    """Workspace identity - determines storage location."""
    name: str = "default"
    description: str = ""

# Storage paths resolved from workspace:
# - workspace_dir = root / workspace / {name}
# - index_db = workspace_dir / index.db
# - papers_dir = workspace_dir / papers
# - vectors = workspace_dir / vectors.faiss
```

### 5.2 IndexConfig (MERGED: SearchConfig + EmbedConfig)
```python
@dataclass(frozen=True)
class IndexConfig:
    """Index module configuration (FTS + Vector)."""
    # FTS
    top_k: int = 20
    # Vector
    embed_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embed_device: str = "auto"
    embed_cache: str = "~/.cache/modelscope/hub/models"
    embed_top_k: int = 10
    # Chunking (for L3 content)
    chunk_size: int = 800
    chunk_overlap: int = 150
```

### 5.3 SourcesConfig (MERGED: Zotero + Sources)
```python
@dataclass(frozen=True)
class SourcesConfig:
    """Data source configuration."""
    # Local
    local_enabled: bool = True
    # OpenAlex
    openalex_enabled: bool = True
    # Zotero
    zotero_enabled: bool = False
    zotero_library_id: str = ""
    zotero_api_key: str = ""  # Resolved from env
    # Endnote
    endnote_enabled: bool = True
```

### 5.4 IngestConfig (mineru.py)
```python
@dataclass(frozen=True)
class IngestConfig:
    """PDF ingestion configuration."""
    # Extractor
    extractor: str = "robust"  # regex | auto | llm | robust
    # MinerU
    mineru_endpoint: str = "http://localhost:8000"
    mineru_api_key: str = ""  # Resolved from env
    mineru_cloud_url: str = "https://mineru.net/api/v4"
    # LLM Abstract
    abstract_llm_mode: str = "verify"  # off | fallback | verify
    contact_email: str = ""
```

### 5.5 LLMConfig (unchanged)
```python
@dataclass(frozen=True)
class LLMConfig:
    """LLM client configuration."""
    backend: str = "openai-compat"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""  # Resolved from env
    timeout: int = 30
```

### 5.6 LogConfig (unchanged)
```python
@dataclass(frozen=True)
class LogConfig:
    """Logging configuration."""
    level: str = "INFO"
    file: str = "data/scholaraio.log"
    metrics_db: str = "data/metrics.db"
```

### 5.7 Main Config
```python
@dataclass
class Config:
    """ScholarAIO configuration."""
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    logging: LogConfig = field(default_factory=LogConfig)

    _root: Path = field(default_factory=Path.cwd, repr=False, compare=False)

    # Resolved Paths (derived from workspace)
    @property
    def workspace_dir(self) -> Path:
        return (self._root / "workspace" / self.workspace.name).resolve()

    @property
    def index_db(self) -> Path:
        return self.workspace_dir / "index.db"

    @property
    def papers_dir(self) -> Path:
        return self.workspace_dir / "papers"

    @property
    def vectors_file(self) -> Path:
        return self.workspace_dir / "vectors.faiss"
```

---

## 6. Config Dependency Graph

```
Config
├── workspace          # Identity → determines storage
├── paths (resolved)   # Derived from workspace
├── index              # Used by: search, index commands
│   └── chunk_size    # Used by: loader.py (L3)
├── sources            # Used by: import commands
│   ├── local         # → papers.py
│   ├── openalex      # → sources/openalex.py
│   ├── zotero        # → sources/zotero.py
│   └── endnote       # → sources/endnote.py
├── ingest             # Used by: ingest command
│   └── extractor     # → extract.py
├── llm                # Used by: extract.py, loader.py
└── logging            # Used by: all modules
```

---

## 7. Implementation Order

```
1. Module Restructure
   ├── 1.1 Delete explore.py
   ├── 1.2 Create scholaraio/index/ directory
   ├── 1.3 Move index.py → index/text.py
   └── 1.4 Move vectors.py → index/vector.py

2. Config Redesign
   ├── 2.1 Add WorkspaceConfig
   ├── 2.2 Create IndexConfig (merge Search + Embed)
   ├── 2.3 Create SourcesConfig (merge Zotero + Sources)
   ├── 2.4 Keep IngestConfig, LLMConfig, LogConfig
   └── 2.5 Add resolve_*() for API keys

3. CLI Refactor
   ├── 3.1 search --mode (fts|author|vector|hybrid|cited)
   ├── 3.2 index --type (fts|vector)
   └── 3.3 Keep audit, setup, metrics, export

4. Integration Tests
   └── Test: CLI → Config → Module flows
```

---

## 8. Data Structure Patterns

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

## 9. Completed Modules

| Module | Status | Key Changes |
|--------|--------|-------------|
| log.py | ✅ | LoggerManager singleton, HasLogConfig Protocol |
| papers.py | ✅ | PaperStore, PaperMetadata, YearRange, Issue, PaperFilter |
| index/ (text.py) | ✅ | FTS5 search (moved from index.py) |
| index/ (vector.py) | ✅ | FAISS semantic search (moved from vectors.py) |
| loader.py | ✅ | StrategyRegistry, PromptTemplate, PaperEnricher |
| topics.py | ✅ | TopicConfig, TopicTrainer, TopicModelOutput |
| cli/ | ⬜ | Need to merge to 5 commands |
| llm.py | ✅ | LLM client abstraction |
| extract.py | ✅ | Extraction utilities |
| mineru.py | ✅ | PDFClient Protocol, LocalClient, CloudClient |
| sources/ | ✅ | PaperSource Protocol + 4 implementations |

---

## 10. Key Refactor Designs

### 10.1 PDF Parser (mineru.py) - COMPLETED

**Client Injection Pattern** - Separate HTTP client as injectable Protocol:

```python
class PDFClient(Protocol):
    @property
    def name(self) -> str: ...
    def check_health(self) -> bool: ...
    def call(self, pdf_path: Path, opts: ParseOptions) -> dict: ...

@dataclass(frozen=True)
class LocalClient:
    base_url: str = "http://localhost:8000"
    def call(self, pdf_path: Path, opts: ParseOptions) -> dict: ...

@dataclass(frozen=True)
class CloudClient:
    api_key: str
    def call(self, pdf_path: Path, opts: ParseOptions) -> dict: ...

class PDFParser:
    def __init__(self, client: PDFClient):
        self._client = client
```

### 10.2 Data Sources Pattern - COMPLETED

```python
class PaperSource(Protocol):
    @property
    def name(self) -> str: ...
    def fetch(self, **kwargs) -> Iterator[dict]: ...
    def count(self, **kwargs) -> int: ...

@dataclass(frozen=True)
class LocalSource:
    papers_dir: Path
    @property
    def name(self) -> str: return "local"
    def fetch(self, **kwargs) -> Iterator[dict]: ...

@dataclass(frozen=True)
class OpenAlexSource:
    @property
    def name(self) -> str: return "openalex"
    def fetch(self, issn: str, year_range: str | None = None, **kwargs) -> Iterator[dict]: ...

@dataclass(frozen=True)
class ZoteroSource:
    library_id: str = ""
    api_key: str = ""
    @property
    def name(self) -> str: return "zotero"
    def fetch(self, db_path: Path | None = None, **kwargs) -> Iterator[dict]: ...

@dataclass(frozen=True)
class EndnoteSource:
    @property
    def name(self) -> str: return "endnote"
    def fetch(self, paths: list[Path], **kwargs) -> Iterator[dict]: ...
```

---

## Summary

| Category | Action |
|----------|--------|
| Commands | 5 unified + export |
| Modules | index/ (text + vector), sources/ (all sources), delete explore.py |
| Config | workspace, index, sources, ingest, llm, logging |
| Patterns | Frozen dataclasses, resolve_*() methods on Config |
| Status | Module restructure ✅, Config redesign ✅, CLI refactor ⬜ |

---

## Config Refactor (v2)

### Changes from Section 5

1. **Removed Protocol classes** - Not needed for Config dataclass
2. **Removed backward compatibility wrappers** - ZoteroCompat, EmbedCompat, SearchCompat deleted
3. **API key resolution as Config methods** - `resolve_llm_api_key()`, `resolve_zotero_api_key()`, `resolve_zotero_library_id()`, `resolve_mineru_api_key()`
4. **Workspace from config** - WorkspaceConfig.name read from config.yaml, paths derived from workspace

### Updated Config Structure

```python
@dataclass
class Config:
    workspace: WorkspaceConfig
    index: IndexConfig
    sources: SourcesConfig
    ingest: IngestConfig
    llm: LLMConfig
    topics: TopicsConfig
    log: LogConfig
    _root: Path

    # API key resolution
    def resolve_llm_api_key(self) -> str: ...
    def resolve_zotero_api_key(self) -> str: ...
    def resolve_zotero_library_id(self) -> str: ...
    def resolve_mineru_api_key(self) -> str: ...

    # Path properties (derived from workspace)
    @property
    def workspace_dir(self) -> Path: ...
    @property
    def papers_dir(self) -> Path: ...
    @property
    def index_db(self) -> Path: ...
```

### Broken API Marked

Old APIs marked with `# BROKEN:` until refactored:
- `cfg.api_key("zotero")` → use `cfg.resolve_zotero_api_key()`
- `cfg.api_key("zotero", "library_id")` → use `cfg.resolve_zotero_library_id()`
- `cfg.api_key("mineru")` → use `cfg.resolve_mineru_api_key()`
- `cfg.zotero` → use `cfg.sources`
- `cfg.embed` → use `cfg.index`
- `cfg.search` → use `cfg.index`
