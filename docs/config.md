# linkora Configuration Guide

> User guide for linkora configuration. Learn how to set up and customize linkora for your research workflow.

---

## 1. Core Concepts

### 1.1 What is a Workspace?

A **workspace** is a self-contained research environment that keeps your papers, indexes, and settings organized. Think of it as a project folder that contains everything related to a specific research topic.

```
linkora_root/
└── workspace/
    ├── default/          # Default workspace
    │   ├── papers/       # Your PDF papers
    │   ├── index.db      # Full-text search index
    │   └── vectors.faiss # Semantic search index
    ├── physics/          # Another workspace
    │   └── ...
    └── ml/              # Machine learning workspace
        └── ...
```

### 1.2 Why Multiple Workspaces?

- **Isolation**: Keep different research topics separate
- **Different sources**: Each workspace can have its own paper sources
- **Different settings**: Embedding models, LLM backends per workspace

---

## 2. Config File Locations

linkora looks for configuration files in the following locations (in priority order):

| Location | Platform | Description |
|----------|----------|-------------|
| `~/.linkora/config.yml` | All | User global config |
| `~/.config/linkora/config.yml` | Linux/macOS | XDG standard location |
| `%APPDATA%/linkora/config.yml` | Windows | User global config |

**Note**: If both global configs exist, linkora shows a warning and uses the user config (`~/.linkora/config.yml`).

### 2.1 Environment Variables

You can also use environment variables:

```bash
# Root directory for all workspaces
export linkora_ROOT=/path/to/root

# Active workspace name
export linkora_WORKSPACE=physics
```

---

## 3. Config File Structure

### 3.1 Minimal Config

```yaml
# ~/.linkora/config.yml
default_workspace: default

sources:
  local:
    enabled: true
    papers_dir: papers
```

### 3.2 Multi-Path Config

You can add multiple local paths to search for papers:

```yaml
# ~/.linkora/config.yml
default_workspace: research

sources:
  local:
    enabled: true
    papers_dir: papers              # Primary path (workspace-relative)
    paths:                          # Additional paths
      - /mnt/library/papers         # Absolute path
      - ~/Dropbox/research          # Home-relative path
      - ${EXTRA_PAPERS}            # Environment variable
```

### 3.3 Full Config Example

```yaml
# ~/.linkora/config.yml
default_workspace: research

workspace:
  research:
    description: "Main research workspace"

index:
  top_k: 20
  embed_model: Qwen/Qwen3-Embedding-0.6B
  embed_device: auto

sources:
  local:
    enabled: true
    papers_dir: papers
    paths:
      - /data/research/pdfs
  openalex:
    enabled: true

llm:
  backend: openai-compat
  model: deepseek-chat
  base_url: https://api.deepseek.com
  api_key: ${DEEPSEEK_API_KEY}

ingest:
  extractor: robust
  mineru_endpoint: http://localhost:8000

logging:
  level: INFO
  file: linkora.log
```

---

## 4. Config Resolution

### 4.1 Layered Resolution

Configuration values are resolved in the following priority order (highest to lowest):

```
1. CLI argument (--workspace)
       ↓
2. Environment variable (linkora_WORKSPACE)
       ↓
3. Workspace-local config (<root>/workspace/<name>/linkora.yml)
       ↓
4. Global config (~/.linkora/config.yml)
       ↓
5. Built-in defaults
```

### 4.2 Workspace-Local Override

You can create a workspace-local config file at `<root>/workspace/<name>/linkora.yml` to override sources for that workspace:

```yaml
# ~/.local/share/linkora/workspace/research/linkora.yml
sources:
  local:
    enabled: true
    papers_dir: ~/papers_physics
    paths:
      - /data/physics_preprints
```

**Important**: Workspace-local config can ONLY override the `sources` field. Other fields are ignored with a warning.

---

## 5. Environment Variables in Config

### 5.1 Syntax

Use `${VAR}` or `${VAR:-fallback}` syntax in your config:

```yaml
llm:
  api_key: ${DEEPSEEK_API_KEY}
  # Fallback if not set
  api_key: ${LINKORA_LLM_API_KEY:-${DEEPSEEK_API_KEY}}
```

### 5.2 .env File

You can also create a `.env` file in the same directory as your config:

```bash
# ~/.linkora/.env
DEEPSEEK_API_KEY=sk-xxx
MINERU_API_KEY=xxx
ZOTERO_API_KEY=xxx
```

---

## 6. Config Reference

### 6.1 Sources

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `sources.local.enabled` | bool | true | Enable local papers |
| `sources.local.papers_dir` | string | "papers" | Primary papers directory |
| `sources.local.paths` | list[str] | [] | Additional paper paths |
| `sources.openalex.enabled` | bool | true | Enable OpenAlex API |
| `sources.zotero.enabled` | bool | false | Enable Zotero |

### 6.2 Index

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `index.top_k` | int | 20 | Default result count |
| `index.embed_model` | string | "Qwen/Qwen3-Embedding-0.6B" | Embedding model |
| `index.embed_device` | string | "auto" | Device (auto/cpu/cuda) |

### 6.3 LLM

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `llm.backend` | string | "openai-compat" | LLM backend |
| `llm.model` | string | "deepseek-chat" | Model name |
| `llm.base_url` | string | "https://api.deepseek.com" | API endpoint |
| `llm.api_key` | string | "" | API key (use ${VAR}) |
| `llm.timeout` | int | 30 | Request timeout |

### 6.4 Ingest

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `ingest.extractor` | string | "robust" | Extraction mode |
| `ingest.mineru_endpoint` | string | "http://localhost:8000" | MinerU endpoint |

---

## 7. Python API

### 7.1 Getting Config

```python
from linkora.config import get_config

# Get config (lazy load, creates directories on first call)
cfg = get_config()
```

### 7.2 Accessing Config Values

```python
# Workspace
cfg.workspace.name          # Current workspace name
cfg.root                    # Root directory
cfg.workspace_dir           # Workspace directory
cfg.papers_dir              # Papers directory
cfg.index_db                # SQLite index path
cfg.vectors_file            # FAISS vectors file
```

### 7.3 Source Paths

```python
# Get all local source paths (primary + additional)
paths = cfg.resolve_local_source_paths()
# Returns: list of Path objects

# Example usage
for path in paths:
    print(f"Scanning: {path}")
```

### 7.4 API Key Resolution

```python
# Resolve API keys from config/env
cfg.resolve_llm_api_key()
cfg.resolve_mineru_api_key()
cfg.resolve_zotero_api_key()
```

---

## 8. Quick Start

### 8.1 First Time Setup

1. Create config file at `~/.linkora/config.yml`:

```yaml
default_workspace: default
sources:
  local:
    enabled: true
    papers_dir: papers
```

2. Run linkora:

```bash
# Check setup
linkora check

# Initialize workspace
linkora init
```

### 8.2 Adding Papers

```bash
# Add papers from local directory
linkora add --doi 10.1234/example
linkora add --title "machine learning"
linkora add "quantum physics"
```

---

## 9. Troubleshooting

### 9.1 Config Not Found

If linkora can't find your config:

1. Check config file location:
   - Linux/macOS: `~/.linkora/config.yml` or `~/.config/linkora/config.yml`
   - Windows: `%APPDATA%/linkora/config.yml`

2. Set explicit root:
   ```bash
   export linkora_ROOT=/path/to/root
   ```

### 9.2 Paths Not Resolving

Paths in config are resolved relative to the config file location, not the current directory.

```yaml
# This path is relative to ~/.linkora/
sources:
  local:
    papers_dir: my_papers    # Resolved to ~/.linkora/my_papers
```

For absolute paths, use full path or environment variables.
