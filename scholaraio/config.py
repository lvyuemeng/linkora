"""
config.py — ScholarAIO configuration loading and management

Priority (high to low):
1. config.local.yaml (API keys, not tracked)
2. config.yaml (main config)
3. Code defaults

Config file search:
1. Explicit config_path
2. SCHOLARAIO_CONFIG env var
3. Walk up from cwd (max 6 levels)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


ENV_PREFIX = "SCHOLARAIO_"


# Protocols (Interfaces)


class ConfigProtocol(Protocol):
    """Protocol for Config - enables dependency injection."""

    @property
    def papers_dir(self) -> Path: ...

    @property
    def index_db(self) -> Path: ...

    @property
    def log_file(self) -> Path: ...

    def ensure_dirs(self) -> None: ...


# Service-specific protocols for API key resolution


class HasLLM(Protocol):
    """Protocol for LLM service."""

    llm: LLMConfig


class HasZotero(Protocol):
    """Protocol for Zotero service."""

    zotero: ZoteroConfig


class HasMinerU(Protocol):
    """Protocol for MinerU service."""

    ingest: IngestConfig


# API key resolution - explicit functions, no getattr


def resolve_llm(cfg: HasLLM) -> str:
    """Resolve LLM API key: config > SCHOLARAIO_LLM_API_KEY > DEEPSEEK_API_KEY > OPENAI_API_KEY."""
    if cfg.llm.api_key:
        return cfg.llm.api_key
    if key := os.environ.get("SCHOLARAIO_LLM_API_KEY"):
        return key
    if key := os.environ.get("DEEPSEEK_API_KEY"):
        return key
    if key := os.environ.get("OPENAI_API_KEY"):
        return key
    return ""


def resolve_zotero_api_key(cfg: HasZotero) -> str:
    """Resolve Zotero API key."""
    if cfg.zotero.api_key:
        return cfg.zotero.api_key
    if key := os.environ.get("ZOTERO_API_KEY"):
        return key
    return ""


def resolve_zotero_library_id(cfg: HasZotero) -> str:
    """Resolve Zotero library ID."""
    if cfg.zotero.library_id:
        return cfg.zotero.library_id
    if key := os.environ.get("ZOTERO_LIBRARY_ID"):
        return key
    return ""


def resolve_mineru(cfg: HasMinerU) -> str:
    """Resolve MinerU API key."""
    if cfg.ingest.mineru_api_key:
        return cfg.ingest.mineru_api_key
    if key := os.environ.get("MINERU_API_KEY"):
        return key
    return ""


# Config Dataclasses


@dataclass(frozen=True)
class PathsConfig:
    """Path configuration."""

    papers_dir: str = "data/papers"
    index_db: str = "data/index.db"


@dataclass(frozen=True)
class LLMConfig:
    """LLM backend configuration."""

    backend: str = "openai-compat"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    timeout: int = 30
    timeout_toc: int = 120
    timeout_clean: int = 90


@dataclass(frozen=True)
class SearchConfig:
    """FTS5 search configuration."""

    top_k: int = 20


@dataclass(frozen=True)
class EmbedConfig:
    """Embedding configuration."""

    model: str = "Qwen/Qwen3-Embedding-0.6B"
    cache_dir: str = "~/.cache/modelscope/hub/models"
    device: str = "auto"
    top_k: int = 10
    source: str = "modelscope"


@dataclass(frozen=True)
class TopicsConfig:
    """BERTopic configuration."""

    min_topic_size: int = 5
    nr_topics: int = 0  # 0 = auto
    model_dir: str = "data/topic_model"


@dataclass(frozen=True)
class LogConfig:
    """Logging configuration."""

    level: str = "INFO"
    file: str = "data/scholaraio.log"
    max_bytes: int = 10_000_000
    backup_count: int = 3
    metrics_db: str = "data/metrics.db"


@dataclass(frozen=True)
class IngestConfig:
    """Ingestion pipeline configuration."""

    extractor: str = "robust"  # regex | auto | llm | robust
    mineru_endpoint: str = "http://localhost:8000"
    mineru_cloud_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""
    abstract_llm_mode: str = "verify"  # off | fallback | verify
    contact_email: str = ""


@dataclass(frozen=True)
class ZoteroConfig:
    """Zotero integration."""

    api_key: str = ""
    library_id: str = ""
    library_type: str = "user"


# Main Config


@dataclass
class Config:
    """ScholarAIO global configuration."""

    paths: PathsConfig = field(default_factory=PathsConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    topics: TopicsConfig = field(default_factory=TopicsConfig)
    log: LogConfig = field(default_factory=LogConfig)
    zotero: ZoteroConfig = field(default_factory=ZoteroConfig)

    _root: Path = field(default_factory=Path.cwd, repr=False, compare=False)

    # Path Properties

    @property
    def papers_dir(self) -> Path:
        return (self._root / self.paths.papers_dir).resolve()

    @property
    def index_db(self) -> Path:
        return (self._root / self.paths.index_db).resolve()

    @property
    def log_file(self) -> Path:
        return (self._root / self.log.file).resolve()

    @property
    def metrics_db_path(self) -> Path:
        return (self._root / self.log.metrics_db).resolve()

    @property
    def topics_model_dir(self) -> Path:
        return (self._root / self.topics.model_dir).resolve()

    # Directory Management

    def ensure_dirs(self) -> None:
        """Create required directories."""
        for d in (
            self.papers_dir,
            self._root / "data" / "inbox",
            self._root / "data" / "pending",
            self._root / "workspace",
            self.log_file.parent,
            self.metrics_db_path.parent,
        ):
            d.mkdir(parents=True, exist_ok=True)


# Environment overrides - mapping-based


_ENV_OVERRIDES: dict[str, tuple[str, list[str]]] = {
    "paths": ("PATH", ["papers_dir", "index_db"]),
    "llm": ("LLM", ["api_key", "backend", "model", "base_url"]),
    "ingest": ("MINERU", ["mineru_api_key", "mineru_endpoint"]),
    "embed": ("EMBED", ["model", "source"]),
    "log": ("LOG", ["level"]),
}


def load_config(config_path: Path | None = None) -> Config:
    """Load and merge YAML configuration files.

    Priority (high to low):
    1. Environment variables SCHOLARAIO_*
    2. config.local.yaml
    3. config.yaml
    4. Code defaults
    """
    import yaml

    # Find config file
    if config_path is None:
        config_path = _find_config_file()

    data: dict = {}
    root = Path.cwd()

    if config_path and config_path.exists():
        root = config_path.parent
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Local overrides
        local_path = config_path.parent / "config.local.yaml"
        if local_path.exists():
            with open(local_path, encoding="utf-8") as f:
                local_data = yaml.safe_load(f) or {}
            data = _deep_merge(data, local_data)

    cfg = _build_config(data, root)
    _apply_env_overrides(cfg)
    return cfg


def _find_config_file() -> Path | None:
    """Walk up from cwd to find config.yaml."""
    current = Path.cwd()
    for _ in range(6):
        candidate = current / "config.yaml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _apply_env_overrides(cfg: Config) -> None:
    """Apply environment variable overrides using mapping."""
    # Root override
    if root := os.environ.get(f"{ENV_PREFIX}ROOT"):
        cfg._root = Path(root).resolve()

    # Section-based overrides
    for section, (env_prefix, fields) in _ENV_OVERRIDES.items():
        section_obj = getattr(cfg, section, None)
        if section_obj is None:
            continue
        for fld in fields:
            env_key = f"{ENV_PREFIX}{env_prefix}_{fld}"
            if val := os.environ.get(env_key):
                setattr(section_obj, fld, val)


# Loader


def _build_config(data: dict, root: Path) -> Config:
    """Build Config from dict."""
    return Config(
        paths=PathsConfig(**data.get("paths", {})),
        llm=LLMConfig(**data.get("llm", {})),
        ingest=IngestConfig(**data.get("ingest", {})),
        embed=EmbedConfig(**data.get("embed", {})),
        search=SearchConfig(**data.get("search", {})),
        topics=TopicsConfig(**data.get("topics", {})),
        log=LogConfig(**data.get("logging", {})),
        zotero=ZoteroConfig(**data.get("zotero", {})),
        _root=root,
    )
