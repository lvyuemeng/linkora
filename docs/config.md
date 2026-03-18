# linkora Configuration

> Quick reference for linkora configuration. See examples in [`examples/config/`](examples/config/).

## Config File Locations

| Location | Description |
|----------|-------------|
| `~/.linkora/config.yml` | User global config |
| `~/.config/linkora/config.yml` | XDG config location |
| `<workspace>/linkora.yml` | Workspace-local override |

## Layered Resolution

Config priority (highest to lowest):

1. CLI argument (`--workspace`)
2. Environment variable (`linkora_WORKSPACE`)
3. Workspace-local config
4. Global config
5. Built-in defaults

## Quick Config

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

## Config Reference

### Sources

| Option | Type | Default | Valid Values | Description |
|--------|------|---------|--------------|-------------|
| `sources.local.enabled` | bool | true | - | Enable local papers |
| `sources.local.papers_dir` | string | "papers" | valid path | Primary papers directory (relative to workspace) |
| `sources.local.paths` | list[str] | [] | absolute paths | Additional paper paths to scan |
| `sources.arxiv.enabled` | bool | false | - | Enable ArXiv import |
| `sources.openalex.enabled` | bool | false | - | Enable OpenAlex API |
| `sources.zotero.enabled` | bool | false | - | Enable Zotero |
| `sources.zotero.library_id` | string | "" | alphanumeric | Zotero library ID |
| `sources.zotero.api_key` | string | "" | Zotero API key | Zotero API key |
| `sources.zotero.library_type` | string | "user" | "user" \| "group" | Zotero library type |
| `sources.endnote.enabled` | bool | true | - | Enable EndNote XML/RIS import |

### Index

| Option | Type | Default | Valid Values | Description |
|--------|------|---------|--------------|-------------|
| `index.top_k` | int | 20 | 1-100 | Default result count for search |
| `index.embed_model` | string | "Qwen/Qwen3-Embedding-0.6B" | HuggingFace model ID | Embedding model for semantic search |
| `index.embed_device` | string | "auto" | "auto" \| "cpu" \| "cuda" \| "mps" | Device for embedding inference |
| `index.embed_cache` | string | "~/.cache/modelscope/hub/models" | directory path | Model cache directory |
| `index.embed_source` | string | "modelscope" | "modelscope" \| "huggingface" | Model download source |
| `index.embed_top_k` | int | 10 | 1-100 | Top-k results for vector search |
| `index.chunk_size` | int | 800 | 100-2000 | Text chunk size for embeddings |
| `index.chunk_overlap` | int | 150 | 0-500 | Overlap between chunks |

### LLM

| Option | Type | Default | Valid Values | Description |
|--------|------|---------|--------------|-------------|
| `llm.backend` | string | "openai-compat" | "openai-compat" \| "openai" \| "anthropic" | LLM backend |
| `llm.model` | string | "deepseek-chat" | model identifier | Model name |
| `llm.base_url` | string | "https://api.deepseek.com" | URL | API endpoint URL |
| `llm.api_key` | string | "" | API key string | API key |
| `llm.timeout` | int | 30 | 10-300 | General request timeout (seconds) |
| `llm.timeout_toc` | int | 120 | 30-600 | Table of contents extraction timeout |
| `llm.timeout_clean` | int | 90 | 30-600 | Text cleaning timeout |

### Ingest

| Option | Type | Default | Valid Values | Description |
|--------|------|---------|--------------|-------------|
| `ingest.extractor` | string | "robust" | "regex" \| "llm" \| "auto" \| "robust" | PDF extraction method |
| `ingest.mineru_endpoint` | string | "http://localhost:8000" | URL | MinerU local server endpoint |
| `ingest.mineru_cloud_url` | string | "https://mineru.net/api/v4" | URL | MinerU cloud API URL |
| `ingest.mineru_api_key` | string | "" | API key | MinerU API key |
| `ingest.abstract_llm_mode` | string | "verify" | "verify" \| "extract" \| "skip" | Abstract extraction mode |
| `ingest.contact_email` | string | "" | email | Contact email for API requests |

### Topics

| Option | Type | Default | Valid Values | Description |
|--------|------|---------|--------------|-------------|
| `topics.min_topic_size` | int | 5 | 2-50 | Minimum documents per topic |
| `topics.nr_topics` | int | 0 | 0-100 | Number of topics (0 = auto-detect) |
| `topics.model_dir` | string | "topic_model" | directory path | Topic model storage directory |

### Logging

| Option | Type | Default | Valid Values | Description |
|--------|------|---------|--------------|-------------|
| `logging.level` | string | "INFO" | "DEBUG" \| "INFO" \| "WARNING" \| "ERROR" | Log level |
| `logging.file` | string | "linkora.log" | filename | Log file (relative to root) |
| `logging.max_bytes` | int | 10000000 | 1000000-100000000 | Max log file size before rotation |
| `logging.backup_count` | int | 3 | 1-10 | Number of rotated log files to keep |
| `logging.metrics_db` | string | "metrics.db" | filename | Metrics database file |

## Environment Variables

| Variable | Valid Values | Description |
|----------|--------------|-------------|
| `linkora_ROOT` | directory path | Root directory for all workspaces |
| `linkora_WORKSPACE` | workspace name | Active workspace name |
| `linkora_LLM_API_KEY` | API key | Override LLM API key |
| `DEEPSEEK_API_KEY` | API key | DeepSeek API key (fallback) |
| `OPENAI_API_KEY` | API key | OpenAI API key (fallback) |
| `MINERU_API_KEY` | API key | MinerU API key |
| `ZOTERO_API_KEY` | API key | Zotero API key |
| `ZOTERO_LIBRARY_ID` | alphanumeric | Zotero library ID |
| `OPENALEX_API_KEY` | API key | OpenAlex API key |

## Python API

```python
from linkora.config import get_config, load_config

# Get config (lazy load)
cfg = get_config()

# Load with workspace
cfg = load_config(workspace="physics")

# Paths
cfg.root            # Root directory (Path object)
cfg.workspace_dir   # Workspace directory (Path)
cfg.papers_dir      # Papers directory (Path)
cfg.index_db        # SQLite index path (Path)
cfg.vectors_file    # FAISS vectors file (Path)
cfg.log_file        # Log file path (Path)
cfg.metrics_db_path # Metrics DB path (Path)

# Config access (attributes)
cfg.sources.local.enabled
cfg.index.top_k
cfg.llm.model

# API key resolution (with env fallback)
cfg.resolve_llm_api_key()       # -> str
cfg.resolve_zotero_api_key()    # -> str
cfg.resolve_mineru_api_key()    # -> str

# Ensure directories exist
cfg.ensure_dirs()  # -> None
```
