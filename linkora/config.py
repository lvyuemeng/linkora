"""
config.py — linkora application configuration

Resolution (exactly ONE file wins — no merging between global locations):

    Priority   Path
    ────────   ────────────────────────────────────────
    highest    ~/.linkora/config.yml          (user home)
    lower      ~/.config/linkora/config.yml   (XDG standard)
    fallback   built-in defaults

If both files exist the higher-priority one wins entirely and a warning
is emitted.  The set of all existing candidate files is exposed so that
`linkora doctor` can surface the conflict to the user.

There is NO workspace-local config override.  Per-workspace settings
are not supported; use the global config for all settings.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENV_PREFIX = "LINKORA_"
_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")

# Ordered from lowest to highest priority.
# The LAST existing file in this list wins.
_CANDIDATE_PATHS: tuple[Path, ...] = (
    Path.home() / ".config" / "linkora" / "config.yml",
    Path.home() / ".linkora" / "config.yml",
)


# ---------------------------------------------------------------------------
# Sub-config models  (pure Pydantic — NO @dataclass decorator)
# ---------------------------------------------------------------------------


class LocalSourceConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = True
    paths: list[str] = Field(default_factory=list)


class ArxivSourceConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False


class OpenAlexSourceConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False


class ZoteroSourceConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False
    library_id: str = ""
    api_key: str = ""
    library_type: str = "user"


class EndnoteSourceConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = True


class SourcesConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    local: LocalSourceConfig = Field(default_factory=LocalSourceConfig)
    arxiv: ArxivSourceConfig = Field(default_factory=ArxivSourceConfig)
    openalex: OpenAlexSourceConfig = Field(default_factory=OpenAlexSourceConfig)
    zotero: ZoteroSourceConfig = Field(default_factory=ZoteroSourceConfig)
    endnote: EndnoteSourceConfig = Field(default_factory=EndnoteSourceConfig)


class IndexConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    top_k: int = 20
    embed_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embed_device: str = "auto"
    embed_cache: str = "~/.cache/modelscope/hub/models"
    embed_top_k: int = 10
    embed_source: str = "modelscope"
    chunk_size: int = 800
    chunk_overlap: int = 150


class LLMConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    backend: str = "openai-compat"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    timeout: int = 30
    timeout_toc: int = 120
    timeout_clean: int = 90


class IngestConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    extractor: str = "robust"
    mineru_endpoint: str = "http://localhost:8000"
    mineru_cloud_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""
    abstract_llm_mode: str = "verify"
    contact_email: str = ""


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
    metrics_db: str = "metrics.db"


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
    llm: LLMConfig = Field(default_factory=LLMConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    topics: TopicsConfig = Field(default_factory=TopicsConfig)
    log: LogConfig = Field(default_factory=LogConfig)

    # ------------------------------------------------------------------
    # Key resolution  (environment variable fallbacks)
    # ------------------------------------------------------------------

    def resolve_llm_api_key(self) -> str:
        return (
            self.llm.api_key
            or os.environ.get(f"{ENV_PREFIX}LLM_API_KEY", "")
            or os.environ.get("DEEPSEEK_API_KEY", "")
            or os.environ.get("OPENAI_API_KEY", "")
        )

    def resolve_zotero_api_key(self) -> str:
        return self.sources.zotero.api_key or os.environ.get("ZOTERO_API_KEY", "")

    def resolve_zotero_library_id(self) -> str:
        return self.sources.zotero.library_id or os.environ.get("ZOTERO_LIBRARY_ID", "")

    def resolve_mineru_api_key(self) -> str:
        return self.ingest.mineru_api_key or os.environ.get("MINERU_API_KEY", "")

    def resolve_local_source_paths(self, config_dir: Path) -> list[Path]:
        """
        Resolve additional local source paths relative to *config_dir*.

        config_dir must be passed explicitly — AppConfig never stores the
        path of the file it was loaded from.  Absolute paths in the config
        are used as-is.
        """
        if not self.sources.local.enabled:
            return []

        result: list[Path] = []
        for raw in self.sources.local.paths:
            if not raw:
                continue
            p = Path(raw)
            result.append(p if p.is_absolute() else (config_dir / p).resolve())
        return result


# ---------------------------------------------------------------------------
# Internal YAML / env helpers
# ---------------------------------------------------------------------------


def _expand_env(value: str) -> str:
    """Expand ``${VAR}`` and ``${VAR:-fallback}`` in a string."""

    def _sub(m: re.Match) -> str:
        name, fallback = m.group(1), m.group(2)
        return os.environ.get(name) or fallback or ""

    return _ENV_PATTERN.sub(_sub, value)


def _resolve_env(obj: Any) -> Any:
    """Recursively expand environment variable references."""
    if isinstance(obj, str):
        return _expand_env(obj)
    if isinstance(obj, dict):
        return {k: _resolve_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env(v) for v in obj]
    return obj


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        from linkora.log import get_logger

        get_logger(__name__).warning("Failed to load %s: %s", path, exc)
        return {}


def _build_config(data: dict[str, Any]) -> AppConfig:
    """Construct AppConfig from a raw (already env-resolved) dict."""
    src = data.get("sources", {})
    return AppConfig(
        sources=SourcesConfig(
            local=LocalSourceConfig(**src.get("local", {})),
            arxiv=ArxivSourceConfig(**src.get("arxiv", {})),
            openalex=OpenAlexSourceConfig(**src.get("openalex", {})),
            zotero=ZoteroSourceConfig(**src.get("zotero", {})),
            endnote=EndnoteSourceConfig(**src.get("endnote", {})),
        ),
        index=IndexConfig(**data.get("index", {})),
        llm=LLMConfig(**data.get("llm", {})),
        ingest=IngestConfig(**data.get("ingest", {})),
        topics=TopicsConfig(**data.get("topics", {})),
        log=LogConfig(**data.get("logging", {})),
    )


# ---------------------------------------------------------------------------
# ConfigLoader  — the public API for finding and loading config
# ---------------------------------------------------------------------------


class ConfigLoader:
    """
    Discovers and loads the active global configuration file.

    The loader intentionally does NOT merge multiple config files.
    Exactly one file wins; all others are ignored (with a warning).
    This makes the resolution unambiguous and easy to reason about.

    Use ``find_all()`` to get every candidate that currently exists on
    disk — useful for ``linkora doctor`` to flag conflicts.
    """

    @staticmethod
    def candidates() -> tuple[Path, ...]:
        """All candidate paths, lowest priority first."""
        return _CANDIDATE_PATHS

    @staticmethod
    def find_all() -> list[Path]:
        """Return every candidate file that currently exists on disk."""
        return [p for p in _CANDIDATE_PATHS if p.exists()]

    @staticmethod
    def active_path() -> Path | None:
        """
        Return the single highest-priority config file that exists.
        Returns None when no config file is found at any location.
        """
        # Walk in reverse: last item in _CANDIDATE_PATHS is highest priority.
        for path in reversed(_CANDIDATE_PATHS):
            if path.exists():
                return path
        return None

    @staticmethod
    def default_write_path() -> Path:
        """
        The canonical path for writing a new or updated config file.
        Always the highest-priority location regardless of what exists.
        """
        return _CANDIDATE_PATHS[-1]  # ~/.linkora/config.yml

    def load(self) -> tuple[AppConfig, Path | None]:
        """
        Load config from the active file.

        Returns:
            (AppConfig, active_path)  where active_path is None when no
            config file was found and built-in defaults are used.

        Emits a warning when multiple candidate files exist because the
        ignored lower-priority file(s) may confuse users.
        """
        from linkora.log import get_logger

        log = get_logger(__name__)

        existing = self.find_all()

        if not existing:
            log.info("No config file found; using built-in defaults.")
            return AppConfig(), None

        if len(existing) > 1:
            # The last (highest priority) wins; warn about the rest.
            ignored = existing[:-1]
            log.warning(
                "Multiple config files found. '%s' is active; ignoring: %s. "
                "Remove the ignored file(s) to silence this warning.",
                existing[-1],
                ", ".join(str(p) for p in ignored),
            )

        active = existing[-1]
        log.debug("Loading config from %s", active)

        raw = _load_yaml(active)
        resolved = _resolve_env(raw)
        return _build_config(resolved), active


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_config: AppConfig | None = None
_config_path: Path | None = None
_config_loaded: bool = False


def get_config() -> AppConfig:
    """Return the process-wide AppConfig singleton."""
    _ensure_loaded()
    return _config  # type: ignore[return-value]


def get_config_path() -> Path | None:
    """
    Return the path of the active config file, or None if defaults are used.
    Use this when resolving relative paths from config values.
    """
    _ensure_loaded()
    return _config_path


def get_config_dir() -> Path:
    """
    Return the directory of the active config file.
    Falls back to the default write location's parent when no file exists.
    """
    path = get_config_path()
    return path.parent if path else ConfigLoader.default_write_path().parent


def _ensure_loaded() -> None:
    global _config, _config_path, _config_loaded
    if not _config_loaded:
        _config, _config_path = ConfigLoader().load()
        _config_loaded = True


def reset_config() -> None:
    """Reset the singleton — intended for tests only."""
    global _config, _config_path, _config_loaded
    _config = None
    _config_path = None
    _config_loaded = False


__all__ = [
    "AppConfig",
    "ConfigLoader",
    "LocalSourceConfig",
    "ArxivSourceConfig",
    "OpenAlexSourceConfig",
    "ZoteroSourceConfig",
    "EndnoteSourceConfig",
    "SourcesConfig",
    "IndexConfig",
    "LLMConfig",
    "IngestConfig",
    "TopicsConfig",
    "LogConfig",
    "get_config",
    "get_config_path",
    "get_config_dir",
    "reset_config",
]
