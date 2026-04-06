"""
paths.py - Unified path resolution.

Keeps platform-specific paths centralized to avoid circular imports.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path


def get_data_root() -> Path:
    """Return the platform-appropriate linkora data directory.

    Override via the LINKORA_ROOT environment variable.

    Platform defaults:
    - Windows:   %APPDATA%/linkora
    - macOS:     ~/Library/Application Support/linkora
    - Linux:     $XDG_DATA_HOME/linkora  (default: ~/.local/share/linkora)
    """
    env_root = os.environ.get("LINKORA_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    home = Path.home()
    system = platform.system()

    if system == "Windows":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

    return base / "linkora"


def get_db_path() -> Path:
    """Return the path to linkora.db."""
    return get_data_root() / "linkora.db"


def get_cache_dir() -> Path:
    """Return the cache directory for extracted text."""
    return get_data_root() / "cache"


def get_vectors_dir() -> Path:
    """Return the vector index directory."""
    return get_data_root() / "vectors"


def resolve_data_path(value: str) -> Path:
    """Resolve a path under data root unless already absolute."""
    raw = Path(value).expanduser()
    return raw if raw.is_absolute() else (get_data_root() / raw)


def get_config_path() -> Path:
    """Return the default config path."""
    return get_config_candidates()[0]


def get_config_candidates() -> list[Path]:
    """Return ordered config path candidates."""
    home = Path.home()
    return [
        home / ".linkora" / "config.yml",
        home / ".linkora" / "config.yaml",
        home / ".linkora.yml",
        home / ".linkora.yaml",
        home / ".config" / "linkora" / "config.yml",
        home / ".config" / "linkora" / "config.yaml",
    ]


__all__ = [
    "get_data_root",
    "get_db_path",
    "get_cache_dir",
    "get_vectors_dir",
    "resolve_data_path",
    "get_config_path",
    "get_config_candidates",
]
