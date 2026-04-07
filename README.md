# linkora

Local-first knowledge CLI for people and AI agents who need fast, reliable retrieval from real files.

[English](./README.md) | [中文](./README-CN.md)

---

## Introduction

linkora turns your existing documents into a searchable knowledge layer without forcing you into a cloud migration or a heavyweight UI. It keeps the workflow close to your terminal, close to your files, and fully auditable.

Think of it as a practical bridge between raw documents and intelligent workflows:

- Your files stay where they are. linkora stores references, not duplicated blobs.
- AI agents get deterministic, structured context instead of brittle ad-hoc prompts.
- Research and engineering teams get one reproducible pipeline from ingest to retrieval.

Design reference: [`docs/design-v2.md`](docs/design-v2.md)

## Why it matters

- **Local-first by default**: data paths are explicit, inspectable, and easy to back up.
- **Built for mixed sources**: local files/directories, DOI, arXiv, and web URLs in one flow.
- **Hybrid retrieval that feels immediate**: keyword precision (FTS5) plus semantic recall (vectors).
- **Workspace isolation**: separate corpora cleanly for projects, teams, or experiments.
- **Agent-ready context**: `linkora --context` exposes operational guidance for deterministic automation.

---

## Install

Requirements:

- Python 3.12+
- `uv`

Install `uv`:

```bash
pip install uv
```

Install linkora with full optional capabilities:

```bash
uv tool install "linkora[full]"
```

Check installation:

```bash
linkora --help
```

### Development install (from source)

```bash
git clone https://github.com/lvyuemeng/linkora.git
cd linkora
uv sync
uv run linkora --help
```

---

## Basic usage

A minimal end-to-end flow:

```bash
# 1) Show runtime context (great for humans and agents)
linkora --context

# 2) Optional health checks (config/env/path)
linkora doctor

# 3) Add documents into a workspace
linkora add ./docs/paper.pdf --workspace default
linkora add doi:10.48550/arXiv.1706.03762 --output ~/Downloads --workspace default

# 4) Build retrieval indexes
linkora index

# 5) Search (keyword and vector)
linkora search "transformer"
linkora search "embedding alignment" --mode vector
```

Workspace priority: CLI `--workspace` > `LINKORA_WORKSPACE` > registry default.

---

## Configuration

Configuration is optional. If no config file is found, linkora runs with built-in defaults.

- Single-file-wins resolution
- Warning when multiple config candidates are present
- Global config only (no workspace-local override)

Guide: [`docs/config.md`](docs/config.md)

```bash
linkora config show
linkora config show llm.model
linkora config set llm.model deepseek-chat
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

Use `linkora <command> --help` for details.

---

## Data layout

Under data root (`LINKORA_ROOT` can override):

```text
<data_root>/
  linkora.db
  vectors/
  cache/
  linkora.log
```

---

## Development

```bash
uv run ruff format .
uv run ruff check .
uv run ty check .
uv run -m pytest
```

Contribution guide: [`docs/AGENT.md`](docs/AGENT.md)

## License

[MIT](LICENSE)
