# linkora Configuration Guide

> User guide for linkora configuration. Learn how to set up and customize linkora for your research workflow.

---

## 1. Core Concepts

### 1.1 What is a Workspace?

A **workspace** is a self-contained research environment that keeps your papers, indexes, and metadata isolated from other projects. Think of it as a dedicated folder for a specific research topic — it stores everything related to that topic in one place.

Workspaces are **managed entirely by CLI commands** — not by user-editable config files. The workspace registry and metadata are stored in JSON files within the data root.

```
<data_root>/                          # e.g., ~/.local/share/linkora
└── workspace/
    ├── workspaces.json              # Registry: workspace names + default
    ├── default/                     # Default workspace
    │   ├── workspace.json           # Metadata (name, description, created_at)
    │   ├── papers/                  # PDF papers
    │   ├── index.db                 # Full-text search index (FTS5)
    │   ├── vectors.faiss             # Semantic search index (FAISS)
    │   └── logs/                    # Workspace-specific logs
    ├── physics/                     # Another workspace
    │   └── ...
    └── ml/                          # Machine learning workspace
        └── ...
```

### 1.2 Why Multiple Workspaces?

- **Isolation**: Keep different research topics separate
- **Independent indexing**: Each workspace has its own search index
- **Easy migration**: Move or rename workspaces without breaking references

### 1.3 What is Configuration?

**Configuration** is the global settings that apply to all workspaces. Unlike workspaces, configuration is user-editable via YAML files.

Configuration includes:
- **Sources**: Where to find papers (local folders, arXiv, OpenAlex, Zotero, EndNote)
- **Index**: Search behavior (embedding model, chunk size, result count)
- **LLM**: Language model settings for enrichment and analysis
- **Ingest**: PDF extraction settings (MinerU, content parsing)
- **Topics**: Topic modeling configuration
- **Logging**: Log levels and file management

---

## 2. Config File Locations

linkora looks for configuration files in the following locations, in priority order (highest to lowest):

| Priority | Location | Platform | Description |
|----------|----------|---------|-------------|
| Highest | `~/.linkora/config.yml` | All | User home directory |
| Lower | `~/.config/linkora/config.yml` | All | XDG standard location |
| Fallback | Built-in defaults | All | If no config file exists |

**Key Rule**: Exactly ONE config file wins — there is NO merging. If multiple config files exist, linkora uses the highest-priority one and emits a warning about ignored files.

### 2.1 How Config Resolution Works

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Check ~/.linkora/config.yml exists?                      │
│    YES → Use it (stop here)                                │
│    NO  → Continue                                           │
├─────────────────────────────────────────────────────────────┤
│ 2. Check ~/.config/linkora/config.yml exists?               │
│    YES → Use it (stop here)                                 │
│    NO  → Continue                                           │
├─────────────────────────────────────────────────────────────┤
│ 3. Use built-in defaults                                     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Environment Variables

You can also control linkora via environment variables:

| Variable | Description |
|----------|-------------|
| `LINKORA_ROOT` | Override the data root directory |
| `LINKORA_WORKSPACE` | Set the active workspace name |

API keys can also be provided via environment variables (see [Environment Variables in Config](#5-environment-variables-in-config)).

---

## 3. Data Root Directory

The data root is where linkora stores all workspaces and runtime data.

| Platform | Default Location | Override |
|----------|-----------------|----------|
| Windows | `%APPDATA%/linkora` | Set `LINKORA_ROOT` |
| macOS | `~/Library/Application Support/linkora` | Set `LINKORA_ROOT` |
| Linux | `$XDG_DATA_HOME/linkora` (default: `~/.local/share/linkora`) | Set `LINKORA_ROOT` |

---

## 4. Config File Structure

### 4.1 Minimal Config

```yaml
# ~/.linkora/config.yml
sources:
  local:
    enabled: true
    papers_dir: papers
```

### 4.2 Full Config Example

```yaml
# ~/.linkora/config.yml

sources:
  local:
    enabled: true
    papers_dir: papers
    paths:
      - /data/research/pdfs
      - ~/Dropbox/research
  arxiv:
    enabled: false
  openalex:
    enabled: false
  zotero:
    enabled: false
    library_id: ""
    api_key: ""
    library_type: user
  endnote:
    enabled: true

index:
  top_k: 20
  embed_model: Qwen/Qwen3-Embedding-0.6B
  embed_device: auto
  embed_cache: ~/.cache/modelscope/hub/models
  embed_top_k: 10
  embed_source: modelscope
  chunk_size: 800
  chunk_overlap: 150

llm:
  backend: openai-compat
  model: deepseek-chat
  base_url: https://api.deepseek.com
  api_key: ${DEEPSEEK_API_KEY}
  timeout: 30
  timeout_toc: 120
  timeout_clean: 90

ingest:
  extractor: robust
  mineru_endpoint: http://localhost:8000
  mineru_cloud_url: https://mineru.net/api/v4
  mineru_api_key: ${MINERU_API_KEY}
  abstract_llm_mode: verify
  contact_email: ""

topics:
  min_topic_size: 5
  nr_topics: 0
  model_dir: topic_model

log:
  level: INFO
  file: linkora.log
  max_bytes: 10000000
  backup_count: 3
  metrics_db: metrics.db
```

---

## 5. Environment Variables in Config

### 5.1 Syntax

Use `${VAR}` or `${VAR:-fallback}` syntax to reference environment variables:

```yaml
llm:
  api_key: ${DEEPSEEK_API_KEY}
  # Fallback if not set
  base_url: ${LINKORA_LLM_BASE_URL:-https://api.deepseek.com}
```

Where `linkora` automatically resolve the `.env` file located in same place with `config.yml`:

```
DEEPSEEK_API_KEY=...
LINKORA_LLM_BASE_URL=...
```

### 5.2 API Key Resolution

API keys are resolved **lazily** at call time (not at config load time), allowing environment variables to be set after linkora starts:

| Config Field | Environment Variable Fallbacks |
|--------------|-------------------------------|
| `llm.api_key` | `LINKORA_LLM_API_KEY` → `DEEPSEEK_API_KEY` → `OPENAI_API_KEY` |
| `sources.zotero.api_key` | `ZOTERO_API_KEY` |
| `sources.zotero.library_id` | `ZOTERO_LIBRARY_ID` |
| `ingest.mineru_api_key` | `MINERU_API_KEY` |

---

## 6. Workspace Management

Workspaces are managed via CLI commands, not config files:

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
linkora config mv my-ws /data/linkora/my-ws  # Move to custom location
```

---

## 7. Config Reference

### 7.1 Sources

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `sources.local.enabled` | bool | true | Enable local papers |
| `sources.local.papers_dir` | string | "papers" | Primary papers directory (workspace-relative) |
| `sources.local.paths` | list[str] | [] | Additional absolute or home-relative paths |
| `sources.arxiv.enabled` | bool | false | Enable arXiv source |
| `sources.openalex.enabled` | bool | false | Enable OpenAlex API |
| `sources.zotero.enabled` | bool | false | Enable Zotero |
| `sources.zotero.library_id` | string | "" | Zotero library ID |
| `sources.zotero.library_type` | string | "user" | Zotero library type (user/group) |
| `sources.endnote.enabled` | bool | true | Enable EndNote source |

### 7.2 Index

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `index.top_k` | int | 20 | Default result count for search |
| `index.embed_model` | string | "Qwen/Qwen3-Embedding-0.6B" | Embedding model |
| `index.embed_device` | string | "auto" | Device (auto/cpu/cuda) |
| `index.embed_cache` | string | "~/.cache/modelscope/hub/models" | Model cache directory |
| `index.embed_top_k` | int | 10 | Top K for embedding retrieval |
| `index.embed_source` | string | "modelscope" | Embedding model source |
| `index.chunk_size` | int | 800 | Text chunk size for indexing |
| `index.chunk_overlap` | int | 150 | Text chunk overlap |

### 7.3 LLM

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `llm.backend` | string | "openai-compat" | LLM backend |
| `llm.model` | string | "deepseek-chat" | Model name |
| `llm.base_url` | string | "https://api.deepseek.com" | API endpoint |
| `llm.api_key` | string | "" | API key (use ${VAR} or env) |
| `llm.timeout` | int | 30 | Request timeout (seconds) |
| `llm.timeout_toc` | int | 120 | TOC extraction timeout (seconds) |
| `llm.timeout_clean` | int | 90 | Content cleaning timeout (seconds) |

### 7.4 Ingest

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `ingest.extractor` | string | "robust" | Extraction mode (regex/auto/llm/robust) |
| `ingest.mineru_endpoint` | string | "http://localhost:8000" | MinerU local endpoint |
| `ingest.mineru_cloud_url` | string | "https://mineru.net/api/v4" | MinerU cloud API |
| `ingest.mineru_api_key` | string | "" | MinerU API key |
| `ingest.abstract_llm_mode` | string | "verify" | LLM abstract mode (off/fallback/verify) |
| `ingest.contact_email` | string | "" | Contact email for API requests |

### 7.5 Topics

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `topics.min_topic_size` | int | 5 | Minimum papers per topic |
| `topics.nr_topics` | int | 0 | Number of topics (0=auto) |
| `topics.model_dir` | string | "topic_model" | Model save directory |

### 7.6 Logging

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `log.level` | string | "INFO" | Log level (DEBUG/INFO/WARNING/ERROR) |
| `log.file` | string | "linkora.log" | Log file name |
| `log.max_bytes` | int | 10000000 | Max log file size |
| `log.backup_count` | int | 3 | Number of backup files |
| `log.metrics_db` | string | "metrics.db" | Metrics database file |

---

## 8. Python API

### 8.1 Getting Config

```python
from linkora.config import get_config, get_config_path, get_config_dir

# Get the active AppConfig (singleton, lazy-loaded)
cfg = get_config()

# Get the path of the active config file (None if using defaults)
config_path = get_config_path()

# Get the directory containing the config file
config_dir = get_config_dir()
```

### 8.2 Accessing Config Values

```python
# Sources configuration
cfg.sources.local.enabled
cfg.sources.local.paths
cfg.sources.arxiv.enabled

# Index configuration  
cfg.index.top_k
cfg.index.embed_model
cfg.index.chunk_size

# LLM configuration
cfg.llm.backend
cfg.llm.model
cfg.llm.base_url

# API key resolution (lazy - reads env vars at call time)
cfg.resolve_llm_api_key()
cfg.resolve_mineru_api_key()
cfg.resolve_zotero_api_key()
```

### 8.3 Workspace API

```python
from linkora.workspace import WorkspaceStore, WorkspacePaths, get_data_root

# Get the data root directory
data_root = get_data_root()

# Create a workspace store
store = WorkspaceStore(data_root)

# List all workspaces
workspaces = store.list_workspaces()

# Get the default workspace
default_ws = store.get_default()

# Get workspace metadata
meta = store.get_metadata("ml")

# Get workspace paths (computed, not stored)
paths = store.paths("ml")
paths.papers_dir       # Path to papers directory
paths.index_db         # Path to FTS index
paths.vectors_file     # Path to FAISS index

# Create a new workspace
store.create("new-workspace", description="My new workspace")

# Set default workspace
store.set_default("ml")
```

---

## 9. Quick Start

### 9.1 First Time Setup

1. Create config file at `~/.linkora/config.yml`:

```yaml
sources:
  local:
    enabled: true
    papers_dir: papers
```

2. Run linkora:

```bash
# Check setup
linkora doctor

# Interactive setup (if available)
linkora init
```

### 9.2 Adding Papers

```bash
# Add papers by DOI
linkora add --doi 10.1234/example

# Add papers by title
linkora add --title "machine learning"

# Add papers by free-form query
linkora add "quantum physics"
```

---

## 10. Troubleshooting

### 10.1 Config Not Found

If linkora can't find your config:

1. Check config file location:
   - Linux/macOS: `~/.linkora/config.yml` or `~/.config/linkora/config.yml`
   - Windows: `%APPDATA%/linkora/config.yml`

2. Set explicit root:
   ```bash
   export LINKORA_ROOT=/path/to/root
   ```

### 10.2 Multiple Config Files Warning

If you see a warning about multiple config files, remove the lower-priority file:

```bash
# Warning: Multiple config files found. '~/.linkora/config.yml' is active; 
# ignoring: ~/.config/linkora/config.yml
rm ~/.config/linkora/config.yml
```

### 10.3 Paths Not Resolving

Paths in config are resolved relative to the config file location:

```yaml
# This path is relative to ~/.linkora/
sources:
  local:
    paths:
      - my_papers    # Resolved to ~/.linkora/my_papers
```

For absolute paths, use full path or environment variables.
