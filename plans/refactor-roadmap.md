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

| Module | Status | Key Changes |
|--------|--------|-------------|
| log.py | ✅ | LoggerManager singleton, HasLogConfig Protocol |
| papers.py | ✅ | PaperStore dataclass, YearRange, Issue, PaperFilter |
| index.py | ✅ | SearchIndex class, SearchMode factory, FilterParams |
| vectors.py | ✅ | VectorIndex class, Embedder Protocol, ModelStore |
| loader.py | ✅ | StrategyRegistry, PromptTemplate, PaperEnricher |
| topics.py | ✅ | TopicConfig, TopicTrainer, TopicModelOutput |
| cli/ | ✅ | 10 commands in 5 files (~300 lines total) |
| llm.py | ✅ | LLM client abstraction |
| extract.py | ✅ | Extraction utilities |
| mineru.py | ✅ | MinerU client |

---

## CLI Design

### New Structure

```
scholaraio/cli/
├── __init__.py    # Entry point: main(), run()
├── args.py        # Shared argument parsers
├── output.py      # UI output formatting
├── errors.py      # CLI exceptions
└── commands.py    # All command handlers
```

### Commands (10 total)

| Command | Description |
|--------|-------------|
| search | FTS5 full-text search |
| search-author | Author name search |
| vsearch | Vector semantic search |
| usearch | Hybrid search |
| top-cited | Top cited papers |
| index | Build FTS5 index |
| embed | Build vector index |
| audit | Data quality audit |
| setup | Setup wizard |
| metrics | LLM usage metrics |

### Removed Commands

| Command | Reason |
|---------|--------|
| workspace (ws) | Bad design |
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
└── workspace.py ✅ (removed)

Layer 3: Pipeline
├── ingest/mineru.py ⬜
├── ingest/extractor.py ⬜
├── ingest/pipeline.py ⬜ (fix state leakage)
└── ingest/metadata/* ⬜ (to be deleted)

Layer 4: Entry Points
├── cli/           ✅ (NEW)
├── mcp_server.py  ⬜ (TODO: redesign)
├── setup.py
└── export.py
```

---

## Remaining Tasks

### Phase 2: Pipeline Cleanup

| Task | Description |
|------|-------------|
| Explore.py refactor | Extract client, reuse vectors/topics |
| Pipeline state fix | Replace mutable context |
| Delete ingest/metadata/* | Incompatible with new design |

### Phase 3: Entry Points

| Task | Description |
|------|-------------|
| mcp_server.py redesign | Update to use new class-based APIs |

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
| ⬜ TODO | explore.py | Extract client, reuse vectors/topics |
| ⬜ TODO | pipeline.py | Fix state leakage |
| ⬜ TODO | mcp_server.py | Redesign to use new APIs |
| ⬜ TODO | ingest/metadata/* | Delete incompatible modules |

---

## Final Structure

```
scholaraio/
├── config.py       # Config loading
├── log.py          # ✅ LoggerManager singleton
├── papers.py       # ✅ PaperStore + audit
├── index.py        # ✅ SearchIndex class
├── vectors.py      # ✅ VectorIndex + Embedder Protocol
├── loader.py       # ✅ PaperEnricher
├── topics.py       # ✅ TopicTrainer
├── llm.py          # ✅ LLM client
├── extract.py      # ✅ Extraction utilities
├── mineru.py       # ✅ MinerU client
├── explore.py      # ⬜ Needs refactor
├── cli/
│   ├── __init__.py    # ✅ run(), main()
│   ├── args.py        # ✅ Shared parsers
│   ├── output.py      # ✅ Formatters
│   ├── errors.py      # ✅ Exceptions
│   └── commands.py    # ✅ All commands
├── cli_legacy.py   # Old CLI (reference)
├── mcp_server.py   # ⬜ TODO: redesign
├── setup.py
└── export.py
```
