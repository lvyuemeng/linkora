# linkora

Local-first knowledge CLI for both humans and AI agents.

[English](./README.md) | [中文](./README-CN.md)

---

## What it does

linkora builds a local knowledge layer on top of your existing files and sources.
It can be used directly by users in terminal workflows and by AI agents that need a
structured, searchable context store.

- Keep files in place: linkora stores references (`source_path`), not duplicated documents.
- Ingest from mixed sources: local files/directories, DOI, arXiv, and web URLs.
- Extract + enrich: parse content, apply schema fields, optionally enrich with LLM.
- Search in two ways: FTS5 full-text and LanceDB vector retrieval.
- Operate by workspace: each workspace is a DB namespace for isolation.

Design reference: [`docs/design-v2.md`](docs/design-v2.md)

## Who it is for

- Users: build a personal or team research corpus and search it quickly.
- AI agents: consume `linkora --context`, then run deterministic add/index/search flows.
- Engineering workflows: keep everything local-first with explicit data paths.

---

## Features

- Multi-source ingest: `add` local files/dirs, DOI IDs, arXiv IDs, and URLs.
- Structured enrichment: schema-aware metadata extraction with optional LLM enhancement.
- Hybrid retrieval: full-text (`fulltext`) and semantic vector (`vector`) search.
- File operations: tidy, dedup, rescan, inbox import, and directory watch.
- Topic workflows: build, inspect, assign, prune, and export topic clusters.
- Local-first runtime: single SQLite DB + local vector/cache directories.

---

## Install

Prerequisites:
- Python 3.12+
- `uv`

From source:

```bash
git clone https://github.com/lvyuemeng/linkora.git
cd linkora
uv sync
```

CLI check:

```bash
uv run linkora --help
```

---

## How to use

Typical flow:
1. Inspect environment and defaults.
2. Add content into a workspace.
3. Build index and search.

```bash
# AI/agent context snapshot
uv run linkora --context

# optional diagnostics (config/env)
uv run linkora doctor

# ingest local files
uv run linkora add ./docs/paper.pdf --workspace default

# ingest by source
uv run linkora add doi:10.48550/arXiv.1706.03762 --output ~/Downloads --workspace default
uv run linkora add arxiv:2401.01234 --output ~/Downloads --workspace default
uv run linkora add web:https://example.com/post --output ~/Downloads --workspace default

# build indexes
uv run linkora index

# search
uv run linkora search "transformer"
uv run linkora search "embedding" --mode vector
```

Workspace selection priority is: CLI flag `--workspace` > `LINKORA_WORKSPACE` > registry default.

---

## Configuration

Config is optional. If no config file exists, linkora uses built-in defaults.

Config model:
- single-file-wins resolution
- warning if multiple config candidates exist
- global config only (no workspace-local override)

See full guide: [`docs/config.md`](docs/config.md)

Common commands:

```bash
uv run linkora config show
uv run linkora config show llm.model
uv run linkora config set llm.model deepseek-chat
```

---

## Command overview

- ingest: `add`
- search: `search`
- indexing: `index`
- enrichment: `enrich`
- file operations: `files ...`
- topics: `topics ...`
- config: `config show/set`
- diagnostics: `doctor`

Run `uv run linkora <command> --help` for detailed usage.

---

## Data layout

Under data root (`LINKORA_ROOT` override supported):

```text
<data_root>/
  linkora.db
  vectors/
  cache/
  linkora.log
```

---

## Development

Use `uv` workflows only.

```bash
uv run ruff format .
uv run ruff check .
uv run ty check
uv run -m pytest
```

### Contribution notes (separation)

- CLI/runtime bootstrap is in `linkora/cli/setup.py`.
- Core modules must not depend on `linkora.cli.*`.
- Keep core dependencies explicit (store/config/path/cache should be injected from orchestration boundaries).
- Do not introduce a separate `application` layer inside core; orchestration remains in existing module boundaries.

Version and release sync helpers:

```bash
just release-show
just release-verify
just release-bump 0.4.0
```

Contributor guidance: [`docs/AGENT.md`](docs/AGENT.md)
Architecture and migration reference: [`docs/design-v2.md`](docs/design-v2.md)

Optional `just` shortcuts (`justfile`):

```bash
just setup
just format
just lint
just type
just test
just ci
```

---

## License

[MIT](LICENSE)
