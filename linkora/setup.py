"""
setup.py — linkora Environment Setup

Commands:
  linkora check    Quick diagnostics (no network)
  linkora doctor   Full health check (with network)
  linkora init     Interactive setup wizard
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator

import yaml

from linkora.config import Config, get_config


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
    "embed": [
        ("sentence_transformers", "sentence-transformers"),
        ("faiss", "faiss-cpu"),
        ("numpy", "numpy"),
    ],
    "topics": [("bertopic", "bertopic"), ("pandas", "pandas")],
    "import": [("endnote_utils", "endnote-utils"), ("pyzotero", "pyzotero")],
}


# ============================================================================
#  Stage 1: Collect
# ============================================================================


def _check_python() -> CheckItem:
    vi = sys.version_info
    ok = vi >= (3, 10)
    return CheckItem(
        CheckCategory.ENV, "python", ok, f"{vi.major}.{vi.minor}.{vi.micro}"
    )


def _check_deps() -> Iterator[CheckItem]:
    for group, pkgs in DEP_GROUPS.items():
        missing = []
        for import_name, _ in pkgs:
            try:
                importlib.import_module(import_name)
            except ImportError:
                missing.append(import_name)
        ok = not missing
        detail = (
            ", ".join(p for _, p in pkgs) if ok else f"missing: {', '.join(missing)}"
        )
        yield CheckItem(CheckCategory.ENV, f"deps.{group}", ok, detail)


def _check_config(cfg: Config) -> CheckItem:
    path = cfg._root / "config.yaml"
    ok = path.exists()
    return CheckItem(
        CheckCategory.CONFIG, "config.yaml", ok, "found" if ok else "not found"
    )


def _check_local_config(cfg: Config) -> CheckItem:
    path = cfg._root / "config.local.yaml"
    ok = path.exists()
    return CheckItem(
        CheckCategory.CONFIG,
        "config.local.yaml",
        ok,
        "found" if ok else "not found (use env vars)",
    )


def _check_workspace_dir(cfg: Config) -> CheckItem:
    ok = cfg.workspace_dir.exists()
    detail = str(cfg.workspace_dir) if ok else "not found"
    return CheckItem(CheckCategory.PATHS, "workspace_dir", ok, detail)


def _check_papers_dir(cfg: Config) -> CheckItem:
    ok = cfg.papers_store_dir.exists()
    count = 0
    if ok:
        count = sum(
            1
            for d in cfg.papers_store_dir.iterdir()
            if d.is_dir() and (d / "meta.json").exists()
        )
    detail = f"{cfg.papers_store_dir} ({count} papers)"
    return CheckItem(CheckCategory.PATHS, "papers_dir", ok, detail)


def _check_llm_key(cfg: Config) -> CheckItem:
    key = cfg.resolve_llm_api_key()
    ok = bool(key)
    detail = "configured" if ok else "not set"
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
        detail = (
            f"reachable @ {cfg.ingest.mineru_endpoint}"
            if ok
            else f"error: {r.status_code}"
        )
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
# linkora Configuration

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
  file: linkora.log
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
        local_data: dict = {}
        if key:
            local_data.setdefault("llm", {})["api_key"] = key
        if local_data:
            local_path.write_text(
                yaml.dump(local_data, allow_unicode=True), encoding="utf-8"
            )
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


# ============================================================================
#  Legacy API (for backward compatibility)
# ============================================================================


def check_environment(lang: str = "zh") -> None:
    """Legacy function for backward compatibility."""
    cfg = get_config()
    result = run_check(cfg)
    print(format_result(result, "Environment Check"))


def main() -> None:
    """Legacy main function for backward compatibility."""
    run_init()
