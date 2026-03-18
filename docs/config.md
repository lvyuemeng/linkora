# linkora Configuration

> linkora configuration system with layered resolution and workspace support.

## Root Path

The **root path** is where linkora stores data. It is determined by:

1. `linkora_ROOT` environment variable
2. Walking up from current working directory to find `.linkora` folder or `workspace/` folder
3. Falls back to `cwd` if none found

```
# Root resolution (priority order):
linkora_ROOT env → .linkora/ or workspace/ found → cwd
```

## Layered Resolution

Configuration is resolved in priority order (highest to lowest):

| Priority | Source |
|----------|--------|
| 1 | CLI argument (`--workspace`) |
| 2 | Environment variable (`linkora_WORKSPACE`) |
| 3 | Workspace-local config (`<root>/workspace/<name>/linkora.yml`) |
| 4 | Global config (`~/.linkora/config.yml`, `~/.config/linkora/config.yml`) |
| 5 | Built-in defaults |

## Config File Locations

```
~/.linkora/config.yml           # User global config
~/.config/linkora/config.yml   # XDG config location
<root>/config.yaml            # Project config (legacy)
<root>/workspace/<name>/linkora.yml  # Workspace-local override
```

## Config Structure

### Global Config

```yaml
# ~/.linkora/config.yml

# Default workspace when none specified
default_workspace: physics

# Workspace definitions
workspace:
  physics:
    description: "Physics research workspace"
    root: /data/physics  # Optional: custom root for this workspace
  
  default:
    description: "Default workspace"

# Default sources (can be overridden per workspace)
sources:
  local:
    enabled: true
    papers_dir: papers
    paths:  # Additional paper paths
      - /mnt/library/papers
      - ~/Documents/research
  
  arxiv:
    enabled: false
  
  openalex:
    enabled: false
  
  zotero:
    enabled: false
    library_id: ""
    api_key: ""
  
  endnote:
    enabled: true

# Index configuration
index:
  top_k: 20
  embed_model: Qwen/Qwen3-Embedding-0.6B
  embed_device: auto
  embed_cache: ~/.cache/modelscope/hub/models
  embed_top_k: 10
  chunk_size: 800
  chunk_overlap: 150

# LLM configuration
llm:
  backend: openai-compat
  model: deepseek-chat
  base_url: https://api.deepseek.com
  api_key: ""
  timeout: 30

# Ingest configuration
ingest:
  extractor: robust
  mineru_endpoint: http://localhost:8000
  mineru_cloud_url: https://mineru.net/api/v4
  mineru_api_key: ""
  abstract_llm_mode: verify

# Topics configuration
topics:
  min_topic_size: 5
  nr_topics: 0
  model_dir: topic_model

# Logging configuration
logging:
  level: INFO
  file: linkora.log
  metrics_db: metrics.db
```

### Workspace-Local Override

```yaml
# workspace/physics/linkora.yml

description: "Physics with custom settings"

sources:
  local:
    paths:
      - /backup/physics
      - /mnt/external/physics-papers

index:
  chunk_size: 1000
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `linkora_ROOT` | Override root path for all workspaces |
| `linkora_WORKSPACE` | Override workspace name |
| `linkora_LLM_API_KEY` | Override LLM API key |

Service-specific env vars (fallback):
- `DEEPSEEK_API_KEY`, `OPENAI_API_KEY` - LLM
- `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID` - Zotero
- `MINERU_API_KEY` - MinerU

## Usage

### Python API

```python
from linkora.config import get_config, load_config, reload_config

# Get singleton config (lazy load)
cfg = get_config()

# Load with workspace override
cfg = load_config(workspace="physics")

# Force reload
cfg = reload_config()

# Root and paths
cfg.root              # → /data/physics (or <detected_root>)
cfg.workspace_dir     # → <root>/workspace/physics
cfg.papers_dir       # → <root>/workspace/physics/papers
cfg.extra_paths      # → [/mnt/library/papers, ~/Documents/research]

# Access sources
cfg.sources.local.enabled        # → True
cfg.sources.local.paths          # → ["/mnt/library/papers", "~/Documents/research"]
cfg.sources.arxiv.enabled       # → False
cfg.sources.zotero.library_id   # → ""

# Resolve API keys (with env fallback)
cfg.resolve_llm_api_key()       # → "sk-..."
cfg.resolve_zotero_api_key()    # → ""
cfg.resolve_mineru_api_key()    # → ""

# Ensure directories exist
cfg.ensure_dirs()
```

## Config Classes

| Class | Description |
|-------|-------------|
| `WorkspaceConfig` | Workspace identity (name, description, root) |
| `SourcesConfig` | All source configurations |
| `LocalSourceConfig` | Local source (papers_dir, paths[]) |
| `IndexConfig` | Search and embedding config |
| `LLMConfig` | LLM client config |
| `IngestConfig` | PDF processing config |
| `TopicsConfig` | Topic modeling config |
| `LogConfig` | Logging config |
| `Config` | Main resolved config |

## Path Resolution

Paths are derived from root and workspace:

```
root = linkora_ROOT env → detected → cwd
workspace_dir = <root>/workspace/<name>
papers_dir   = <workspace_dir>/<sources.local.papers_dir>
index_db     = <workspace_dir>/index.db
vectors_file = <workspace_dir>/vectors.faiss

# Additional paths
extra_paths = [<root>/path1, <root>/path2, ...]
```

### Multiple Paper Paths

The `sources.local.paths` config allows multiple paper storage locations:

```yaml
sources:
  local:
    papers_dir: papers  # Primary storage
    paths:              # Additional paths to scan
      - /mnt/library/papers
      - /backup/papers
```

Use `cfg.papers_dir` for primary storage and `cfg.extra_paths` for additional locations.
