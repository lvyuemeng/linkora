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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


ENV_PREFIX = "linkora_"

# Workspace fields can only be defined in global config
WORKSPACE_FIELDS = {"workspace", "default_workspace"}
# Workspace-local config can only override these fields
ALLOWED_WORKSPACE_LOCAL = {"sources"}


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
    """Load YAML file, trying .yaml and .yml extensions.

    Args:
        path: Path to config file (without extension)

    Returns:
        Loaded config dict, or empty dict if not found
    """
    if not path:
        return {}

    # Try .yaml first, then .yml
    yaml_path = Path(str(path) + ".yaml")
    yml_path = Path(str(path) + ".yml")

    actual_path = None
    if yaml_path.exists():
        actual_path = yaml_path
    elif yml_path.exists():
        actual_path = yml_path

    if actual_path:
        import yaml

        with open(actual_path, encoding="utf-8") as f:
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

    Priority:
    1. Environment variable (linkora_ROOT)
    2. Platform-specific user data directory

    Raises warning if both env and default data dir have config files (collision).
    """
    import logging

    _log = logging.getLogger(__name__)

    # Check environment variable
    env_root = os.environ.get(f"{ENV_PREFIX}ROOT")
    if env_root:
        env_path = Path(env_root).expanduser().resolve()

        # Check if default data dir also has config (collision warning)
        default_dir = _get_user_data_dir()
        has_env_config = (env_path / "config.yaml").exists() or (
            env_path / "config.yml"
        ).exists()
        has_default_config = (default_dir / "config.yaml").exists() or (
            default_dir / "config.yml"
        ).exists()

        if has_env_config and has_default_config:
            _log.warning(
                "Config in both env root (%s) and default data dir (%s). "
                "Using env root.",
                env_path,
                default_dir,
            )

        return env_path

    # Use platform-specific user data directory
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


def _load_env(config_path: Path) -> dict[str, str]:
    """Load .env file from config directory.

    Args:
        config_path: Path to config.yaml

    Returns:
        Dict of environment variables
    """
    env_path = config_path.parent / ".env"

    if not env_path.exists():
        return {}

    values: dict[str, str] = {}

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

    return values


def _resolve_string(value: str, env: dict[str, str]) -> str:
    """Resolve environment variables in a string."""
    pattern = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")

    def replacer(match):
        var_name = match.group(1)
        fallback = match.group(2)
        return env.get(var_name) or os.environ.get(var_name, "") or fallback or ""

    return pattern.sub(replacer, value)


def _resolve_dict(data: dict, env: dict[str, str]) -> dict:
    """Resolve environment variables in a dict."""
    return {k: _resolve_value(v, env) for k, v in data.items()}


def _resolve_list(items: list, env: dict[str, str]) -> list:
    """Resolve environment variables in a list."""
    return [_resolve_value(item, env) for item in items]


def _resolve_value(obj: str | dict | list, env: dict[str, str]) -> str | dict | list:
    """Resolve environment variables in any value."""
    if isinstance(obj, str):
        return _resolve_string(obj, env)
    if isinstance(obj, dict):
        return _resolve_dict(obj, env)
    if isinstance(obj, list):
        return _resolve_list(obj, env)
    return obj


def _resolve_env_vars(data: dict, env: dict[str, str]) -> dict:
    """Resolve ${VAR} and ${VAR:-fallback} in data.

    Pure function - no side effects.
    """
    return _resolve_dict(data, env)


def _config_paths(root: Path) -> Iterator[tuple[Path, str]]:
    """Yield config paths with scope info.

    Only global configs: XDG and user home.
    Project config removed - use env var or default data dir.

    Yields:
        (path, scope) tuples: "xdg", "user"

    Note: Warns if multiple global configs exist.
    """
    import logging

    _log = logging.getLogger(__name__)
    home = Path.home()

    # Check for both .yaml and .yml extensions
    def find_config(base_path: Path) -> Path | None:
        yaml_path = Path(str(base_path) + ".yaml")
        yml_path = Path(str(base_path) + ".yml")
        if yaml_path.exists():
            return yaml_path
        if yml_path.exists():
            return yml_path
        return None

    found_xdg = False

    # XDG config (~/.config/linkora/config)
    xdg_path = find_config(home / ".config" / "linkora" / "config")
    if xdg_path:
        found_xdg = True
        yield xdg_path, "xdg"

    # User config (~/.linkora/config)
    user_path = find_config(home / ".linkora" / "config")
    if user_path:
        if found_xdg:
            # Warn about duplicate
            _log.warning(
                "Multiple global configs: using %s (also found %s)", user_path, xdg_path
            )
        yield user_path, "user"

    # No project config - removed per design decision


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

    # Collect and merge configs
    merged: dict = {}
    config_root = root  # Will be updated based on loaded configs

    for path, scope in _config_paths(root):
        config_root = path.parent  # Use highest priority config's directory
        env = _load_env(path)
        data = _load_yaml(path)
        data = _resolve_env_vars(data, env)
        merged = _merge_dicts(merged, data)

    # Extract workspace config (GLOBAL ONLY - no workspace-local override)
    workspace_data = {k: v for k, v in merged.items() if k in WORKSPACE_FIELDS}
    other_data = {k: v for k, v in merged.items() if k not in WORKSPACE_FIELDS}

    # Determine workspace name
    ws_name = workspace or env_ws or workspace_data.get("default_workspace", "default")

    # Load workspace-local config (ONLY sources can override)
    sources_data = other_data.get("sources", {})
    ws_local_path = root / "workspace" / ws_name / "linkora.yml"

    if ws_local_path.exists():
        env = _load_env(ws_local_path)
        ws_local_data = _load_yaml(ws_local_path)
        ws_local_data = _resolve_env_vars(ws_local_data, env)

        # Check for disallowed fields
        import logging

        _log = logging.getLogger(__name__)
        disallowed = set(ws_local_data.keys()) - ALLOWED_WORKSPACE_LOCAL
        if disallowed:
            _log.warning(
                "Workspace-local '%s' contains non-source fields: %s. "
                "Only 'sources' can be overridden per-workspace.",
                ws_local_path,
                list(disallowed),
            )

        # Only allow sources override
        local_sources = ws_local_data.get("sources", {})
        sources_data = _merge_dicts(sources_data, local_sources)

    # Build workspace store (from global only)
    ws_store = {
        name: WorkspaceConfig(
            name=name,
            description=(
                entry if isinstance(entry, str) else entry.get("description", "")
            )
            if entry
            else "",
        )
        for name, entry in workspace_data.get("workspace", {}).items()
    }

    # Resolve current workspace
    ws_entry = ws_store.get(ws_name, WorkspaceConfig(name=ws_name))

    return Config(
        workspace=WorkspaceConfig(name=ws_name, description=ws_entry.description),
        workspace_store=ws_store,
        default_workspace=workspace_data.get("default_workspace", "default"),
        sources=_build_sources(sources_data),
        index=IndexConfig(**other_data.get("index", {})),
        llm=LLMConfig(**other_data.get("llm", {})),
        ingest=IngestConfig(**other_data.get("ingest", {})),
        topics=TopicsConfig(**other_data.get("topics", {})),
        log=LogConfig(**other_data.get("logging", {})),
        _root=root,
        _config_root=config_root,
    )


# ============== Config Class ==============


@dataclass
class Config:
    """linkora configuration.

    Invariant: Directories are created on init.
    """

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
    _config_root: Path = field(
        default_factory=Path.cwd
    )  # Config file location for path resolution

    def __post_init__(self) -> None:
        """Ensure required directories exist (invariant)."""
        self.ensure_dirs()

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

    def resolve_local_source_paths(self) -> list[Path]:
        """Resolve all local source paths from config.

        Returns:
            List of paths: papers_dir + additional paths.
            Resolved relative to config file root, NOT workspace root.
        """
        if not self.sources.local.enabled:
            return []

        paths: list[Path] = []

        # Primary papers_dir
        primary = self.sources.local.papers_dir
        if primary:
            p = Path(primary)
            if p.is_absolute():
                paths.append(p.resolve())
            else:
                paths.append((self._config_root / p).resolve())

        # Additional paths
        for path_str in self.sources.local.paths:
            if path_str:
                p = Path(path_str)
                if p.is_absolute():
                    paths.append(p.resolve())
                else:
                    paths.append((self._config_root / p).resolve())

        return paths


# ============== Singleton ==============


_config_singleton: Config | None = None


def get_config() -> Config:
    """Get config singleton (creates directories on first call)."""
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = _load()
    return _config_singleton
