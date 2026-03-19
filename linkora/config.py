"""
config.py — linkora configuration loading and management

Layered resolution (priority top → bottom):
1. CLI argument (--workspace)
2. Environment variables (linkora_WORKSPACE)
3. Workspace-local config (<workspace>/linkora.yml)
4. Global config (~/.linkora/config.yml, ~/.config/linkora/config.yml)
5. Built-in defaults
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


ENV_PREFIX = "linkora_"


# ============== Config Dataclasses ==============


@dataclass(frozen=True)
class WorkspaceConfig:
    name: str = "default"
    description: str = ""
    root: str = ""  # Optional override for workspace root


@dataclass(frozen=True)
class LocalSourceConfig:
    enabled: bool = True
    papers_dir: str = "papers"
    paths: list[str] = field(default_factory=list)  # Additional paper paths


@dataclass(frozen=True)
class ArxivSourceConfig:
    enabled: bool = False


@dataclass(frozen=True)
class OpenAlexSourceConfig:
    enabled: bool = False


@dataclass(frozen=True)
class ZoteroSourceConfig:
    enabled: bool = False
    library_id: str = ""
    api_key: str = ""
    library_type: str = "user"


@dataclass(frozen=True)
class EndnoteSourceConfig:
    enabled: bool = True


@dataclass(frozen=True)
class SourcesConfig:
    local: LocalSourceConfig = field(default_factory=LocalSourceConfig)
    arxiv: ArxivSourceConfig = field(default_factory=ArxivSourceConfig)
    openalex: OpenAlexSourceConfig = field(default_factory=OpenAlexSourceConfig)
    zotero: ZoteroSourceConfig = field(default_factory=ZoteroSourceConfig)
    endnote: EndnoteSourceConfig = field(default_factory=EndnoteSourceConfig)


@dataclass(frozen=True)
class IndexConfig:
    top_k: int = 20
    embed_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embed_device: str = "auto"
    embed_cache: str = "~/.cache/modelscope/hub/models"
    embed_top_k: int = 10
    embed_source: str = "modelscope"
    chunk_size: int = 800
    chunk_overlap: int = 150


@dataclass(frozen=True)
class LLMConfig:
    """LLM client configuration."""

    backend: str = "openai-compat"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    timeout: int = 30
    timeout_toc: int = 120
    timeout_clean: int = 90

    def resolve_api_key(self) -> str:
        """Resolve API key with environment variable fallback."""
        import os

        return (
            self.api_key
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )


@dataclass(frozen=True)
class IngestConfig:
    extractor: str = "robust"
    mineru_endpoint: str = "http://localhost:8000"
    mineru_cloud_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""
    abstract_llm_mode: str = "verify"
    contact_email: str = ""


@dataclass(frozen=True)
class TopicsConfig:
    min_topic_size: int = 5
    nr_topics: int = 0
    model_dir: str = "topic_model"


@dataclass(frozen=True)
class LogConfig:
    level: str = "INFO"
    file: str = "linkora.log"
    max_bytes: int = 10_000_000
    backup_count: int = 3
    metrics_db: str = "metrics.db"


# ============== Data Pipe Functions ==============


def _load_yaml(path: Path | None) -> dict:
    if path and path.exists():
        import yaml

        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _merge_dicts(*dicts: dict) -> dict:
    """Deep merge dicts (rightmost has highest priority)."""
    result = {}
    for d in dicts:
        for k, v in d.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = _merge_dicts(result[k], v)
            else:
                result[k] = v
    return result


def _find_root() -> Path:
    """Find root directory for the application.

    Priority (highest to lowest):
    1. CLI argument (--workspace)
    2. Environment variable (linkora_ROOT)
    3. Project markers (.linkora, workspace/, config.yaml) walking up from cwd
    4. Platform-specific user data directory (default for installed CLI)

    User data directories:
    - Linux/macOS: ~/.local/share/linkora
    - Windows: %APPDATA%/linkora
    """
    # First check environment variable
    env_root = os.environ.get(f"{ENV_PREFIX}ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    # Walk up from current directory looking for project markers
    current = Path.cwd()
    for _ in range(6):
        if (current / ".linkora").exists() or (current / "workspace").exists():
            return current
        if (current / "config.yaml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Fall back to platform-specific user data directory
    # This is suitable for CLI tools installed in binary path
    return _get_user_data_dir()


def _get_user_data_dir() -> Path:
    """Get platform-specific user data directory for CLI tool.

    Returns:
        - Linux: ~/.local/share/linkora
        - macOS: ~/Library/Application Support/linkora
        - Windows: %APPDATA%/linkora
    """
    import platform

    system = platform.system()
    home = Path.home()

    if system == "Windows":
        # Windows: %APPDATA% (typically C:\Users\<user>\AppData\Roaming)
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "linkora"
        return home / "AppData" / "Roaming" / "linkora"
    elif system == "Darwin":
        # macOS: ~/Library/Application Support/linkora
        return home / "Library" / "Application Support" / "linkora"
    else:
        # Linux and others: ~/.local/share/linkora
        # (follows XDG Base Directory Specification)
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            return Path(xdg_data) / "linkora"
        return home / ".local" / "share" / "linkora"


def _config_paths(root: Path) -> Iterator[Path]:
    home = Path.home()
    yield home / ".linkora" / "config.yml"
    yield home / ".config" / "linkora" / "config.yml"
    yield root / "config.yaml"


def _resolve_workspace(data: dict, cli_ws: str | None, env_ws: str | None) -> str:
    return cli_ws or env_ws or data.get("default_workspace", "default")


# ============== Config Builder ==============


def _build_sources(data: dict) -> SourcesConfig:
    return SourcesConfig(
        local=LocalSourceConfig(**data.get("local", {})),
        arxiv=ArxivSourceConfig(**data.get("arxiv", {})),
        openalex=OpenAlexSourceConfig(**data.get("openalex", {})),
        zotero=ZoteroSourceConfig(**data.get("zotero", {})),
        endnote=EndnoteSourceConfig(**data.get("endnote", {})),
    )


# ============== Main Pipeline ==============


def _load(workspace: str | None = None, root: Path | None = None) -> "Config":
    root = root or _find_root()
    env_ws = os.environ.get(f"{ENV_PREFIX}WORKSPACE")

    # Collect layers
    layers = [_load_yaml(p) for p in _config_paths(root)]
    data = _merge_dicts(*layers) if layers else {}

    # Workspace-local override
    ws_name = _resolve_workspace(data, workspace, env_ws)
    ws_data = _load_yaml(root / "workspace" / ws_name / "linkora.yml")
    merged = _merge_dicts(data, ws_data) if ws_data else data

    # Build workspace store
    ws_store = {
        name: WorkspaceConfig(
            name=name,
            description=(
                entry if isinstance(entry, str) else entry.get("description", "")
            )
            if entry
            else "",
        )
        for name, entry in merged.get("workspace", {}).items()
    }

    # Resolve current workspace
    ws_entry = ws_store.get(ws_name, WorkspaceConfig(name=ws_name))

    return Config(
        workspace=WorkspaceConfig(name=ws_name, description=ws_entry.description),
        workspace_store=ws_store,
        default_workspace=merged.get("default_workspace", "default"),
        sources=_build_sources(merged.get("sources", {})),
        index=IndexConfig(**merged.get("index", {})),
        llm=LLMConfig(**merged.get("llm", {})),
        ingest=IngestConfig(**merged.get("ingest", {})),
        topics=TopicsConfig(**merged.get("topics", {})),
        log=LogConfig(**merged.get("logging", {})),
        _root=root,
    )


# ============== Config Class ==============


@dataclass
class Config:
    """linkora configuration."""

    workspace: WorkspaceConfig
    workspace_store: dict[str, WorkspaceConfig]
    default_workspace: str
    sources: SourcesConfig
    index: IndexConfig
    llm: LLMConfig
    ingest: IngestConfig
    topics: TopicsConfig
    log: LogConfig
    _root: Path = field(default_factory=Path.cwd)

    # Path Properties
    @property
    def root(self) -> Path:
        """Get root path - uses workspace override if set."""
        if self.workspace.root:
            return Path(self.workspace.root).resolve()
        return self._root

    @property
    def workspace_dir(self) -> Path:
        return self.root / "workspace" / self.workspace.name

    @property
    def papers_store_dir(self) -> Path:
        # Papers store directory - where linkora manages papers
        return self.workspace_dir / "papers"

    @property
    def index_db(self) -> Path:
        return self.workspace_dir / "index.db"

    @property
    def vectors_file(self) -> Path:
        return self.workspace_dir / "vectors.faiss"

    @property
    def log_file(self) -> Path:
        return self._root / self.log.file

    @property
    def metrics_db_path(self) -> Path:
        return self._root / self.log.metrics_db

    # API key resolution
    def resolve_llm_api_key(self) -> str:
        return (
            self.llm.api_key
            or os.environ.get(f"{ENV_PREFIX}LLM_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )

    def resolve_zotero_api_key(self) -> str:
        return self.sources.zotero.api_key or os.environ.get("ZOTERO_API_KEY") or ""

    def resolve_zotero_library_id(self) -> str:
        return (
            self.sources.zotero.library_id or os.environ.get("ZOTERO_LIBRARY_ID") or ""
        )

    def resolve_mineru_api_key(self) -> str:
        return self.ingest.mineru_api_key or os.environ.get("MINERU_API_KEY") or ""

    def ensure_dirs(self) -> None:
        for d in (
            self.workspace_dir,
            self.papers_store_dir,
            self.log_file.parent,
            self.metrics_db_path.parent,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def resolve_local_source_dir(self) -> Path | None:
        """Resolve the local source PDF directory from config.

        Returns:
            Path to local source directory, or None if not configured
        """
        if not self.sources.local.enabled:
            return None

        local_path = self.sources.local.papers_dir
        if not local_path:
            return None

        # Resolve relative to workspace root
        path = Path(local_path)
        if path.is_absolute():
            return path.resolve()
        return (self.root / path).resolve()


# ============== Singleton ==============


_config_singleton: Config | None = None


def get_config() -> Config:
    """Get config singleton."""
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = _load()
    return _config_singleton


def reload_config(workspace: str | None = None) -> Config:
    """Force reload config."""
    global _config_singleton
    _config_singleton = _load(workspace=workspace)
    return _config_singleton


def load_config(workspace: str | None = None, root: Path | None = None) -> Config:
    """Load configuration."""
    return _load(workspace=workspace, root=root)
