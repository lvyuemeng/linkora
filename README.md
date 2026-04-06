# linkora

Local-first document corpus CLI for AI-assisted workflows.

[English](./README.md) | [中文](./README-CN.md)

---

## What linkora is

linkora indexes documents where they already live, enriches metadata by schema,
and supports full-text plus vector search.

Architecture principles:
- user files stay in place (`source_path` references original files)
- workspace is a DB namespace (not a workspace folder tree)
- explicit composable pipelines (source -> fetch -> ingest, schema -> parse -> filter)

Authoritative design document: [`docs/design-v2.md`](docs/design-v2.md)

---

## Key capabilities

- Source ingest:
  - local file/dir
  - `doi:<id>`
  - `arxiv:<id>`
  - `web:<url>`
- Pipeline ingest:
  - extract text (Kreuzberg)
  - enrich metadata (schema + LLM)
  - persist to SQLite
- Search:
  - `fulltext` mode (FTS5)
  - `vector` mode (LanceDB)
- File workflows:
  - `files tidy`, `files dedup`, `files rescan`, `files inbox`, `files watch`
- Topics workflows:
  - `topics build`, `list`, `show`, `assign`, `prune`, `export`

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

## Quick start

```bash
# AI/agent context snapshot
uv run linkora --context

# initialize config + environment
uv run linkora init

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

Contributor guidance: [`docs/AGENT.md`](docs/AGENT.md)

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
