# linkora v2 - Architecture and Design

> Current architecture reference for contributors and coding agents.
> This document reflects the codebase as implemented now and supersedes most of `docs/design.md`.

---

## 1. Project Goals and Invariants

linkora is a local-first document corpus CLI.

Core goals:
- Keep user files in place (index metadata and search artifacts only).
- Support heterogeneous documents through schema-driven extraction and filtering.
- Keep orchestration explicit and composable (parse -> resolve -> fetch -> ingest style).

Non-negotiable invariants:
- `source_path` always references user-owned files; linkora does not maintain a managed paper copy store.
- Workspace is a DB namespace label, not a directory tree.
- One SQLite database is the primary state store.
- Network calls happen only for explicit remote sources (`doi`, `arxiv`, `web`) and configured LLM backends.

### 1.1 Breaking changes from `docs/design.md`

Major architecture shifts from the old v0.x design:
- `sources/` package is replaced by a unified `linkora/sources.py` module.
- Old `ingest/` package is replaced by `linkora/pipeline/` (`extract`, `enrich`, `ingest`).
- Schema/filter logic moved into `linkora/schema/registry.py` with composable stage APIs.
- Workspace is no longer represented as per-workspace directory trees; it is a DB namespace model.
- FAISS-centric design is replaced by LanceDB vector indexing in `linkora/index.py`.

---

## 2. Runtime Boundaries

linkora is organized around clear layer boundaries.

```
CLI command layer
  -> sources/files/pipeline orchestration
  -> store/index/workspace services
  -> db + vectors + cache persistence
```

### 2.1 Sources Boundary (`linkora/sources.py`)

Responsibilities:
- Parse source targets (`SourceRequest`).
- Resolve and execute source fetchers (`DocumentSource`).
- Return standardized `FetchResult` objects.
- Orchestrate add-flow ingestion through explicit stage outputs.

Non-responsibilities:
- No direct SQL.
- No schema internals.
- No file-hygiene operations (`tidy`, `dedup`, `watch`, `rescan`).

### 2.2 Pipeline Boundary (`linkora/pipeline/`)

Responsibilities:
- `extract.py`: text extraction via Kreuzberg.
- `enrich.py`: schema-aware LLM extraction/merge.
- `ingest.py`: path-in, record-out ingestion pipeline.

Non-responsibilities:
- No source parsing/dispatch logic.
- No CLI argument interpretation.

### 2.3 File Operations Boundary (`linkora/files.py`)

Responsibilities:
- Directory scans and ingestion (`files inbox`).
- Filename normalization (`files tidy`) using schema rendering pipeline.
- Dedup, rescan, and watch-related operations.

This layer may call pipeline ingest, but it does not own remote retrieval.

### 2.4 Schema Boundary (`linkora/schema/registry.py`, `linkora/schema/types.py`)

Responsibilities:
- Schema registry and doc-type resolution.
- Filename rendering pipeline.
- Schema-filter parse and match pipeline for search.

Design style:
- Data classes for stage payloads.
- Explicit pure-stage functions.
- No implicit `getattr` dispatch in public pipeline composition.

---

## 3. Composable Data Pipelines

The current codebase favors explicit stage transitions with typed payloads.

### 3.1 Source Ingest Pipeline

Implemented in `linkora/sources.py`:

1. Parse targets -> `ParsedTarget`
2. Resolve source from registry -> `ResolvedSource`
3. Fetch results -> `FetchOutcome`
4. Ingest fetched paths -> `IngestOutcome`
5. Map to CLI-facing `SourceIngestResult`

Core types:
- `SourceRequest`
- `FetchResult`
- `ParsedTarget`
- `ResolvedSource`
- `FetchOutcome`
- `IngestOutcome`
- `SourceIngestRequest`
- `SourceIngestResult`

Supported source schemes:
- `file`
- `local`
- `doi`
- `arxiv`
- `web`

### 3.2 Schema Resolution and Filtering Pipeline

Implemented in `linkora/schema/registry.py`:

1. Normalize/resolve type
   - `normalize_doc_type`
   - `resolve_doc_type`
   - `resolve_schema`
2. Parse documents into schema payloads
   - `parse_schema_documents`
3. Apply schema filters
   - `filter_schema_documents`

Core types:
- `SchemaRegistry`
- `ParsedSchemaDocument`
- `SearchFilter`

### 3.3 Filename Rendering Pipeline

Used by `files tidy`:

1. Build context from extracted fields (`build_filename_context`)
2. Optional custom template (`render_custom_filename`)
3. Fallback to schema template (`resolve_filename`)
4. Final normalization (`normalize_filename` in `files.py` flow)

Core types:
- `FilenameRenderRequest`
- `FilenameRenderOutcome`

---

## 4. Storage and Index Architecture

### 4.1 Persistent State

Primary DB: SQLite (`linkora.db`), managed by `linkora/db.py`.

Current tables include:
- `workspaces`
- `documents`
- `documents_fts` (FTS5 virtual table)
- `watched_dirs`
- `file_locations`
- `topics`
- `document_topics`
- `sessions`
- `workspace_profiles`

### 4.2 Stores

Implemented in `linkora/store.py`:
- `DocumentStore`
- `FileLocationStore`
- `TopicStore`

### 4.3 Search Indexes

Implemented in `linkora/index.py`:
- `SearchIndex` (SQLite FTS5 + fallback LIKE query)
- `VectorIndex` (LanceDB + sentence-transformers)
- `VectorStore` (vectors directory/table lifecycle)

Current status notes:
- FTS and vector run as parallel command modes (`fulltext` / `vector`).
- Hybrid fusion/reranking is not currently implemented in command flow.

---

## 5. Workspace Model

Implemented in `linkora/workspace.py`.

Workspace properties:
- Namespace metadata in DB: `id`, `name`, `description`, `created_at`, `is_default`.
- Not a filesystem workspace directory.

`WorkspaceStore` provides:
- create/delete/rename/list/default operations
- document store and index accessors
- watch registration/list/remove

Data root and canonical paths are provided via `linkora/paths.py`.

---

## 6. Configuration Model

Configuration is global and immutable-at-runtime (`AppConfig` in `linkora/config.py`).

Top-level sections:
- `sources`
- `index`
- `extract`
- `tidy`
- `llm`
- `topics`
- `log`

No workspace-local override exists.

Resolution model is single-file-wins:
- candidates are checked in deterministic order
- first existing file is active
- if multiple candidates exist, a warning is logged and lower-priority files are ignored
- if no file exists, built-in defaults are used

For full user-facing configuration details, see `docs/config.md`.

---

## 7. CLI Surface (Current)

Command registration is centralized in `linkora/cli/commands.py`.

Primary command groups:
- `add`
- `search`
- `index`
- `enrich`
- `files` (`tidy`, `dedup`, `rescan`, `inbox`, `watch ...`)
- `topics` (`build`, `list`, `show`, `assign`, `prune`, `export`)
- `config` (`show`, `set`)
- `doctor`
- `init`

Design guidance from `docs/AGENT.md`:
- CLI user-facing text should remain Chinese.
- Internal architecture code should favor explicit, typed, functional composition.

---

## 8. Module Map (Current)

```
linkora/
  __init__.py
  cli/
    __init__.py
    args.py
    commands.py
    errors.py
  config.py
  db.py
  files.py
  index.py
  log.py
  paths.py
  pipeline/
    __init__.py
    extract.py
    enrich.py
    ingest.py
  schema/
    __init__.py
    registry.py
    types.py
  setup.py
  sources.py
  store.py
  topics.py
  workspace.py
```

---

## 9. Dependency Profile

From `pyproject.toml`:

Core:
- `httpx`
- `pyyaml`
- `pydantic`
- `tenacity`
- `litellm`
- `kreuzberg[pdf]`

Optional groups:
- `extract`, `extract-ocr`
- `embed`
- `topics`
- `full`, `full-ocr`

Build/test tooling uses `uv` workflows as described in `docs/AGENT.md`.

---

## 10. Document Authority

`docs/design-v2.md` is the single architecture authority for active development.

Historical v0.x architecture notes have been removed from the main docs tree.
