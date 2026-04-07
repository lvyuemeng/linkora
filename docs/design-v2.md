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

Separation direction (in progress):
- Core modules must not depend on CLI argument/context objects.
- Filesystem path resolution for runtime roots/config candidates is owned by CLI bootstrap layer.
- Core services receive explicit dependencies (store/config/path/cache) from orchestration boundaries.

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

### 2.5 CLI Bootstrap Boundary (`linkora/cli/setup.py`)

Responsibilities:
- Runtime bootstrap (`run_init`) and process singletons used by CLI execution.
- Global config candidate resolution/load and config write helpers.
- Doctor diagnostics for env/path/config visibility.
- Runtime path ownership (`data_root`, `db`, `cache`, `vectors`) for CLI workflows.

Non-responsibilities:
- No schema parsing logic.
- No DB query/domain workflow implementation.
- No document enrichment/index algorithms.

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

Data root and canonical runtime paths are owned by `linkora/cli/setup.py`.

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

Runtime bootstrap note:
- No explicit `init` command is required for normal usage.
- First run auto-initializes database and default workspace.
- Config file remains optional; defaults are loaded when absent.

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
    setup.py
  config.py
  db.py
  files.py
  index.py
  log.py
  pipeline/
    __init__.py
    extract.py
    enrich.py
    ingest.py
  schema/
    __init__.py
    registry.py
    types.py
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

---

## 11. Core/CLI Separation Proposal

This is the target package split for the two-crate layout (`linkora-core` + `linkora-cli`).

### 11.1 Ownership Rules

- `linkora-core` owns domain logic: `schema`, `pipeline`, `store`, `db`, `workspace`, `index`, `topics`, `sources`, `files`.
- `linkora-cli` owns user interaction and runtime environment: arg parsing, command dispatch, runtime path/config/bootstrap, doctor/config mutation.
- Core modules must expose explicit inputs and outputs (no hidden dependency on CLI context).
- CLI can import core; core must not import CLI.
- Do not add a separate `application` package/layer inside core; keep orchestration in existing module boundaries and CLI command wiring.

### 11.2 Dependency Injection Contract

To keep crates orthogonal, core entry points should accept concrete dependencies from callers:

- Ingest paths should receive `DocumentStore` (or protocol) explicitly.
- Enrichment should receive resolved `AppConfig` (or an extracted LLM settings object) explicitly.
- Extraction cache and vector store roots should be passed from orchestrators instead of resolved globally inside core.
- Topic model storage should be path-explicit (`TopicModelStore(model_dir=...)`) and not derive from CLI runtime context.

### 11.3 External Filesystem Policy

- CLI layer owns top-level machine paths (`LINKORA_ROOT`, config candidate files, default data root layout).
- Core may perform file IO only for domain artifacts already passed to it (input docs, cache dir, vectors dir, topic model dir, exports).
- Core must not decide platform-specific root locations by itself.

### 11.4 Migration Steps

1. Keep `linkora/cli/setup.py` as the only runtime path/bootstrap module.
2. Remove implicit global fallbacks from core APIs and require explicit constructor/request dependencies.
3. Introduce package directories (`packages/linkora-core`, `packages/linkora-cli`) and move modules without changing public command behavior.
4. Keep lockstep release versions initially; publish core first, then CLI pinned to matching core version.

### 11.5 Package Naming and Install Surface

- Publish the CLI distribution under package name `linkora` (user install command remains `pip/uv install linkora`).
- Publish the domain library under package name `linkora-core`.
- `linkora` depends on `linkora-core` and exposes the `linkora` console script.
- `linkora-core` exposes importable Python APIs only, with no console entrypoint.

---

## 12. Publish and Version Plan (Two-Crate)

### 12.1 Release Artifacts

- `linkora-core`:
  - wheel + sdist
  - import namespace for core runtime/domain modules
- `linkora` (CLI):
  - wheel + sdist
  - dependency: `linkora-core==<same version>` during stabilization phase
  - console entrypoint: `linkora = linkora.cli:main`

### 12.2 Publish Workflow

Single-tag, two-package release workflow:

1. Create one release version `X.Y.Z`.
2. Run workspace validation (`ruff`, `pytest`, package build checks) for both crates.
3. Build and publish `linkora-core` first.
4. Verify `linkora-core==X.Y.Z` is available from index.
5. Build and publish `linkora` with dependency pinned to `linkora-core==X.Y.Z`.
6. Run smoke test in clean env:
   - `uvx --from linkora linkora --help`
   - `python -c "import linkora_core"` (or mapped module import in final package layout)

Failure policy:
- If core publish succeeds and CLI publish fails, do not republish core with new version immediately.
- Fix CLI and publish `linkora` using the same `X.Y.Z` when possible; otherwise bump both to `X.Y.(Z+1)`.

### 12.3 Version Management Policy

Version source of truth:
- Use one canonical version value in repository automation (release script / tag-driven version).
- Apply the same version to both crates at release time.

Compatibility policy:
- Phase 1 (stabilization): strict lockstep dependency (`linkora` -> `linkora-core==X.Y.Z`).
- Phase 2 (after API stability): relax to compatible range (`linkora-core>=X.Y,<X.(Y+1)`) only when core API compatibility is guaranteed and tested.

SemVer interpretation:
- MAJOR: breaking changes in core API or CLI command behavior.
- MINOR: backward-compatible features in either crate.
- PATCH: bug fixes, docs, and internal non-breaking refactors.

### 12.4 CI/CD Gates

- PR gate:
  - run tests/lint for changed crate(s)
  - run contract tests for CLI-core integration
- Release gate:
  - ensure both crates carry identical release version
  - ensure CLI dependency points to target core version
  - block publish if integration smoke test fails

---

## 13. Test Strategy and Module Migration Plan

This section defines how to validate separation and how to migrate modules into
`linkora-core` and `linkora` (CLI package) safely.

### 13.1 Test Layers for Separation

1. Core unit tests (`linkora-core`)
   - Scope: pure/domain logic with explicit dependencies.
   - Must not import `linkora.cli.*`.
   - Examples: schema parsing/filtering, ingest pipeline behavior with injected stores,
     topic assignment/pruning, search query composition.

2. CLI unit tests (`linkora`)
   - Scope: argument parsing, command registration, context bootstrap wiring,
     message formatting contracts.
   - Replace heavy core calls with stubs/mocks where possible.

3. Contract tests (CLI <-> Core)
   - Validate CLI request mapping into core request objects.
   - Ensure required injected dependencies are present (store/config/path/cache).
   - Protect against accidental reintroduction of global runtime lookups in core.

4. Packaging checks (lean mode)
   - Build both packages with `uv build --project ...`.
   - Run metadata sanity checks and dependency pin checks via `release_sync verify`.
   - Keep local wheel install tests optional (only for release hardening/debugging).

5. Release smoke tests
   - Fresh environment install from index:
     - `uvx --from linkora linkora --help`
     - lightweight command path (e.g. `linkora --context`)
   - Verify no missing module errors from split boundaries.

### 13.2 Required Gate Checks

PR gates (mandatory):
- `uv run ruff check .`
- `uv run -m pytest`
- `uv run python scripts/release_sync.py verify`
- architecture guard: fail if any core module imports `linkora.cli`.

Release gates (mandatory):
- build both crates from `packages/linkora-core` and `packages/linkora`
- verify lockstep version and dependency pin consistency
- publish with `uv publish` in staged order (core -> cli)

### 13.3 Module Split Map (Target)

`linkora-core` target ownership:
- `linkora/config.py`
- `linkora/db.py`
- `linkora/store.py`
- `linkora/workspace.py`
- `linkora/schema/*`
- `linkora/pipeline/*`
- `linkora/index.py`
- `linkora/sources.py`
- `linkora/files.py`
- `linkora/topics.py`
- `linkora/log.py` (shared logging utilities used by core flows)

`linkora` (CLI) target ownership:
- `linkora/cli/__init__.py`
- `linkora/cli/args.py`
- `linkora/cli/commands.py`
- `linkora/cli/errors.py`
- `linkora/cli/setup.py`

Shared package namespace note:
- During migration, both distributions may contribute modules under `linkora.*`.
- Import direction remains strict: CLI can import core; core cannot import CLI.

### 13.4 Migration Phases

Phase A - Boundary hardening (now):
- Remove implicit core global runtime/path lookups.
- Make core APIs dependency-explicit.
- Keep test suite green.

Phase B - Package extraction:
- Keep source tree stable; publish from `packages/linkora-core` and `packages/linkora`.
- Add package-specific test jobs while preserving full-repo integration tests.

Phase C - Contract stabilization:
- Freeze minimal core API surface used by CLI.
- Add compatibility tests for CLI against pinned core version.

Phase D - Post-stabilization improvements:
- Consider relaxing strict `==` core pin to compatible range.
- Keep lockstep if release cadence or compatibility risk remains high.

---

## 14. GitHub Workflow Refactor Plan

Current workflow files:
- `.github/workflows/ci.yml`
- `.github/workflows/publish.yml`

The current setup is still single-package oriented. The refactor target is a two-crate
pipeline (`linkora-core` + `linkora`) with explicit version-sync and staged publishing.

### 14.1 Target Workflow Topology

Proposed workflow split:

1. `ci.yml` (PR + push validation)
   - lint/type/tests (existing)
   - add `release_sync verify`
   - add architecture guard (core must not import `linkora.cli`)
   - add package build checks for both crates:
     - `uv build --project packages/linkora-core`
     - `uv build --project packages/linkora`

2. `package-smoke.yml` (optional, keep disabled by default)
   - used only when release hardening is needed
   - local artifact install/runtime checks

3. `publish.yml` (tag-based release)
   - single tag `vX.Y.Z`
   - publish order:
     1) `linkora-core`
     2) wait/verify index availability
     3) `linkora` (CLI)
   - run post-publish smoke (`uvx --from linkora linkora --help`)

### 14.2 CI Job Graph (Proposed)

Within `ci.yml`:

- `lint_type`:
  - `uv sync --extra full`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run ty check`

- `verify_release_sync` (depends on `lint_type`):
  - `uv run python scripts/release_sync.py verify`

- `tests_matrix` (depends on `lint_type`):
  - keep current OS/Python matrix pytest runs

- `build_packages` (depends on `verify_release_sync`):
  - build both package projects
  - no artifact install in normal CI path

### 14.3 Publish Job Graph (Proposed)

Within `publish.yml`:

- `preflight`:
  - checkout
  - `release_sync verify`
  - ensure tag version matches repository version source

- `publish_core` (needs `preflight`):
  - build `packages/linkora-core`
  - publish to target index

- `verify_core_available` (needs `publish_core`):
  - short availability check before CLI publish

- `publish_cli` (needs `verify_core_available`):
  - build `packages/linkora`
  - publish to target index

- `post_publish_smoke` (needs `publish_cli`):
  - minimal runtime check only:
    - `uvx --from linkora linkora --help`

### 14.4 Environment and Permissions

- Keep `contents: read` as default workflow permission.
- Use environment-scoped publish secrets and optional approval gates for production PyPI.
- Keep TestPyPI publish as separate branch/tag policy or manual dispatch to avoid accidental dual publish on every tag.

### 14.5 Migration Steps for Workflows

1. Update `ci.yml` first (add verify/build jobs only; no install-smoke job).
2. Refactor `publish.yml` from matrix publish to staged core-then-cli publish via `uv publish`.
3. Keep smoke as one post-publish `uvx --from linkora linkora --help` command.
4. Keep optional artifact-install smoke workflow out of default path to preserve simplicity.
