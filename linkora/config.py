"""
config.py — linkora application configuration

Resolution order:

    1. ~/.linkora/config.yml
    2. ~/.linkora/config.yaml
    3. ~/.linkora.yml
    4. ~/.linkora.yaml
    5. ~/.config/linkora/config.yml
    6. ~/.config/linkora/config.yaml

There is NO workspace-local config override.  Per-workspace settings
are not supported; use the global config for all settings.

If multiple config files exist, only the highest-priority file is active;
lower-priority files are ignored and a warning is emitted.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENV_PREFIX = "LINKORA_"


# ---------------------------------------------------------------------------
# Sub-config models  (pure Pydantic — NO @dataclass decorator)
# ---------------------------------------------------------------------------


class ArxivSourceConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False


class SourcesConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    arxiv: ArxivSourceConfig = Field(default_factory=ArxivSourceConfig)


class IndexConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    top_k: int = 20
    embed_model: str = "Qwen/Qwen3-Embedding"
    embed_device: str = "cpu"
    embed_top_k: int = 10
    embed_source: str = "modelscope"
    chunk_size: int = 800
    chunk_overlap: int = 150


class ExtractConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    ocr_backend: str = "tesseract"
    extract_tables: bool = True
    cache_max_mb: int = 500


class TidyConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    dry_run: bool = False
    confirm: bool = True
    templates: dict[str, str] = Field(
        default_factory=lambda: {
            "paper": "{title}_{author}",
            "generic": "{title}_{author}",
            "invoice": "{vendor}_{amount}",
            "contract": "{parties_slug}_contract",
        }
    )


class LLMConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    backend: str = "openai-compat"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    timeout: int = 30
    timeout_toc: int = 120
    timeout_clean: int = 90


class TopicsConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    min_topic_size: int = 5
    nr_topics: int = 0
    model_dir: str = "topic_model"


class LogConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    level: str = "INFO"
    file: str = "linkora.log"
    max_bytes: int = 10_000_000
    backup_count: int = 3


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class AppConfig(BaseModel):
    """
    Immutable application settings loaded from a single YAML file.

    Does NOT contain workspace names, workspace paths, or runtime state.
    All API keys are resolved lazily via the `resolve_*` methods so that
    environment variables are read at call time, not at load time.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    index: IndexConfig = Field(default_factory=IndexConfig)
    extract: ExtractConfig = Field(default_factory=ExtractConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tidy: TidyConfig = Field(default_factory=TidyConfig)
    topics: TopicsConfig = Field(default_factory=TopicsConfig)
    log: LogConfig = Field(default_factory=LogConfig)

    # ------------------------------------------------------------------
    # Key resolution  (environment variable fallbacks)
    # ------------------------------------------------------------------

    def resolve_llm_api_key(self) -> str:
        return self.llm.api_key or os.environ.get(f"{ENV_PREFIX}LLM_API_KEY", "")


__all__ = [
    "AppConfig",
    "ArxivSourceConfig",
    "SourcesConfig",
    "IndexConfig",
    "LLMConfig",
    "ExtractConfig",
    "TidyConfig",
    "TopicsConfig",
    "LogConfig",
]
