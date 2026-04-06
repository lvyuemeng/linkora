# linkora Configuration Guide

This document explains all configuration settings in `linkora/config.py` and how users should manage them.

---

## 1. How config is resolved

linkora loads one global config file. It does not merge multiple files.

Resolution order (highest priority first):
1. `~/.linkora/config.yml`
2. `~/.linkora/config.yaml`
3. `~/.linkora.yml`
4. `~/.linkora.yaml`
5. `~/.config/linkora/config.yml`
6. `~/.config/linkora/config.yaml`

Behavior:
- If multiple files exist, only the highest-priority file is active.
- Lower-priority files are ignored.
- linkora logs a warning naming the active file and ignored files.
- If no file exists, built-in defaults are used.

Example warning shape:

```text
Multiple config files found. '<active>' is active; ignoring: <others>.
Remove the ignored file(s) to silence this warning.
```

---

## 2. Global-only model

Configuration is global (`AppConfig`) and immutable at runtime.

Important:
- No workspace-local config override.
- Per-workspace behavior is controlled by CLI args and DB state, not per-workspace config files.

Is config required?
- No. Config is optional.
- If no config file exists, linkora runs with built-in defaults from `AppConfig`.
- You only need config when overriding defaults.

Non-config defaults are generally sufficient for:
- local add/search/index workflows
- files tidy/dedup/rescan with default behavior
- basic logging

Config is typically needed when you want:
- custom LLM endpoint/model/key setup
- non-default embed model/device/source
- custom tidy templates
- topic modeling tuning and model directory override

---

## 3. Environment variable expansion

YAML values support environment interpolation:
- `${VAR}`
- `${VAR:-fallback}`

Example:

```yaml
llm:
  api_key: ${LINKORA_LLM_API_KEY:-}
  base_url: ${LINKORA_LLM_BASE_URL:-https://api.deepseek.com}
```

The expansion is recursive across dict/list/string values.

---

## 4. Supported top-level sections

Valid sections for `linkora config set` are:
- `sources`
- `index`
- `extract`
- `tidy`
- `llm`
- `topics`
- `log`

Unknown sections are rejected by CLI with an error.

---

## 5. Full schema and defaults

```yaml
sources:
  arxiv:
    enabled: false

index:
  top_k: 20
  embed_model: Qwen/Qwen3-Embedding
  embed_device: cpu
  embed_top_k: 10
  embed_source: modelscope
  chunk_size: 800
  chunk_overlap: 150

extract:
  ocr_backend: tesseract
  extract_tables: true
  cache_max_mb: 500

tidy:
  dry_run: false
  confirm: true
  templates:
    paper: "{title}_{author}"
    generic: "{title}_{author}"
    invoice: "{vendor}_{amount}"
    contract: "{parties_slug}_contract"

llm:
  backend: openai-compat
  model: deepseek-chat
  base_url: https://api.deepseek.com
  api_key: ""
  timeout: 30
  timeout_toc: 120
  timeout_clean: 90

topics:
  min_topic_size: 5
  nr_topics: 0
  model_dir: topic_model

log:
  level: INFO
  file: linkora.log
  max_bytes: 10000000
  backup_count: 3
```

---

## 6. Section-by-section details

### 6.1 `sources`

`sources.arxiv.enabled`:
- Type: `bool`
- Default: `false`
- Purpose: feature flag for arXiv source behavior and checks.

### 6.2 `index`

- `top_k` (`int`, default `20`): default search result cap.
- `embed_model` (`str`): sentence-transformers model name.
- `embed_device` (`str`, default `cpu`): embedding device.
- `embed_top_k` (`int`, default `10`): default vector result cap.
- `embed_source` (`str`, default `modelscope`): model resolution strategy.
- `chunk_size` (`int`, default `800`): text chunk size for processing.
- `chunk_overlap` (`int`, default `150`): overlap size between chunks.

### 6.3 `extract`

- `ocr_backend` (`str`, default `tesseract`): OCR backend preference.
- `extract_tables` (`bool`, default `true`): table extraction toggle.
- `cache_max_mb` (`int`, default `500`): extraction cache size cap.

### 6.4 `tidy`

- `dry_run` (`bool`, default `false`): preview mode default.
- `confirm` (`bool`, default `true`): interactive rename confirmation.
- `templates` (`dict[str, str]`): filename templates per doc type.

Concrete template mapping semantics:

1. Start with `fields.model_dump()` from the selected schema (`DocumentFields` subclass).
   - Every schema field name can be referenced directly in template.
   - Missing keys are replaced with empty string (`""`), not errors.

2. Extra helper keys are injected:
   - `author`:
     - if `authors` is a non-empty list -> first item as string
     - if `authors` is a string -> that string
     - else -> `""`
   - `author_last`:
     - last token of `author`, lowercased
     - if empty author -> `""`
   - `title_slug`:
     - slugified lowercase title via `slugify_filename(title)`
     - truncated to first 40 chars
   - `parties_slug`:
     - for list `parties`, take first two entries,
       each entry uses its last token, joined by `_`, lowercased
     - if no parties -> `""`

3. Rendering order:
   - If custom template exists for the doc type, render custom first.
   - If rendered custom is empty/invalid and fallback is enabled, use schema filename template.

4. Final normalization in tidy flow:
   - invalid filename chars become `-`
   - whitespace compacted
   - suffix is appended as original lowercase extension.

Examples:

```yaml
tidy:
  templates:
    paper: "{year}_{author_last}_{title_slug}"
    contract: "{parties_slug}_contract"
```

- paper with `authors=["Jane Smith"]`, `year=2024`, `title="Attention Is All You Need"`
  -> `2024_smith_attention-is-all-you-need`
- contract with `parties=["Acme Corp", "Riverstone LLC"]`
  -> `corp_llc_contract`

### 6.5 `llm`

- `backend` (`str`, default `openai-compat`)
- `model` (`str`, default `deepseek-chat`)
- `base_url` (`str`, default `https://api.deepseek.com`)
- `api_key` (`str`, default empty)
- `timeout` (`int`, default `30`)
- `timeout_toc` (`int`, default `120`)
- `timeout_clean` (`int`, default `90`)

API key resolution:
- `AppConfig.resolve_llm_api_key()` returns `llm.api_key` first.
- If empty, it falls back to env var `LINKORA_LLM_API_KEY`.

### 6.6 `topics`

- `min_topic_size` (`int`, default `5`)
- `nr_topics` (`int`, default `0`)
- `model_dir` (`str`, default `topic_model`)

### 6.7 `log`

- `level` (`str`, default `INFO`)
- `file` (`str`, default `linkora.log`)
- `max_bytes` (`int`, default `10_000_000`)
- `backup_count` (`int`, default `3`)

Compatibility note:
- Legacy `logging` section is still read as fallback to `log` during load.

---

## 7. CLI operations

Show full config:

```bash
linkora config show
```

Show one field:

```bash
linkora config show llm.model
linkora config show index.embed_model
```

Set one field:

```bash
linkora config set llm.model deepseek-chat
linkora config set index.top_k 50
linkora config set tidy.confirm false
```

Value parsing:
- `set` values are YAML-parsed, so booleans/numbers/lists/maps work.
- Example: `linkora config set log.level INFO`

---

## 8. Common examples

### Use env-managed LLM key

```yaml
llm:
  backend: openai-compat
  model: deepseek-chat
  base_url: https://api.deepseek.com
  api_key: ${LINKORA_LLM_API_KEY:-}
```

### Use custom embedding model on CPU

```yaml
index:
  embed_model: Qwen/Qwen3-Embedding
  embed_device: cpu
  embed_source: modelscope
```

### Safer tidy defaults (preview first)

```yaml
tidy:
  dry_run: true
  confirm: true
```

---

## 9. Troubleshooting

- If config changes appear ignored, run `linkora config show` and confirm the active file path from logs.
- If multiple config files exist, the first candidate wins; remove lower-priority duplicates.
- If a key lookup fails, ensure the top-level section is one of the valid sections listed above.
