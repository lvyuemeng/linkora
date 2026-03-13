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

Workspace: Storage paths are derived from workspace identity in config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


ENV_PREFIX = "SCHOLARAIO_"


# Config Dataclasses


@dataclass(frozen=True)
class WorkspaceConfig:
    """Workspace identity - determines storage location."""

    name: str = "default"
    description: str = ""


@dataclass(frozen=True)
class IndexConfig:
    """Index module configuration (FTS + Vector)."""

    # FTS
    top_k: int = 20
    # Vector
    embed_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embed_device: str = "auto"
    embed_cache: str = "~/.cache/modelscope/hub/models"
    embed_top_k: int = 10
    embed_source: str = "modelscope"
    # Chunking (for L3 content)
    chunk_size: int = 800
    chunk_overlap: int = 150


@dataclass(frozen=True)
class SourcesConfig:
    """Data source configuration."""

    # Local
    local_enabled: bool = True
    # OpenAlex
    openalex_enabled: bool = True
    # Zotero
    zotero_enabled: bool = False
    zotero_library_id: str = ""
    zotero_api_key: str = ""
    zotero_library_type: str = "user"
    # Endnote
    endnote_enabled: bool = True


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
class IngestConfig:
    """PDF ingestion configuration."""

    # Extractor
    extractor: str = "robust"  # regex | auto | llm | robust
    # MinerU
    mineru_endpoint: str = "http://localhost:8000"
    mineru_cloud_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""
    # LLM Abstract
    abstract_llm_mode: str = "verify"  # off | fallback | verify
    contact_email: str = ""


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


# Main Config


@dataclass
class Config:
    """ScholarAIO global configuration."""

    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    topics: TopicsConfig = field(default_factory=TopicsConfig)
    log: LogConfig = field(default_factory=LogConfig)

    _root: Path = field(default_factory=Path.cwd, repr=False, compare=False)

    # Path Properties (derived from workspace)

    @property
    def workspace_dir(self) -> Path:
        """Workspace directory - derived from workspace identity."""
        return (self._root / "workspace" / self.workspace.name).resolve()

    @property
    def papers_dir(self) -> Path:
        return (self.workspace_dir / "papers").resolve()

    @property
    def index_db(self) -> Path:
        return (self.workspace_dir / "index.db").resolve()

    @property
    def vectors_file(self) -> Path:
        return (self.workspace_dir / "vectors.faiss").resolve()

    @property
    def vector_ids_file(self) -> Path:
        return (self.workspace_dir / "vector_ids.json").resolve()

    @property
    def log_file(self) -> Path:
        return (self._root / self.log.file).resolve()

    @property
    def metrics_db_path(self) -> Path:
        return (self._root / self.log.metrics_db).resolve()

    @property
    def topics_model_dir(self) -> Path:
        return (self._root / self.topics.model_dir).resolve()

    # API key resolution

    def resolve_llm_api_key(self) -> str:
        """Resolve LLM API key: config > SCHOLARAIO_LLM_API_KEY > DEEPSEEK_API_KEY > OPENAI_API_KEY."""
        if self.llm.api_key:
            return self.llm.api_key
        if key := os.environ.get("SCHOLARAIO_LLM_API_KEY"):
            return key
        if key := os.environ.get("DEEPSEEK_API_KEY"):
            return key
        if key := os.environ.get("OPENAI_API_KEY"):
            return key
        return ""

    def resolve_zotero_api_key(self) -> str:
        """Resolve Zotero API key."""
        if self.sources.zotero_api_key:
            return self.sources.zotero_api_key
        if key := os.environ.get("ZOTERO_API_KEY"):
            return key
        return ""

    def resolve_zotero_library_id(self) -> str:
        """Resolve Zotero library ID."""
        if self.sources.zotero_library_id:
            return self.sources.zotero_library_id
        if key := os.environ.get("ZOTERO_LIBRARY_ID"):
            return key
        return ""

    def resolve_mineru_api_key(self) -> str:
        """Resolve MinerU API key."""
        if self.ingest.mineru_api_key:
            return self.ingest.mineru_api_key
        if key := os.environ.get("MINERU_API_KEY"):
            return key
        return ""

    # Directory Management

    def ensure_dirs(self) -> None:
        """Create required directories."""
        for d in (
            self.workspace_dir,
            self.papers_dir,
            self._root / "data" / "inbox",
            self._root / "data" / "pending",
            self.log_file.parent,
            self.metrics_db_path.parent,
            self.topics_model_dir.parent,
        ):
            d.mkdir(parents=True, exist_ok=True)


# Environment overrides - mapping-based


_ENV_OVERRIDES: dict[str, tuple[str, list[str]]] = {
    "workspace": ("WORKSPACE", ["name", "description"]),
    "index": ("INDEX", ["top_k", "embed_model", "embed_device", "chunk_size", "chunk_overlap"]),
    "sources": ("SOURCES", ["zotero_api_key", "zotero_library_id"]),
    "llm": ("LLM", ["api_key", "backend", "model", "base_url"]),
    "ingest": ("MINERU", ["mineru_api_key", "mineru_endpoint"]),
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
        workspace=WorkspaceConfig(**data.get("workspace", {})),
        index=IndexConfig(**data.get("index", {})),
        sources=SourcesConfig(**data.get("sources", {})),
        ingest=IngestConfig(**data.get("ingest", {})),
        llm=LLMConfig(**data.get("llm", {})),
        topics=TopicsConfig(**data.get("topics", {})),
        log=LogConfig(**data.get("logging", {})),
        _root=root,
    )
