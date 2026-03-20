"""
setup.py — linkora environment diagnostics and interactive setup.

Commands
────────
  linkora check          Quick diagnostics (no network calls)
  linkora doctor         Full health check (includes network calls)
  linkora init           Interactive setup wizard

Design notes
────────────
- All checks receive AppContext so they can inspect workspace paths,
  config resolution, and the store without accessing private internals.
- Multiple global config files are a first-class warning surfaced by doctor.
- The init wizard writes only to ConfigLoader.default_write_path()
  (~/.linkora/config.yml) and never touches workspace files directly.
- get_data_root() is imported from workspace — no inline platform detection.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Iterator

from linkora.config import ConfigLoader
from linkora.workspace import get_data_root


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class CheckCategory(Enum):
    CONFIG = auto()  # Config file resolution + conflicts
    ENV = auto()  # Python version, installed packages
    WORKSPACE = auto()  # Workspace registry health
    PATHS = auto()  # Required directories / files
    SECRETS = auto()  # API keys (present / absent)
    SERVICES = auto()  # Network reachability (doctor only)


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
    config_written: bool
    config_path: Path
    dirs_created: bool


# ---------------------------------------------------------------------------
# Dependency groups
# ---------------------------------------------------------------------------

_DEP_GROUPS: dict[str, list[tuple[str, str]]] = {
    "core": [
        ("requests", "requests"),
        ("yaml", "pyyaml"),
    ],
    "embed": [
        ("sentence_transformers", "sentence-transformers"),
        ("faiss", "faiss-cpu"),
        ("numpy", "numpy"),
    ],
    "topics": [
        ("bertopic", "bertopic"),
        ("pandas", "pandas"),
    ],
    "import": [
        ("endnote_utils", "endnote-utils"),
        ("pyzotero", "pyzotero"),
    ],
}


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_config_resolution() -> Iterator[CheckItem]:
    """
    Inspect global config file resolution.

    Reports which file is active and warns when multiple candidates exist
    (the non-active ones are silently ignored, which can confuse users).
    """
    existing = ConfigLoader.find_all()
    active = ConfigLoader.active_path()

    if not existing:
        yield CheckItem(
            CheckCategory.CONFIG,
            "config.file",
            ok=False,
            detail=(
                f"No config file found. "
                f"Run 'linkora init' or create {ConfigLoader.default_write_path()}"
            ),
        )
        return

    yield CheckItem(
        CheckCategory.CONFIG,
        "config.active",
        ok=True,
        detail=str(active),
    )

    if len(existing) > 1:
        ignored = [p for p in existing if p != active]
        yield CheckItem(
            CheckCategory.CONFIG,
            "config.conflict",
            ok=False,
            detail=(
                f"Multiple config files found — only '{active.name}' is active. "  # type: ignore[union-attr]
                f"Ignored: {', '.join(str(p) for p in ignored)}. "
                "Remove the ignored file(s) to eliminate this ambiguity."
            ),
        )


def _check_python() -> CheckItem:
    vi = sys.version_info
    ok = vi >= (3, 12)
    suffix = "" if ok else " (3.12+ required)"
    return CheckItem(
        CheckCategory.ENV,
        "python",
        ok=ok,
        detail=f"{vi.major}.{vi.minor}.{vi.micro}{suffix}",
    )


def _check_deps() -> Iterator[CheckItem]:
    for group, pkgs in _DEP_GROUPS.items():
        missing = [
            pip_name for import_name, pip_name in pkgs if not _can_import(import_name)
        ]
        yield CheckItem(
            CheckCategory.ENV,
            f"deps.{group}",
            ok=not missing,
            detail=(
                "all present"
                if not missing
                else f"missing: pip install {' '.join(missing)}"
            ),
        )


def _can_import(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def _check_workspace(ctx) -> Iterator[CheckItem]:
    """Check that the active workspace is registered and has a papers directory."""
    name = ctx.workspace_name
    paths = ctx.workspace

    yield CheckItem(
        CheckCategory.WORKSPACE,
        "workspace.registry",
        ok=ctx.store.exists(name),
        detail=(
            f"'{name}' registered"
            if ctx.store.exists(name)
            else f"'{name}' not found in registry — run 'linkora init'"
        ),
    )

    yield CheckItem(
        CheckCategory.PATHS,
        "workspace.papers_dir",
        ok=paths.papers_dir.exists(),
        detail=str(paths.papers_dir),
    )

    count = ctx.store.get_paper_count(name)
    yield CheckItem(
        CheckCategory.WORKSPACE,
        "workspace.papers",
        ok=True,  # informational — never a failure
        detail=f"{count} paper(s) in '{name}'",
    )


def _check_secrets(ctx) -> Iterator[CheckItem]:
    llm_key = ctx.config.resolve_llm_api_key()
    yield CheckItem(
        CheckCategory.SECRETS,
        "llm.api_key",
        ok=bool(llm_key),
        detail="configured"
        if llm_key
        else "not set (DEEPSEEK_API_KEY / OPENAI_API_KEY / llm.api_key)",
    )

    mineru_key = ctx.config.resolve_mineru_api_key()
    yield CheckItem(
        CheckCategory.SECRETS,
        "mineru.api_key",
        ok=bool(mineru_key),
        detail=(
            "configured"
            if mineru_key
            else "not set (MINERU_API_KEY / ingest.mineru_api_key) — optional"
        ),
    )


def _check_llm_service(ctx) -> CheckItem:
    try:
        import requests

        url = ctx.config.llm.base_url.rstrip("/") + "/v1/models"
        r = requests.get(url, timeout=5)
        ok = r.status_code < 500
        detail = (
            f"reachable ({ctx.config.llm.model})" if ok else f"HTTP {r.status_code}"
        )
    except Exception as exc:
        ok = False
        detail = f"unreachable — {exc}"
    return CheckItem(CheckCategory.SERVICES, f"llm.{ctx.config.llm.model}", ok, detail)


def _check_mineru_service(ctx) -> CheckItem:
    try:
        import requests

        r = requests.get(ctx.config.ingest.mineru_endpoint, timeout=5)
        ok = r.status_code < 500
        detail = "reachable" if ok else f"HTTP {r.status_code}"
    except Exception as exc:
        ok = False
        detail = f"unreachable — {exc}"
    return CheckItem(CheckCategory.SERVICES, "mineru", ok, detail)


# ---------------------------------------------------------------------------
# Collection pipelines
# ---------------------------------------------------------------------------


def _collect_quick(ctx) -> Iterator[CheckItem]:
    yield from _check_config_resolution()
    yield _check_python()
    yield from _check_deps()
    yield from _check_workspace(ctx)
    yield from _check_secrets(ctx)


def _collect_services(ctx) -> Iterator[CheckItem]:
    yield _check_llm_service(ctx)
    yield _check_mineru_service(ctx)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_check(ctx) -> CheckResult:
    """Quick check — no network calls."""
    return CheckResult(items=tuple(_collect_quick(ctx)))


def run_doctor(ctx) -> CheckResult:
    """Full health check, including network reachability."""
    return CheckResult(
        items=tuple(list(_collect_quick(ctx)) + list(_collect_services(ctx)))
    )


def format_result(result: CheckResult, title: str = "Check") -> str:
    """Format a CheckResult for terminal output."""
    bar = "=" * (len(title) + 8)
    lines = [bar, f"    {title}", bar]

    by_cat: dict[CheckCategory, list[CheckItem]] = {}
    for item in result.items:
        by_cat.setdefault(item.category, []).append(item)

    for cat in CheckCategory:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"\n{cat.name}:")
        for item in items:
            mark = "✓" if item.ok else "✗"
            lines.append(f"  [{mark}] {item.name:<34} {item.detail}")

    status = "PASS" if result.passed else "FAIL"
    lines.append(
        f"\n{status}  {result.total - result.failed}/{result.total} checks passed"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Init wizard
# ---------------------------------------------------------------------------

_CONFIG_TEMPLATE = """\
# linkora configuration
# Run 'linkora init' to regenerate, or edit freely.
#
# Workspace management (create / rename / set-default) is done via:
#   linkora config <subcommand>

index:
  top_k: 20
  embed_model: Qwen/Qwen3-Embedding-0.6B
  embed_device: auto

sources:
  local:
    enabled: true
    papers_dir: papers
    # paths:          # additional directories to scan for PDFs
    #   - /data/shared-papers

llm:
  backend: openai-compat
  model: deepseek-chat
  base_url: https://api.deepseek.com
  # api_key: ${DEEPSEEK_API_KEY}   # or export DEEPSEEK_API_KEY
  timeout: 30

ingest:
  extractor: robust
  mineru_endpoint: http://localhost:8000
  # mineru_api_key: ${MINERU_API_KEY}

logging:
  level: INFO
  file: linkora.log
  metrics_db: metrics.db
"""


def run_init(force: bool = False) -> InitResult:
    """
    Write an initial global config file and bootstrap the default workspace.

    Always writes to ``ConfigLoader.default_write_path()``
    (~/.linkora/config.yml).  Prompts for an LLM API key which is written
    directly into the config file (the user can later replace the literal
    value with an environment-variable reference).
    """
    config_path = ConfigLoader.default_write_path()
    config_written = False

    if force or not config_path.exists():
        key = input("LLM API key (leave blank to configure later): ").strip()
        template = _CONFIG_TEMPLATE
        if key:
            template = template.replace(
                "  # api_key: ${DEEPSEEK_API_KEY}",
                f"  api_key: {key}  # move to DEEPSEEK_API_KEY env var for security",
            )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(template, encoding="utf-8")
        config_written = True
        print(f"Created {config_path}")
    else:
        print(f"Config already exists at {config_path}  (use --force to overwrite)")

    # Bootstrap the default workspace.
    from linkora.workspace import WorkspaceStore

    store = WorkspaceStore(get_data_root())
    dirs_created = False

    if not store.exists("default"):
        store.create("default", description="Default workspace")
        dirs_created = True
        print(f"Created default workspace at {store.paths('default').workspace_dir}")

    return InitResult(
        config_written=config_written,
        config_path=config_path,
        dirs_created=dirs_created,
    )


# ---------------------------------------------------------------------------
# CLI entry points  (called from commands.py cmd_doctor / cmd_init)
# ---------------------------------------------------------------------------


def cmd_check(args, ctx) -> None:
    result = run_check(ctx)
    print(format_result(result, "Quick Check"))


def cmd_doctor(args, ctx) -> None:
    result = run_doctor(ctx)
    print(format_result(result, "Doctor"))


def cmd_init(args) -> None:
    run_init(force=getattr(args, "force", False))
