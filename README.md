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

| | |
|---|---|
| **Layered Reading** | L1 metadata → L2 abstract → L3 sections → L4 full text — read at the depth you need |
| **Hybrid Search** | FTS5 keyword + Qwen3 semantic → RRF fusion ranking |
| **Multi-Source Import** | Local PDFs, OpenAlex API, Zotero, EndNote XML/RIS |
| **Workspaces** | Multiple research projects with isolated search and BibTeX export |
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

linkora **is NOT a zero-config tool** — it requires explicit configuration. See [config.md](./docs/config.md) for full details.

### Quick Setup

```yaml
# ~/.linkora/config.yml
default_workspace: research

workspace:
  research:
    description: "Main research workspace"

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

### Workspace Concept

Workspaces provide isolated research environments:

```
~/.linkora/config.yml           # Global config
~/.config/linkora/config.yml   # XDG config location
<workspace>/linkora.yml        # Workspace-local override
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `linkora_ROOT` | Root directory for all workspaces |
| `linkora_WORKSPACE` | Active workspace name |
| `linkora_LLM_API_KEY` | LLM API key (fallback: `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`) |
| `MINERU_API_KEY` | PDF parsing API key (MinerU) |
| `ZOTERO_API_KEY` | Zotero API key |
| `ZOTERO_LIBRARY_ID` | Zotero library ID |
| `OPENALEX_API_KEY` | OpenAlex API key |

### Example Config

```yaml
# ~/.linkora/config.yml
default_workspace: research

workspace:
  research:
    description: "Main research workspace"

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

## CLI Commands

| Command | Description |
|---------|-------------|
| `linkora search <query>` | Search papers (default: FTS5) |
| `linkora search <query> --mode vector` | Semantic vector search |
| `linkora index` | Build FTS5 index |
| `linkora index --type vector` | Build vector index |
| `linkora init` | Interactive setup wizard |
| `linkora audit` | Data quality audit |
| `linkora doctor` | Full health check |
| `linkora --context` | Show design context for AI agents |

## Architecture

linkora follows a layered architecture:

- **Layer 3**: CLI, MCP server, exports
- **Layer 2**: Features (topics, sources)
- **Layer 1**: Core (loader, index, extract)
- **Layer 0**: Foundation (config, log, papers)

See [`docs/design.md`](docs/design.md) for detailed architecture.

## Development

Please refer [design](docs/design.md) for architecture.

linkora uses [just](https://github.com/casey/just) for development workflows. However, it's **optional** for convenience.

Install just first, then use the commands below.

```bash
# Show all available commands
just

# Common commands
just setup        # Create venv and sync dependencies
just test         # Run tests
just lint         # Check linting
just typecheck    # Type checking
just check        # All quality checks
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
