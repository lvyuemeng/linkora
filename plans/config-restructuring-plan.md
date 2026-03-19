# Configuration Restructuring Plan

> Plan based on user feedback:
> - Single global config with warning for duplicates
> - Single file module (one config.py)
> - Environment variables with .env file support
> - Workspace-local can only override SOURCE config
> - Relative paths resolved from config file location root
> - Data pipe flow (AGENT.md), no getattr

---

## 1. Core Principles

1. **Single global config** - warn if multiple exist
2. **.env auto-load** - from config file's directory
3. **Workspace = GLOBAL only** - filesystem locations
4. **Source = per-workspace** - can override
5. **Data pipe flow** - pure functions, no getattr

---

## 2. Single File: config.py

All functionality in ONE file:

```python
# linkora/config.py

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# ============================================================================
#  Constants
# ============================================================================

ENV_PREFIX = "linkora"

WORKSPACE_FIELDS = {"workspace", "default_workspace"}
ALLOWED_WORKSPACE_LOCAL = {"sources"}

SCOPES = ["xdg", "user", "project"]


# ============================================================================
#  Dataclasses
# ============================================================================

@dataclass(frozen=True)
class WorkspaceConfig:
    name: str = "default"
    description: str = ""
    root: str = ""


@dataclass(frozen=True)
class LocalSourceConfig:
    enabled: bool = True
    papers_dir: str = "papers"
    paths: list[str] = field(default_factory=list)


# ... (other source configs)

@dataclass
class Config:
    """Main config object."""
    workspace: WorkspaceConfig
    workspace_store: dict[str, WorkspaceConfig]
    default_workspace: str
    sources: SourcesConfig
    # ... other fields
    
    _config_root: Path = field(default_factory=Path.cwd)


# ============================================================================
#  Stage 1: .env Loading (Pure Function)
# ============================================================================

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


def _resolve_env_vars(data: dict, env: dict[str, str]) -> dict:
    """Resolve ${VAR} and ${VAR:-fallback} in data.
    
    Pure function - no side effects.
    """
    def resolve(obj):
        if isinstance(obj, str):
            pattern = re.compile(r'\$\{([^}:]+)(?::-([^}]*))?\}')
            
            def replacer(match):
                var_name = match.group(1)
                fallback = match.group(2)
                value = env.get(var_name) or os.environ.get(var_name, "")
                return value or fallback or ""
            
            return pattern.sub(replacer, obj)
        
        if isinstance(obj, dict):
            return {k: resolve(v) for k, v in obj.items()}
        
        if isinstance(obj, list):
            return [resolve(item) for item in obj]
        
        return obj
    
    return resolve(data)


# ============================================================================
#  Stage 2: Collect Config Files
# ============================================================================

def _collect_config_files(root: Path) -> list[tuple[Path, str]]:
    """Collect config files in priority order.
    
    Yields:
        (path, scope) tuples
    """
    home = Path.home()
    found: list[tuple[Path, str]] = []
    
    # XDG: ~/.config/linkora/config.yml
    xdg = home / ".config" / "linkora" / "config.yml"
    if xdg.exists():
        found.append((xdg, "xdg"))
    
    # User: ~/.linkora/config.yml
    user = home / ".linkora" / "config.yml"
    if user.exists():
        if xdg.exists():
            # Warn about duplicate
            import logging
            _log = logging.getLogger(__name__)
            _log.warning(
                "Multiple global configs: using %s (also found %s)",
                user, xdg
            )
        found.append((user, "user"))
    
    # Project: <root>/config.yaml
    project = root / "config.yaml"
    if project.exists():
        found.append((project, "project"))
    
    return found


# ============================================================================
#  Stage 3: YAML Loading
# ============================================================================

def _load_yaml(path: Path) -> dict:
    """Load YAML file."""
    import yaml
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge (override wins)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ============================================================================
#  Stage 4: Load Pipeline
# ============================================================================

def _load_config_data(root: Path, workspace: str | None) -> tuple[dict, dict, Path]:
    """Main loading pipeline.
    
    Returns:
        (workspace_data, sources_data, config_root)
    """
    files = _collect_config_files(root)
    
    # Determine config root (directory of highest priority config)
    config_root = files[-1][0].parent if files else root
    
    # Merge all configs
    merged: dict = {}
    for path, scope in files:
        env = _load_env(path)
        data = _load_yaml(path)
        data = _resolve_env_vars(data, env)
        merged = _deep_merge(merged, data)
    
    # Extract workspace config (global only)
    workspace_data = {k: v for k, v in merged.items() if k in WORKSPACE_FIELDS}
    other_data = {k: v for k, v in merged.items() if k not in WORKSPACE_FIELDS}
    
    # Load workspace-local sources (if exists)
    ws_name = workspace or other_data.get("default_workspace", "default")
    sources_data = other_data.get("sources", {})
    
    ws_local_path = root / "workspace" / ws_name / "linkora.yml"
    if ws_local_path.exists():
        env = _load_env(ws_local_path)
        local_data = _load_yaml(ws_local_path)
        local_data = _resolve_env_vars(local_data, env)
        
        # Warn about disallowed fields
        disallowed = set(local_data.keys()) - ALLOWED_WORKSPACE_LOCAL
        if disallowed:
            import logging
            _log = logging.getLogger(__name__)
            _log.warning(
                "Workspace-local '%s' has non-source fields: %s",
                ws_local_path, list(disallowed)
            )
        
        # Only allow sources override
        local_sources = local_data.get("sources", {})
        sources_data = _deep_merge(sources_data, local_sources)
    
    return workspace_data, sources_data, config_root


# ============================================================================
#  Path Resolution
# ============================================================================

def resolve_path(path: str, config_root: Path) -> Path:
    """Resolve relative path from config root."""
    p = Path(path)
    if p.is_absolute():
        return p.resolve()
    return (config_root / p).resolve()


def resolve_local_source_paths(sources_data: dict, config_root: Path) -> list[Path]:
    """Resolve all local source paths (papers_dir + paths)."""
    local = sources_data.get("local", {})
    
    if not local.get("enabled", True):
        return []
    
    paths = []
    
    # Primary papers_dir
    primary = local.get("papers_dir", "papers")
    if primary:
        paths.append(resolve_path(primary, config_root))
    
    # Additional paths
    for path_str in local.get("paths", []):
        if path_str:
            paths.append(resolve_path(path_str, config_root))
    
    return paths


# ============================================================================
#  Main Loader
# ============================================================================

def load_config(workspace: str | None = None, root: Path | None = None) -> Config:
    """Load configuration."""
    root = root or _find_root()
    
    workspace_data, sources_data, config_root = _load_config_data(root, workspace)
    
    # Build workspace store
    ws_store: dict[str, WorkspaceConfig] = {}
    for name, entry in workspace_data.get("workspace", {}).items():
        ws_entry = entry if isinstance(entry, dict) else {"description": str(entry or "")}
        ws_store[name] = WorkspaceConfig(
            name=name,
            description=ws_entry.get("description", ""),
            root=ws_entry.get("root", ""),
        )
    
    # Resolve current workspace
    ws_name = workspace or os.environ.get(f"{ENV_PREFIX}WORKSPACE") or "default"
    ws_entry = ws_store.get(ws_name, WorkspaceConfig(name=ws_name))
    
    # ... build rest of Config
    
    return Config(
        workspace=ws_entry,
        workspace_store=ws_store,
        sources=_build_sources(sources_data),
        _config_root=config_root,
    )
```

---

## 3. Summary

| Feature | Implementation |
|---------|----------------|
| Single file | All in `config.py` |
| .env auto-load | `_load_env(config_path.parent / ".env")` |
| Workspace = global | `WORKSPACE_FIELDS = {"workspace", "default_workspace"}` |
| Source = per-workspace | `ALLOWED_WORKSPACE_LOCAL = {"sources"}` |
| No getattr | Explicit dict lookups |
| Data pipe | `_collect_config_files` → `_load_yaml` → `_resolve_env_vars` → `_deep_merge` |
