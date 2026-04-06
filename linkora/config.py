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
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from linkora.paths import get_config_path as _get_config_path, get_config_candidates

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENV_PREFIX = "LINKORA_"
_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


VALID_CONFIG_SECTIONS = {
    "sources",
    "index",
    "extract",
    "tidy",
    "llm",
    "topics",
    "log",
}


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


def _set_nested(doc: Any, parts: list[str], value: Any) -> None:
    current = doc
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _get_nested(doc: dict, parts: list[str]) -> Any:
    current: Any = doc
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _parse_cli_value(raw: str) -> Any:
    import yaml

    try:
        return yaml.safe_load(raw)
    except Exception:
        return raw


def _dump_yaml(data: dict) -> str:
    import yaml

    return yaml.safe_dump(
        data, allow_unicode=True, default_flow_style=False, sort_keys=False
    ).rstrip()


def render_config_yaml(config: AppConfig, field: str | None = None) -> str:
    config_dict = config.model_dump()
    if not field:
        return _dump_yaml(config_dict)
    value = _get_nested(config_dict, field.split("."))
    if value is None:
        return f"Field '{field}' not found in config."
    return _dump_yaml({field: value})


def set_config_value(field: str, raw_value: str) -> tuple[str, Path, str | None]:
    value = _parse_cli_value(raw_value)
    top_key = field.split(".")[0]
    if top_key not in VALID_CONFIG_SECTIONS:
        return (
            f"Error: Unknown config section '{top_key}'. Valid sections: "
            f"{', '.join(sorted(VALID_CONFIG_SECTIONS))}",
            get_config_path(),
            None,
        )

    config_path = ConfigLoader.active_path() or get_config_path()
    existed_before = config_path.exists()
    doc = _load_yaml(config_path) if existed_before else {}

    _set_nested(doc, field.split("."), value)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    import yaml

    config_path.write_text(
        yaml.safe_dump(
            doc, allow_unicode=True, default_flow_style=False, sort_keys=False
        ),
        encoding="utf-8",
    )

    note = None
    if not existed_before:
        note = f"Creating new config file at {config_path}"

    return (f"Set {field} = {value!r}  ({config_path})", config_path, note)


def _build_config(data: dict[str, Any]) -> AppConfig:
    """Construct AppConfig from a raw (already env-resolved) dict."""
    src = data.get("sources", {})
    log_section = dict(data.get("log", data.get("logging", {})))
    log_section.pop("metrics_db", None)
    return AppConfig(
        sources=SourcesConfig(
            arxiv=ArxivSourceConfig(**src.get("arxiv", {})),
        ),
        index=IndexConfig(**data.get("index", {})),
        extract=ExtractConfig(**data.get("extract", {})),
        llm=LLMConfig(**data.get("llm", {})),
        tidy=TidyConfig(**data.get("tidy", {})),
        topics=TopicsConfig(**data.get("topics", {})),
        log=LogConfig(**log_section),
    )


# ---------------------------------------------------------------------------
# ConfigLoader  — the public API for finding and loading config
# ---------------------------------------------------------------------------


class ConfigLoader:
    """
    Discovers and loads the active global configuration file.

    Uses the configured resolution order defined in paths.get_config_candidates().
    """

    @staticmethod
    def active_path() -> Path | None:
        """
        Return the config file path if it exists.
        Returns None when no config file is found.
        """
        for path in get_config_candidates():
            if path.exists():
                return path
        return None

    @staticmethod
    def find_all() -> list[Path]:
        """Return all existing config files in resolution order."""
        return [p for p in get_config_candidates() if p.exists()]

    @staticmethod
    def default_write_path() -> Path:
        """
        The canonical path for writing a new or updated config file.
        Always the same canonical location.
        """
        return _get_config_path()

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

        candidates = [p for p in get_config_candidates() if p.exists()]
        if len(candidates) > 1:
            log.warning(
                "Multiple config files found. '%s' is active; ignoring: %s. "
                "Remove the ignored file(s) to silence this warning.",
                candidates[0],
                ", ".join(str(p) for p in candidates[1:]),
            )

        active = candidates[0] if candidates else None
        if not active:
            log.info("No config file found; using built-in defaults.")
            return AppConfig(), None

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


def get_config_path() -> Path:
    """Return the canonical config file path."""
    return _get_config_path()


def get_config_dir() -> Path:
    """
    Return the directory of the active config file.
    Falls back to the default write location's parent when no file exists.
    """
    active = ConfigLoader.active_path()
    return active.parent if active else get_config_path().parent


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
    "ArxivSourceConfig",
    "SourcesConfig",
    "IndexConfig",
    "LLMConfig",
    "ExtractConfig",
    "TidyConfig",
    "TopicsConfig",
    "LogConfig",
    "get_config",
    "get_config_path",
    "get_config_dir",
    "render_config_yaml",
    "set_config_value",
    "VALID_CONFIG_SECTIONS",
    "reset_config",
]
