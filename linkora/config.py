"""
config.py - linkora application configuration.

Configuration is immutable at runtime and does not contain workspace runtime state.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

ENV_PREFIX = "LINKORA_"
_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")
_MISSING = object()


def _expand_env_string(
    value: str,
    dotenv: Mapping[str, str],
    environ: Mapping[str, str],
) -> str:
    def _sub(match: re.Match[str]) -> str:
        name, fallback = match.group(1), match.group(2)
        if name in dotenv:
            return dotenv[name]
        env_value = environ.get(name)
        if env_value is not None:
            return env_value
        return fallback or ""

    return _ENV_PATTERN.sub(_sub, value)


def _expand_env_value(
    value: Any,
    dotenv: Mapping[str, str],
    environ: Mapping[str, str],
) -> Any:
    if isinstance(value, str):
        return _expand_env_string(value, dotenv, environ)
    if isinstance(value, dict):
        return {k: _expand_env_value(v, dotenv, environ) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_value(v, dotenv, environ) for v in value]
    return value


def _resolve_path(value: str, data_root: Path) -> str:
    raw = Path(value).expanduser()
    resolved = raw if raw.is_absolute() else (data_root / raw)
    return str(resolved.resolve())


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


class AppConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    index: IndexConfig = Field(default_factory=IndexConfig)
    extract: ExtractConfig = Field(default_factory=ExtractConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tidy: TidyConfig = Field(default_factory=TidyConfig)
    topics: TopicsConfig = Field(default_factory=TopicsConfig)
    log: LogConfig = Field(default_factory=LogConfig)

    @property
    def llm_api_key(self) -> str:
        return self.llm.api_key or os.environ.get(f"{ENV_PREFIX}LLM_API_KEY", "")

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        data_root: Path,
        dotenv: Mapping[str, str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "AppConfig":
        dotenv_map = dotenv or {}
        env_map = environ or os.environ
        expanded = _expand_env_value(doc, dotenv_map, env_map)
        return cls.model_validate(expanded).normalize_paths(data_root)

    @classmethod
    def from_root(cls, data_root: Path) -> "AppConfig":
        """Build default config and normalize all path fields for data root."""
        return cls().normalize_paths(data_root)

    def normalize_paths(self, data_root: Path) -> "AppConfig":
        topics_cfg = self.topics.model_copy(
            update={"model_dir": _resolve_path(self.topics.model_dir, data_root)}
        )
        return self.model_copy(update={"topics": topics_cfg})

    def _read_nested(self, parts: list[str]) -> Any:
        current: Any = self
        for part in parts:
            if isinstance(current, BaseModel):
                if not hasattr(current, part):
                    return _MISSING
                current = getattr(current, part)
                continue
            if isinstance(current, Mapping):
                mapping_current = current
                if part not in mapping_current:
                    return _MISSING
                current = mapping_current.get(part, _MISSING)
                continue
            return _MISSING
        return current

    def to_yaml(self, field: str | None = None) -> str:
        import yaml

        if not field:
            payload: Any = self.model_dump()
        else:
            value = self._read_nested(field.split("."))
            if value is _MISSING:
                return f"Field '{field}' not found in config."
            payload = {field: value}

        return yaml.safe_dump(
            payload,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


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
