# linkora Configuration

> Quick reference for linkora configuration.

## Config File Locations

| Location | Description |
|----------|-------------|
| `~/.linkora/config` | User global config (yaml/yml) |
| `~/.config/linkora/config` | XDG config location (yaml/yml) |
| `~/.linkora/.env` | Environment variables (optional) |

**Note**: If both global configs exist, a warning is shown and user config takes priority.

## Root Directory

The root directory is determined by:
1. Environment variable: `linkora_ROOT`
2. Platform-specific default:
   - Linux/macOS: `~/.local/share/linkora`
   - Windows: `%APPDATA%/linkora`

**Note**: Project-based config resolution was removed. Use environment variable for custom root.

## Environment Variables in Config

Use `${VAR}` or `${VAR:-fallback}` syntax:

```yaml
llm:
  api_key: ${DEEPSEEK_API_KEY}
  # or with fallback
  api_key: ${LINKORA_LLM_API_KEY:-${DEEPSEEK_API_KEY}}
```

Or in `.env` file (in same directory as config):

```bash
DEEPSEEK_API_KEY=sk-xxx
MINERU_API_KEY=xxx
```

## Layered Resolution

Config priority (highest to lowest):

1. CLI argument (`--workspace`)
2. Environment variable (`linkora_WORKSPACE`)
3. Workspace-local config (`<root>/workspace/<name>/linkora.yml`) - **sources only**
4. Global config (~/.linkora/config, ~/.config/linkora/config)
5. Built-in defaults

**Important**: Workspace-local config can ONLY override `sources` field. Other fields are ignored with a warning.

## Quick Config

```yaml
# ~/.linkora/config.yaml
default_workspace: research

workspace:
  research:
    description: "Main research workspace"

sources:
  local:
    enabled: true
    papers_dir: papers
    paths:
      - /mnt/library/papers
```

## Config Reference

### Sources

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `sources.local.enabled` | bool | true | Enable local papers |
| `sources.local.papers_dir` | string | "papers" | Primary papers directory |
| `sources.local.paths` | list[str] | [] | Additional paper paths |

### Index

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `index.top_k` | int | 20 | Default result count for search |
| `index.embed_model` | string | "Qwen/Qwen3-Embedding-0.6B" | Embedding model |
| `index.embed_device` | string | "auto" | Device for embedding |

### LLM

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `llm.backend` | string | "openai-compat" | LLM backend |
| `llm.model` | string | "deepseek-chat" | Model name |
| `llm.base_url` | string | "https://api.deepseek.com" | API endpoint |
| `llm.api_key` | string | "" | API key (use ${VAR} for env) |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `linkora_ROOT` | Root directory for all workspaces |
| `linkora_WORKSPACE` | Active workspace name |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `MINERU_API_KEY` | MinerU API key |
| `ZOTERO_API_KEY` | Zotero API key |

## Python API

```python
from linkora.config import get_config

# Get config (lazy load, creates directories on first call)
cfg = get_config()

# Access config
cfg.workspace.name          # Current workspace name
cfg.root                   # Root directory
cfg.workspace_dir          # Workspace directory
cfg.papers_store_dir       # Papers directory
cfg.index_db               # SQLite index path
cfg.vectors_file           # FAISS vectors file
cfg.log_file               # Log file path

# Source paths (returns list of paths!)
cfg.resolve_local_source_paths()  # papers_dir + paths array
cfg.resolve_local_source_dir()   # Legacy: primary path only

# API key resolution
cfg.resolve_llm_api_key()
cfg.resolve_zotero_api_key()
cfg.resolve_mineru_api_key()
```
