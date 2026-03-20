# linkora

> **Local Knowledge Network** — AI-native research terminal powered by local-first architecture.

[English](./README.md) | [中文](./README-CN.md)

---

## Motive

Research is fragmented. Papers live in multiple folders, search is scattered across tools, and context is lost between sessions. **linkora** solves this by building a **local knowledge network** that:

- Stores all data locally (privacy, offline capability)
- Provides layered access (L1 metadata → L4 full text)
- Enables semantic search with embeddings
- Works seamlessly with AI coding agents

**Target Audience**: AI coding agents (Claude, Cursor) and researchers who want CLI-driven workflows.

## Features

| | | | |
|---|---|---|---|
| **Layered Reading** | L1 metadata → L2 abstract → L3 sections → L4 full text — read at the depth you need |
| **Hybrid Search** | FTS5 keyword + Qwen3 semantic → RRF fusion ranking |
| **Multi-Source Import** | Local PDFs, OpenAlex API, Zotero, EndNote XML/RIS |
| **Workspaces** | Multiple research projects with isolated search and data |
| **MCP Server** | Full toolset for Claude Desktop, Cursor, and any MCP client |

## Installation

### Prerequisites

- **uv** (required): [Install via astral.sh](https://astral.sh/uv/install)
- **Python 3.12+**

### Quick Install

```bash
uv tool install "linkora[full]"
```

### From Source

```bash
git clone https://github.com/your-repo/linkora.git
cd linkora
uv sync
```

## Quick Start

```bash
# Show design context for AI agents
linkora --context

# Interactive setup
linkora init

# Add papers (place PDFs in workspace)
linkora add /path/to/paper.pdf

# Build search index
linkora index

# Search papers
linkora search "machine learning"
linkora search "turbulence" --mode vector

# MCP server
linkora-mcp
```

## Configuration

linkora **requires explicit configuration** — it is NOT a zero-config tool. See [config.md](./docs/config.md) for full details.

### Config File Locations

linkora looks for config in (highest priority first):

| Location | Platform |
|----------|----------|
| `~/.linkora/config.yml` | All |
| `~/.config/linkora/config.yml` | All |

If no config file is found, built-in defaults are used.

### Quick Setup

```yaml
# ~/.linkora/config.yml
sources:
  local:
    enabled: true
    papers_dir: papers

llm:
  backend: openai-compat
  model: deepseek-chat
  base_url: https://api.deepseek.com
```

See [`examples/config/full.yml`](examples/config/full.yml) for complete configuration.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `LINKORA_ROOT` | Root directory for all workspaces |
| `LINKORA_WORKSPACE` | Active workspace name |
| `LINKORA_LLM_API_KEY` | LLM API key (fallback: `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`) |
| `MINERU_API_KEY` | PDF parsing API key (MinerU) |
| `ZOTERO_API_KEY` | Zotero API key |
| `ZOTERO_LIBRARY_ID` | Zotero library ID |
| `OPENALEX_API_KEY` | OpenAlex API key |

---

## Workspace Concept

A **workspace** is a self-contained research environment with its own:
- Papers directory
- Full-text search index (FTS5)
- Vector search index (FAISS)
- Metadata

Workspaces are managed via CLI commands:

```bash
# Show current workspace info
linkora config show

# List all workspaces
linkora config show --all

# Set default workspace
linkora config set-default ml

# Set workspace description
linkora config set-meta description "Machine learning papers"

# Migrate/rename workspace
linkora config mv old-name new-name
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| **Search** | |
| `linkora search <query>` | Search papers (default: FTS5 fulltext) |
| `linkora search <query> --mode fulltext` | Full-text search using FTS5 |
| `linkora search <query> --mode author` | Search by author name |
| `linkora search <query> --mode vector` | Semantic vector search (FAISS) |
| `linkora search <query> --mode hybrid` | Combined FTS + vector search |
| `linkora top-cited` | Get top-cited papers |
| **Index** | |
| `linkora index` | Build/update FTS5 index |
| `linkora index --type fts` | Build FTS5 full-text index |
| `linkora index --type vector` | Build vector index (FAISS) |
| `linkora index --rebuild` | Rebuild index from scratch |
| **Paper Management** | |
| `linkora add --doi <doi>` | Add paper by DOI |
| `linkora add --title <title>` | Add paper by title search |
| `linkora add "<query>"` | Add papers by free-form query |
| `linkora enrich` | Enrich papers with TOC and conclusions |
| **Workspace** | |
| `linkora config show` | Show workspace configuration |
| `linkora config show --all` | List all workspaces |
| `linkora config set <field> <value>` | Set config value |
| `linkora config set-meta <field> <value>` | Set workspace metadata |
| `linkora config set-default <workspace>` | Set default workspace |
| `linkora config mv <source> <target>` | Migrate workspace |
| **System** | |
| `linkora init` | Interactive setup wizard |
| `linkora audit` | Data quality audit |
| `linkora doctor` | Full health check (with network) |
| `linkora doctor --light` | Quick health check (no network) |
| `linkora metrics` | Show LLM metrics |
| `linkora --context` | Show design context for AI agents |

---

## Architecture

See [`docs/design.md`](docs/design.md) for detailed architecture.

## Development

Please refer to [`docs/AGENT.md`](docs/AGENT.md) for development guidelines.

linkora uses [just](https://github.com/casey/just) for development workflows. However, it's **optional** for convenience.

Install just first, then use the commands below.

```bash
# Show all available commands
just

# Common commands
just setup        # Create venv and sync dependencies
just test         # Run tests
just lint         # Check linting
just ty           # Type checking
just quality      # All quality checks
just ci           # Full CI pipeline
```

### Manual Setup

```bash
uv venv
uv sync

# Run tests
uv run pytest tests/ -v

# Lint
uv run ruff check .
uv run ruff format .

# Type check
uv run ty check
```

## License

[MIT](LICENSE) © 2026
