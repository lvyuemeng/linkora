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

### Key Patterns

1. **Protocol for Dependencies** - Each module defines its Protocol
2. **Dataclass for Configuration** - Pass Config objects, not individual params
3. **Lazy Loading** - Use PaperData pattern for expensive operations
4. **Pipe-style Functions** - Compose operations, avoid stateful classes
5. **Data/Execution Separation** - Separate prompt templates from LLM calls
6. **Key-based Dispatch** - StrategyRegistry resolves entire pipeline by identifier

---

## Completed Modules

### log.py ✅
- Class-based `LoggerManager` singleton with session tracking
- `HasLogConfig` Protocol for dependency injection
- Explicit level mapping (no getattr)

### papers.py ✅
- `PaperStore` dataclass with in-memory caching
- `YearRange` NamedTuple
- Path helpers
- `Issue` dataclass for audit
- `audit()` with pluggable rules
- `PaperFilter` with `apply()` method
- DEPRECATED: `iter_paper_dirs()`, `read_meta()` - use PaperStore instead

### index.py ✅
- Class-based `SearchIndex`
- `SearchMode` factory, `FilterParams` dataclass
- Unified `_index_paper()` for rebuild/update
- Context manager support

### loader.py ✅
- `StrategyRegistry` - Key-based pipeline resolution
- `PromptTemplate` - Immutable prompt data
- `ContentExtractor` - Pure functions
- `LLMRunner` - LLM execution with retry
- `PaperEnricher` - Class-based interface
- Updated CLI, MCP server, pipeline callers

### vectors.py ✅
- Class-based `VectorIndex` with encapsulated DB + FAISS
- `Embedder` Protocol for dependency injection
- `ModelStore` singleton for embedding model lifecycle
- Unified `rebuild()` / `update()` pattern
- `VectorFilterParams` dataclass
- Uses `PaperStore` internally (no deprecated functions)
- Data/side-effect separation

---

## Pending Modules

_No pending modules at Layer 1._

---

## Layer 2: Feature Modules (Future)

### topics.py
- Depends on vectors.py
- BERTopic topic modeling
- Needs Protocol for embedding dependency

### explore.py
- Journal-wide exploration
- OpenAlex API + FAISS + BERTopic
- Should reuse VectorIndex

### workspace.py
- Workspace paper subset management
- Should reuse PaperStore

---

## Checklist

| Status | Module | Task |
|--------|--------|------|
| ✅ Done | log.py | Protocol-based singleton |
| ✅ Done | papers.py | PaperStore + audit |
| ✅ Done | index.py | SearchIndex class |
| ✅ Done | loader.py | StrategyRegistry + PaperEnricher |
| ✅ Done | vectors.py | VectorIndex class + Embedder Protocol |
| ⬜ Pending | topics.py | Protocol for embedding |
| ⬜ Pending | explore.py | Reuse VectorIndex |
| ⬜ Pending | workspace.py | Reuse PaperStore |

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

Layer 2: Features (depends on Layer 1)
├── topics.py
├── explore.py
└── workspace.py

Layer 3: Pipeline
├── ingest/mineru.py
├── ingest/extractor.py
├── ingest/pipeline.py
└── ingest/metadata/*

Layer 4: Entry Points
├── cli.py
├── mcp_server.py
├── setup.py
└── export.py
```
