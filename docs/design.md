# linkora Design - Updated

> Ideal architecture for a general-purpose local knowledge network.
> Updated: Multiple local paths support with efficiency focus

---

## 1. Project Goal

**linkora** is a local knowledge network that enables AI-powered research and knowledge management. It provides:

- **Unified knowledge base** with multiple workspaces
- **Layered content loading** (L1-L4) for progressive access
- **Semantic retrieval** via embeddings and vector search
- **Source-agnostic** paper ingestion from multiple formats
- **Multiple local sources** with efficient unified indexing

### Core Principles

| Principle | Description |
|-----------|-------------|
| Local-First | All data stored locally (privacy, offline capability) |
| AI-Native | Designed for AI coding agents with JSON output |
| Zero Config | Environment variables auto-detected, smart defaults |
| Functional Design | Pure functions, pipeline composition, dataclass-based state |
| Efficiency-First | Minimize memory usage, reuse caches, lazy initialization |

---

## 2. Architecture

### Layer Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Entry Points                                           │
│   ├── cli/          CLI commands                                │
│   ├── mcp.py        MCP server for AI agents                    │
│   └── export.py     BibTeX export                               │
├─────────────────────────────────────────────────────────────────┤
│ Layer 2: Features                                               │
│   ├── topics.py     BERTopic clustering                          │
│   └── sources/     PaperSource Protocol + implementations       │
│       ├── local.py  Multi-path LocalSource (UPDATED)            │
│       └── ...       Other sources                               │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1: Core Data                                              │
│   ├── loader.py     L1-L4 layered loading                      │
│   ├── index/       FTS5 + FAISS search                         │
│   │   ├── text.py  Full-text search                             │
│   │   └── vector.py Semantic search                             │
│   └── extract.py    Metadata extraction (regex/LLM)             │
├─────────────────────────────────────────────────────────────────┤
│ Layer 0: Foundation                                              │
│   ├── config.py    Configuration loading & resolution           │
│   ├── log.py       Logging singleton                            │
│   ├── papers.py    PaperStore, metadata handling                │
│   ├── audit.py     Data quality auditing                        │
│   ├── filters.py   Protocol-based filtering                     │
│   ├── llm.py       LLM client abstraction                      │
│   ├── http.py      HTTP client Protocol                         │
│   ├── mineru.py    PDF parsing (MinerU)                         │
│   └── metrics.py   Metrics collection                          │
└─────────────────────────────────────────────────────────────────┘
```

### Module Reference

| Module | Responsibility | Key Types |
|--------|---------------|-----------|
| `config.py` | Config loading, workspace resolution, multi-path resolution | `Config`, `LocalSourceConfig`, `resolve_local_source_paths()` |
| `sources/local.py` | Multi-path local PDF scanning with unified cache | `LocalSource`, `MultiPathLocalSource` |
| `ingest/matching.py` | Source dispatcher for paper matching | `DefaultDispatcher` |
| `cli/context.py` | Lazy context injection for commands | `AppContext` |
| `cli/commands.py` | CLI command handlers | `cmd_add`, `cmd_search`, etc. |

---

## 3. Configuration

### LocalSourceConfig (Updated for Multiple Paths)

```python
@dataclass(frozen=True)
class LocalSourceConfig:
    enabled: bool = True
    papers_dir: str = "papers"           # Primary path (workspace relative)
    paths: list[str] = field(default_factory=list)  # Additional absolute/relative paths
```

### Path Resolution

```python
def resolve_local_source_paths(self) -> list[Path]:
    """Resolve all local source paths from config.
    
    Returns:
        List of paths: papers_dir + additional paths.
        Resolved relative to config file root, NOT workspace root.
    """
```

**Resolution Priority:**
1. Primary `papers_dir` (workspace-relative or absolute)
2. Additional paths from `paths` list (absolute or config-root-relative)

---

## 4. Multi-Path Local Source (Efficiency-Focused Design)

### Design Decision: Unified Index with Shared Cache

For **efficiency in speed and memory**, multiple local paths are managed as a **single unified source** with:
- One shared index covering all paths
- Single file hash cache across all paths
- Deduplication at candidate level
- Single-threaded sequential scan (avoids thread overhead)

### Architecture

```mermaid
graph TB
    subgraph "LocalSource (Multi-Path)"
        A[pdf_dirs: list[Path]] --> B[Unified Index Builder]
        B --> C[Shared Cache: dict[Path, str]]
        C --> D[Query Processor]
        D --> E[Deduplicator]
    end
    
    F[PaperQuery] --> D
    E --> G[Iterator[PaperCandidate]]
```

### Key Design Points

| Aspect | Approach | Benefit |
|--------|----------|---------|
| Index Storage | Single dict keyed by DOI/filename | O(1) lookup, unified cache |
| File Hashing | One MD5 per file, stored in shared dict | Avoids re-hashing on re-scan |
| Change Detection | Compare hash dict against filesystem | Minimal I/O on unchanged dirs |
| Search | Sequential scan with early exit | Memory efficient |
| Deduplication | By DOI first, then by filename | Consistent ordering |

### LocalSource API (Updated)

```python
@dataclass
class LocalSource:
    """Scan user's downloaded PDFs on filesystem (read-only).
    
    Now supports multiple paths with unified indexing.
    
    Attributes:
        pdf_dirs: List of root directories to scan
        recursive: Enable recursive scanning
    """
    
    pdf_dirs: list[Path]  # Changed from single pdf_dir
    recursive: bool = True
    
    # Cached state - unified across all paths
    _index: dict[str, Path] = field(default_factory=dict, init=False, repr=False)
    _file_hashes: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _path_sources: dict[Path, str] = field(default_factory=dict, init=False, repr=False)  # Track which path each file came from
```

### Breaking Change: Constructor Signature

**Old:**
```python
LocalSource(pdf_dir: Path)
```

**New:**
```python
LocalSource(pdf_dirs: list[Path])  # Accepts list, maintains backward compat via overload
```

---

## 5. Source Dispatcher (Updated)

### DefaultDispatcher (Updated for Multi-Path)

```python
class DefaultDispatcher:
    """Source dispatcher - updated for multi-path local sources."""
    
    def __init__(
        self,
        local_pdf_dirs: list[Path] | None = None,  # Changed from single path
        http_client=None,
    ):
        self._local_pdf_dirs = local_pdf_dirs or []
        self._http_client = http_client
        self._local_source: PaperSource | None = None
        # ... other sources
```

**Key Change:** Single `LocalSource` instance handles all paths, not multiple instances.

---

## 6. Context Injection (Improved)

### Current Pattern (to be improved)

```python
# In commands.py - BROKEN (method doesn't exist!)
def cmd_add(args, ctx: AppContext):
    local_pdf_dir = ctx.config.resolve_local_source_dir()  # ERROR!
```

### Improved Pattern

```python
# Option 1: Direct config access (recommended for clarity)
def cmd_add(args, ctx: AppContext):
    paths = ctx.config.resolve_local_source_paths()  # Returns list[Path]
    dispatcher = DefaultDispatcher(local_pdf_dirs=paths, http_client=ctx.http_client())

# Option 2: Context method (for repeated use)
@dataclass
class AppContext:
    # ... existing fields
    
    def source_dispatcher(self) -> DefaultDispatcher:
        """Get or create source dispatcher with multi-path support."""
        if self._dispatcher is None:
            paths = self.config.resolve_local_source_paths()
            self._dispatcher = DefaultDispatcher(
                local_pdf_dirs=paths,
                http_client=self.http_client()
            )
        return self._dispatcher
```

### Context Methods Summary

| Method | Purpose | Lazy? |
|--------|---------|-------|
| `http_client()` | HTTP requests | Yes |
| `llm_runner()` | LLM inference | Yes |
| `paper_store()` | Paper CRUD | Yes |
| `search_index()` | FTS search | No (context manager) |
| `vector_index()` | Vector search | No (context manager) |
| `paper_enricher()` | TOC/conclusion extraction | Yes |
| `source_dispatcher()` | Paper sources (NEW) | Yes |

---

## 7. Workflows

### Add Command Flow (Updated)

```mermaid
graph LR
    A[cmd_add] --> B[ctx.source_dispatcher]
    B --> C[LocalSource<br/>pdf_dirs=list[Path]]
    C --> D[Unified Index Builder]
    D --> E[Search All Paths]
    E --> F[Deduplicate Results]
    F --> G[Score & Rank]
    G --> H[Return Candidates]
```

### Multi-Path Index Building

```mermaid
graph TB
    A[pdf_dirs: list[Path]] --> B{For each path}
    B --> C[Glob *.pdf recursive]
    C --> D[Compute MD5 hash]
    D --> E[Update unified index]
    E --> F[Store path source]
    B --> G[Dedupe by DOI]
    G --> H[Final index]
```

---

## 8. CLI Commands

### Add Command (Updated)

```bash
# Search local PDFs from multiple paths
linkora add --doi 10.1234/example
linkora add --title "machine learning"
linkora add "quantum physics"  # Freeform

# Shows which sources are used
# Using 2 source(s)  # Now shows multi-path local source as 1
```

### Configuration Example

```yaml
# ~/.linkora/config.yaml
sources:
  local:
    enabled: true
    papers_dir: papers           # Workspace-relative
    paths:                      # Additional paths
      - /data/research/pdfs
      - ~/Dropbox/papers
      - ${LINKORA_EXTRA_PAPERS}  # Env var support
```

---

## 9. Breaking Changes Summary

| Change | Old | New | Impact |
|--------|-----|-----|--------|
| Config method | `resolve_local_source_dir()` (doesn't exist) | `resolve_local_source_paths()` | Fix broken code |
| LocalSource ctor | `LocalSource(pdf_dir: Path)` | `LocalSource(pdf_dirs: list[Path])` | API change |
| DefaultDispatcher | `local_pdf_dir: Path` | `local_pdf_dirs: list[Path]` | API change |
| Source count | Multiple local = N sources | Multiple local = 1 source | UI change |

---

## 10. Implementation Plan

### Phase 1: Fix Broken Code
- [ ] Add `resolve_local_source_dir()` as alias or fix commands.py to use `resolve_local_source_paths()`

### Phase 2: Update LocalSource
- [ ] Modify `LocalSource.__init__` to accept `pdf_dirs: list[Path]`
- [ ] Update `_build_index()` to scan all paths
- [ ] Add `_path_sources` tracking for source identification
- [ ] Update `_search_sequential()` and `_search_parallel()` for multi-path

### Phase 3: Update Dispatcher
- [ ] Modify `DefaultDispatcher.__init__` to accept `local_pdf_dirs: list[Path]`
- [ ] Create single `LocalSource` with all paths

### Phase 4: Update Context
- [ ] Add `source_dispatcher()` method to `AppContext`
- [ ] Update `cmd_add()` to use context method

### Phase 5: Documentation
- [ ] Update docs/design.md (this file)
- [ ] Add examples/config for multi-path

---

## 11. Environment Variables

| Variable | Description |
|----------|-------------|
| `linkora_WORKSPACE` | Active workspace name |
| `linkora_LLM_API_KEY` | LLM API key |
| `linkora_EXTRA_PAPERS` | Additional local PDF paths (NEW) |
| `DEEPSEEK_API_KEY` | DeepSeek API key (fallback) |
| `OPENAI_API_KEY` | OpenAI API key (fallback) |
| `MINERU_API_KEY` | MinerU cloud API key |
| `ZOTERO_API_KEY` | Zotero API key |
| `ZOTERO_LIBRARY_ID` | Zotero library ID |
