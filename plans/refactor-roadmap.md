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

---

## Completed Modules

### log.py ✅
- Class-based `LoggerManager` singleton with session tracking
- `HasLogConfig` Protocol for dependency injection

### papers.py ✅
- `PaperStore` dataclass with in-memory caching
- `YearRange` NamedTuple, Path helpers
- `Issue` dataclass for audit, `PaperFilter` with `apply()` method

### index.py ✅
- Class-based `SearchIndex` with context manager
- `SearchMode` factory, `FilterParams` dataclass (frozen)
- Removed legacy API - only SearchIndex class

### vectors.py ✅
- Class-based `VectorIndex` with encapsulated DB + FAISS
- `Embedder` Protocol for dependency injection
- `ModelStore` singleton for embedding model lifecycle

### loader.py ✅
- `StrategyRegistry` - Key-based pipeline resolution
- `PromptTemplate` - Immutable prompt data
- `ContentExtractor` - Pure functions
- `LLMRunner` - LLM execution with retry
- `PaperEnricher` - Class-based interface

### topics.py ✅
- `TopicConfig` - No paths, uses abstract Embedder
- `TopicInputData` - Input data structure
- `TopicModelOutput` - Immutable output with query/visualization methods
- `TopicTrainer` - Builder that returns immutable Output
- Import Embedder from vectors.py

---

## CLI Redesign (Functional Groups)

### Principle: Group by Functionality, Not by Command

Commands should be grouped by the library module they primarily use:

| CLI Command | Uses Library | Group |
|-------------|--------------|-------|
| search (all modes) | index.py, vectors.py | search.py |
| show (content + citations) | papers.py, index.py | show.py |
| enrich (toc, l3, abstract) | loader.py | enrich.py |
| index (fts, vector) | index.py, vectors.py | index.py |
| import (endnote, zotero) | sources/ | data.py |
| export (bibtex) | export.py | data.py |
| topics | topics.py | analysis.py |
| explore | explore.py, topics.py, vectors.py | analysis.py |
| audit | papers.py | system.py |
| setup | setup.py | system.py |
| metrics | metrics.py | system.py |

### Proposed CLI Module Structure

```
scholaraio/cli/
├── __init__.py        # Public API: run(), main()
├── args.py            # Shared argument parsers (filters, common flags)
├── output.py          # UI output abstraction
├── errors.py          # CLI exceptions
└── commands/
    ├── __init__.py    # CommandRegistry + common imports
    ├── search.py      # search --mode fts|author|vector|unified|cited
    ├── show.py        # show --layer 1-4 + --refs|--citing|--shared
    ├── enrich.py      # enrich --target toc|l3|abstract
    ├── index.py       # index --type fts|vector|all
    ├── data.py        # import --source, export --format
    ├── analysis.py    # topics, explore
    └── system.py      # audit --fix, setup, metrics
```

### Command Details

```bash
# Search Group (index.py, vectors.py)
scholaraio search "query" --mode fts|author|vector|unified|cited

# Show Group (papers.py, index.py)
scholaraio show <id> --layer 1-4 --refs --citing --shared

# Enrich Group (loader.py)
scholaraio enrich --target toc|l3|abstract [--dry-run]

# Index Group (index.py, vectors.py)
scholaraio index --type fts|vector|all [--rebuild]

# Data Group (sources/, export.py)
scholaraio import file.xml --source endnote|zotero [--dry-run]
scholaraio export --format bibtex [--all] [--year] [--journal]

# Analysis Group (topics.py, explore.py)
scholaraio topics --build|--viz|--topic N
scholaraio explore fetch|embed|topics|search|viz

# System Group
scholaraio audit [--fix]
scholaraio setup check|init
scholaraio metrics [--last N]
```

### Removed Commands

| Removed | Reason |
|---------|--------|
| workspace (ws) | Bad design - marked for removal |
| rename | One-off operation |
| migrate-dirs | One-off migration |
| attach-pdf | Redundant with import |

---

## Module Dependency Analysis

```
Layer 0: Foundation
├── config.py
├── log.py ✅
└── papers.py ✅

Layer 1: Core Data
├── loader.py ✅
├── index.py ✅
└── vectors.py ✅

Layer 2: Features
├── topics.py ✅
├── explore.py ⬜ (needs refactor)
└── workspace.py ⬜ (remove)

Layer 3: Pipeline
├── ingest/mineru.py ⬜ (keep as reference)
├── ingest/extractor.py ⬜ (keep as reference)
├── ingest/pipeline.py ⬜ (refactor: fix state leakage)
└── ingest/metadata/* ⬜ (DELETE - incompatible)

Layer 4: Entry Points
├── cli/           ⬜ (NEW - CLI redesign, 7 files)
├── mcp_server.py  ⬜ (TODO: redesign - broken imports)
├── setup.py
└── export.py
```

---

## Proceeding Plan

### Phase 1: CLI Redesign (Priority)

| Step | Task | Description |
|------|------|-------------|
| 1.1 | Create cli/ directory | Create directory + base files |
| 1.2 | Create command groups | 7 files: search, show, enrich, index, data, analysis, system |
| 1.3 | Migrate commands | Group by functionality |
| 1.4 | Update entry point | Update pyproject.toml |

**⚠️ TODO: Current cli.py and mcp_server.py have broken imports due to index.py refactor:**
- `get_references` - removed, use SearchIndex.references()
- `get_citing_papers` - removed, use SearchIndex.citing()
- `get_shared_references` - removed, use SearchIndex.shared_citations()
- `unified_search` - removed, implement new hybrid search
- `lookup_paper` - removed, use SearchIndex.lookup()

### Phase 2: Pipeline Cleanup

| Step | Task | Description |
|------|------|-------------|
| 2.1 | Explore.py refactor | Extract client, reuse vectors/topics |
| 2.2 | Remove workspace.py | Delete file, update imports |
| 2.3 | Pipeline state fix | Replace mutable context |

---

## Command Count Reduction

| Metric | Before | After |
|--------|--------|-------|
| Top-level commands | 25+ | **11** |
| CLI files | 1 (2500 lines) | **7 (~300 lines each)** |

---

## Checklist

| Status | Module | Task |
|--------|--------|------|
| ✅ Done | log.py | Protocol-based singleton |
| ✅ Done | papers.py | PaperStore + audit |
| ✅ Done | index.py | SearchIndex class |
| ✅ Done | loader.py | StrategyRegistry + PaperEnricher |
| ✅ Done | vectors.py | VectorIndex + ModelStore + Embedder Protocol |
| ✅ Done | topics.py | Separate trainer/output, remove paths |
| ✅ Done | cli/ | New modular CLI (10 commands) |
| ⬜ TODO | mcp_server.py | Redesign - broken imports from index.py refactor |
| ⬜ TODO | explore.py | Extract client, reuse vectors/topics |
| ⬜ TODO | workspace.py | Remove completely |
| ⬜ TODO | pipeline.py | Fix state leakage |

---

## Final Structure

```
scholaraio/
├── config.py       # Existing
├── log.py          # ✅ Refactored
├── papers.py       # ✅ Refactored
├── index.py        # ✅ Refactored
├── vectors.py      # ✅ Refactored
├── loader.py       # ✅ Refactored
├── topics.py       # ✅ Refactored
├── llm.py          # ✅ Created
├── extract.py      # ✅ Created
├── mineru.py      # ✅ Created
├── explore.py      # ⬜ Needs refactor
├── cli/
│   ├── __init__.py    # run(), main()
│   ├── args.py        # Shared parsers
│   ├── output.py      # Formatters
│   ├── errors.py      # Exceptions
│   └── commands/
│       ├── __init__.py
│       ├── search.py  # search (all modes)
│       ├── show.py    # show (content + citations)
│       ├── enrich.py  # enrich (toc, l3, abstract)
│       ├── index.py   # index (fts, vector)
│       ├── data.py    # import, export
│       ├── analysis.py # topics, explore
│       └── system.py  # audit, setup, metrics
├── mcp_server.py  # ⬜ Redesign
├── setup.py
└── export.py
```

