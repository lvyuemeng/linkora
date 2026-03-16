# setup.py Refactoring Plan

> Refactor `scholaraio/setup.py` to align with AGENT.md philosophy.
> - English only
> - Data pipe flow
> - Commands: `synapse check` and `synapse doctor`

---

## 1. Command Design

### 1.1 `synapse check`

Quick environment diagnostics (fast, no network):

```bash
$ synapse check

[OK] python: 3.12.2
[OK] config.yaml: found
[OK] workspace: /path/to/workspace
[OK] papers_dir: /path/to/papers (0 papers)
[--] llm.api_key: not set

Passed: 4/5
```

### 1.2 `synapse doctor`

Full health check (may test network/API connections):

```bash
$ synapse doctor

=== Environment ===
[OK] python: 3.12.2
[OK] deps: requests, pyyaml

=== Configuration ===
[OK] config.yaml: found
[OK] workspace_dir: /path/to/workspace
[OK] papers_dir: /path/to/papers

=== Secrets ===
[--] llm.api_key: not set
[--] mineru.api_key: not set

=== Services ===
[OK] LLM (deepseek): reachable
[--] MinerU: not reachable

Health Score: 7/9
```

---

## 2. Data Pipe Flow

### 2.1 Types

```python
from dataclasses import dataclass
from enum import Enum, auto


class CheckCategory(Enum):
    ENV = auto()      # Python, deps
    CONFIG = auto()   # Config files
    PATHS = auto()   # Directories
    SECRETS = auto() # API keys
    SERVICES = auto() # Network checks


@dataclass(frozen=True)
class CheckItem:
    category: CheckCategory
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class CheckResult:
    items: tuple[CheckItem, ...]

    @property
    def passed(self) -> bool:
        return all(i.ok for i in self.items)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def failed(self) -> int:
        return sum(1 for i in self.items if not i.ok)
```

### 2.2 Pipe Functions

```python
def _collect(cfg: Config) -> Iterator[CheckItem]:
    """Collect all check items."""
    # ENV
    yield _check_python()
    yield from _check_deps()

    # CONFIG
    yield _check_config(cfg)
    yield _check_local_config(cfg)

    # PATHS
    yield _check_workspace_dir(cfg)
    yield _check_papers_dir(cfg)

    # SECRETS
    yield _check_llm_key(cfg)
    yield _check_mineru_key(cfg)


def _verify_service(item: CheckItem, cfg: Config) -> CheckItem:
    """Verify service connectivity (for doctor command)."""
    if item.category != CheckCategory.SERVICES:
        return item
    # Test network connectivity here
    return item


def run_check(cfg: Config) -> CheckResult:
    """Quick check (no network)."""
    items = tuple(_collect(cfg))
    return CheckResult(items=items)


def run_doctor(cfg: Config) -> CheckResult:
    """Full health check (with network)."""
    items = tuple(_verify_service(item, cfg) for item in _collect(cfg))
    return CheckResult(items=items)
```

---

## 3. Secret Management

Two-file pattern:

| File | Tracked | Contents |
|------|---------|----------|
| `config.yaml` | YES | Non-sensitive defaults |
| `config.local.yaml` | NO | Secrets only |

---

## 4. Complete Code

```python
"""
setup.py — Synapse Environment Setup

Commands:
  synapse check    Quick diagnostics (no network)
  synapse doctor   Full health check (with network)
  synapse init    Interactive setup wizard
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Iterator

import yaml

from scholaraio.config import Config, get_config


# ============================================================================
#  Types
# ============================================================================


class CheckCategory(Enum):
    ENV = auto()
    CONFIG = auto()
    PATHS = auto()
    SECRETS = auto()
    SERVICES = auto()


@dataclass(frozen=True)
class CheckItem:
    category: CheckCategory
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class CheckResult:
    items: tuple[CheckItem, ...]

    @property
    def passed(self) -> bool:
        return all(i.ok for i in self.items)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def failed(self) -> int:
        return sum(1 for i in self.items if not i.ok)


@dataclass(frozen=True)
class InitResult:
    config_created: bool
    local_created: bool
    dirs_created: bool


# ============================================================================
#  Constants
# ============================================================================

DEP_GROUPS = {
    "core": [("requests", "requests"), ("yaml", "pyyaml")],
    "embed": [("sentence_transformers", "sentence-transformers"), ("faiss", "faiss-cpu"), ("numpy", "numpy")],
    "topics": [("bertopic", "bertopic"), ("pandas", "pandas")],
    "import": [("endnote_utils", "endnote-utils"), ("pyzotero", "pyzotero")],
}


# ============================================================================
#  Stage 1: Collect
# ============================================================================


def _check_python() -> CheckItem:
    vi = sys.version_info
    ok = vi >= (3, 10)
    return CheckItem(CheckCategory.ENV, "python", ok, f"{vi.major}.{vi.minor}.{vi.micro}")


def _check_deps() -> Iterator[CheckItem]:
    for group, pkgs in DEP_GROUPS.items():
        missing = []
        for import_name, _ in pkgs:
            try:
                importlib.import_module(import_name)
            except ImportError:
                missing.append(import_name)
        ok = not missing
        detail = ", ".join(p for _, p in pkgs) if ok else f"missing: {', '.join(missing)}"
        yield CheckItem(CheckCategory.ENV, f"deps.{group}", ok, detail)


def _check_config(cfg: Config) -> CheckItem:
    path = cfg._root / "config.yaml"
    ok = path.exists()
    return CheckItem(CheckCategory.CONFIG, "config.yaml", ok, "found" if ok else "not found")


def _check_local_config(cfg: Config) -> CheckItem:
    path = cfg._root / "config.local.yaml"
    ok = path.exists()
    return CheckItem(CheckCategory.CONFIG, "config.local.yaml", ok, "found" if ok else "not found (use env vars)")


def _check_workspace_dir(cfg: Config) -> CheckItem:
    ok = cfg.workspace_dir.exists()
    detail = str(cfg.workspace_dir) if ok else "not found"
    return CheckItem(CheckCategory.PATHS, "workspace_dir", ok, detail)


def _check_papers_dir(cfg: Config) -> CheckItem:
    ok = cfg.papers_dir.exists()
    count = 0
    if ok:
        count = sum(1 for d in cfg.papers_dir.iterdir() if d.is_dir() and (d / "meta.json").exists())
    detail = f"{cfg.papers_dir} ({count} papers)"
    return CheckItem(CheckCategory.PATHS, "papers_dir", ok, detail)


def _check_llm_key(cfg: Config) -> CheckItem:
    key = cfg.resolve_llm_api_key()
    ok = bool(key)
    detail = f"configured" if ok else "not set"
    return CheckItem(CheckCategory.SECRETS, "llm.api_key", ok, detail)


def _check_mineru_key(cfg: Config) -> CheckItem:
    key = cfg.resolve_mineru_api_key()
    ok = bool(key)
    detail = "configured" if ok else "not set (use MINERU_API_KEY env)"
    return CheckItem(CheckCategory.SECRETS, "mineru.api_key", ok, detail)


def _check_llm_service(cfg: Config) -> CheckItem:
    """Check if LLM service is reachable."""
    try:
        import requests
        r = requests.get(cfg.llm.base_url.rstrip("/") + "/v1/models", timeout=5)
        ok = r.status_code < 500
        detail = f"reachable ({cfg.llm.model})" if ok else f"error: {r.status_code}"
    except Exception as e:
        ok = False
        detail = f"unreachable: {e}"
    return CheckItem(CheckCategory.SERVICES, f"llm.{cfg.llm.model}", ok, detail)


def _check_mineru_service(cfg: Config) -> CheckItem:
    """Check if MinerU service is reachable."""
    try:
        import requests
        r = requests.get(cfg.ingest.mineru_endpoint, timeout=5)
        ok = r.status_code < 500
        detail = f"reachable @ {cfg.ingest.mineru_endpoint}" if ok else f"error: {r.status_code}"
    except Exception as e:
        ok = False
        detail = f"unreachable: {e}"
    return CheckItem(CheckCategory.SERVICES, "mineru", ok, detail)


# ============================================================================
#  Stage 2: Pipe
# ============================================================================


def _collect(cfg: Config) -> Iterator[CheckItem]:
    """Collect all check items."""
    yield _check_python()
    yield from _check_deps()
    yield _check_config(cfg)
    yield _check_local_config(cfg)
    yield _check_workspace_dir(cfg)
    yield _check_papers_dir(cfg)
    yield _check_llm_key(cfg)
    yield _check_mineru_key(cfg)


def _collect_services(cfg: Config) -> Iterator[CheckItem]:
    """Collect service health items."""
    yield _check_llm_service(cfg)
    yield _check_mineru_service(cfg)


# ============================================================================
#  Commands
# ============================================================================


def run_check(cfg: Config) -> CheckResult:
    """Quick check (no network)."""
    items = tuple(_collect(cfg))
    return CheckResult(items=items)


def run_doctor(cfg: Config) -> CheckResult:
    """Full health check (with network)."""
    items = tuple(list(_collect(cfg)) + list(_collect_services(cfg)))
    return CheckResult(items=items)


def format_result(result: CheckResult, title: str = "Check") -> str:
    """Format check result."""
    lines = [f"=== {title} ==="]

    # Group by category
    by_cat: dict[CheckCategory, list[CheckItem]] = {}
    for item in result.items:
        by_cat.setdefault(item.category, []).append(item)

    for cat in CheckCategory:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"\n{cat.name}:")
        for item in items:
            mark = "[OK]" if item.ok else "[--]"
            lines.append(f"  {mark} {item.name}: {item.detail}")

    lines.append(f"\nHealth: {result.total - result.failed}/{result.total}")
    return "\n".join(lines)


# ============================================================================
#  Init Wizard
# ============================================================================


CONFIG_TEMPLATE = """\
# Synapse Configuration

workspace:
  name: default
  description: "Default workspace"

index:
  top_k: 20
  embed_model: Qwen/Qwen3-Embedding-0.6B
  embed_device: auto

sources:
  local:
    enabled: true
    papers_dir: papers

llm:
  backend: openai-compat
  model: deepseek-chat
  base_url: https://api.deepseek.com
  timeout: 30

ingest:
  extractor: robust
  mineru_endpoint: http://localhost:8000

logging:
  level: INFO
  file: synapse.log
  metrics_db: metrics.db
"""


LOCAL_TEMPLATE = """\
# Local overrides (not tracked by git)

# llm:
#   api_key: sk-xxx

# ingest:
#   mineru_api_key: xxx
#   contact_email: your@email.com
"""


def run_init(force: bool = False) -> InitResult:
    """Interactive init wizard."""
    cfg = get_config()
    root = cfg._root

    # Create config.yaml
    config_path = root / "config.yaml"
    config_created = False
    if force or not config_path.exists():
        config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        config_created = True

    # Create config.local.yaml
    local_path = root / "config.local.yaml"
    local_created = False
    if force or not local_path.exists():
        key = input("LLM API key (skip to use env): ").strip()
        local_data = {}
        if key:
            local_data.setdefault("llm", {})["api_key"] = key
        if local_data:
            local_path.write_text(yaml.dump(local_data, allow_unicode=True), encoding="utf-8")
            local_created = True

    # Create directories
    dirs_created = False
    if config_created or local_created:
        cfg = get_config()
        cfg.ensure_dirs()
        dirs_created = True

    return InitResult(config_created, local_created, dirs_created)


# ============================================================================
#  CLI
# ============================================================================


def cmd_check(args) -> None:
    cfg = get_config()
    result = run_check(cfg)
    print(format_result(result, "Check"))


def cmd_doctor(args) -> None:
    cfg = get_config()
    result = run_doctor(cfg)
    print(format_result(result, "Doctor"))


def cmd_init(args) -> None:
    force = getattr(args, "force", False)
    result = run_init(force=force)
    if result.config_created:
        print("Created config.yaml")
    if result.local_created:
        print("Created config.local.yaml")
    if result.dirs_created:
        print("Created directories")
    print("\nDone! Run: synapse doctor")


# ============================================================================
#  Main
# ============================================================================


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Synapse Setup")
    sub = parser.add_subparsers()

    p = sub.add_parser("check", help="Quick diagnostics")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("doctor", help="Full health check")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("init", help="Initialize configuration")
    p.add_argument("--force", action="store_true", help="Overwrite files")
    p.set_defaults(func=cmd_init)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
```

---

## 5. CLI Summary

| Command | Description | Network |
|---------|-------------|---------|
| `synapse check` | Quick diagnostics | No |
| `synapse doctor` | Full health check | Yes |
| `synapse init` | Interactive setup | No |

---

## 6. Files Changed

| File | Action |
|------|--------|
| `scholaraio/setup.py` | Refactor to new design |
| `scholaraio/cli/commands.py` | Update setup command names |
