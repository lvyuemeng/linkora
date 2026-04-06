"""
__init__.py / main.py — linkora CLI entry point.

Startup sequence
────────────────
1. Early-parse `--context` / `--workspace`.
2. Load global AppConfig (single-file-wins resolution).
3. Build WorkspaceStore on the default DB.
4. Resolve active workspace (CLI > env > DB default).
5. Build AppContext and initialize logging.
6. Build full parser and dispatch command.

Workspace flag
──────────────
  linkora --workspace <name> <command> …

Environment variable
────────────────────
  LINKORA_WORKSPACE=<name> linkora <command> …
"""

from __future__ import annotations

import argparse
import os
from typing import Sequence


def main() -> None:
    """CLI entry point."""

    early_args = _parse_early_args()
    if early_args.context:
        print(_design_context())
        return

    cfg, config_dir = _load_runtime_config()
    store = _build_workspace_store()
    workspace_name = _resolve_active_workspace_name(store, early_args.workspace)
    ctx = _build_context(cfg, config_dir, store, workspace_name)

    from linkora import log as linkora_log

    linkora_log.init(cfg.log, ctx.log_file(cfg.log.file))

    parser = _build_parser()
    args = parser.parse_args()

    try:
        args.func(args, ctx)
    finally:
        ctx.close()


def _parse_early_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse flags needed before full parser construction."""
    early = argparse.ArgumentParser(add_help=False)
    early.add_argument("--context", action="store_true")
    early.add_argument("--workspace", "-W", default=None, metavar="NAME")
    early_args, _ = early.parse_known_args(argv)
    return early_args


def _load_runtime_config():
    """Load config and active config directory."""
    from linkora.config import get_config, get_config_dir

    return get_config(), get_config_dir()


def _build_workspace_store():
    """Create WorkspaceStore bound to default database."""
    from linkora.workspace import WorkspaceStore
    from linkora.db import get_db

    return WorkspaceStore(get_db())


def _resolve_active_workspace_name(store, cli_workspace: str | None) -> str:
    """Resolve active workspace in precedence: CLI > env > default."""
    default_ws = _ensure_default_workspace(store)
    return cli_workspace or os.environ.get("LINKORA_WORKSPACE", "") or default_ws


def _ensure_default_workspace(store) -> str:
    """Ensure there is one default workspace and return its name."""
    default_ws = store.get_default()
    if default_ws:
        return default_ws.name

    existing = store.list_workspaces()
    if existing:
        name = existing[0].name
        store.set_default(name)
        return name

    store.create("default", description="Default workspace")
    store.set_default("default")
    return "default"


def _build_context(cfg, config_dir, store, workspace_name: str):
    """Create AppContext instance."""
    from linkora.cli.commands import AppContext

    return AppContext(
        config=cfg,
        config_dir=config_dir,
        store=store,
        workspace_name=workspace_name,
    )


def run() -> int:
    """Run the CLI; return a POSIX exit code."""
    from linkora.cli.errors import handle_error

    try:
        main()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        handle_error(exc)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    from linkora.cli.commands import register_all

    parser = argparse.ArgumentParser(
        prog="linkora",
        description=(
            "linkora — Local Knowledge Network\n\n"
            "AI-powered research tool that keeps all data local."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--workspace",
        "-W",
        metavar="NAME",
        help="Active workspace (overrides LINKORA_WORKSPACE env var and registry default)",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="Show design context for AI agents",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    register_all(sub)
    return parser


def _design_context() -> str:
    return """\
================================================================================
                    linkora Design Context for AI Agents
================================================================================

CLI workflow:  init -> add -> index -> search

  linkora init                          Set up config and database
  linkora add ./paper.pdf               Add a local file
  linkora add doi:10.xxx/yyy            Add by DOI
  linkora add arxiv:2401.01234          Add by arXiv id
  linkora add https://...               Add from URL
  linkora index                         Build FTS + vector by default
  linkora index --vector                Build only vector index
  linkora index --fts                   Build only FTS index
  linkora index --topics                Build only topics
  linkora search "transformers"         Search both modes by default
  linkora search --mode vector "..."    Vector-only search
  linkora search --mode fulltext "..."  Fulltext-only search

Data root layout
────────────────
  <data_root>/
    linkora.db     Single SQLite database (all workspaces)
    vectors/       LanceDB vector storage
    cache/         Extracted text cache
    linkora.log    Log file

Config resolution (single-file-wins)
────────────────────────────────────
  Candidates are checked in order; the first existing file is active:
    1) ~/.linkora/config.yml
    2) ~/.linkora/config.yaml
    3) ~/.linkora.yml
    4) ~/.linkora.yaml
    5) ~/.config/linkora/config.yml
    6) ~/.config/linkora/config.yaml

  If multiple candidates exist, linkora logs a warning and ignores lower-priority files.
  Workspace names/paths are NOT stored in config.
  Config is optional; built-in defaults are used when no file exists.

Config commands
───────────────
  linkora config show             Show full config
  linkora config show llm.model   Single config field
  linkora config set llm.model gpt-4o

Source ingest pipeline (conceptual)
───────────────────────────────────
  parse target -> resolve source -> fetch artifacts -> ingest pipeline

Schema pipeline (conceptual)
────────────────────────────
  resolve doc type/schema -> parse schema fields -> filter/render

Files commands
──────────────
  linkora files inbox <dir>       Ingest all files in a directory
  linkora files tidy <dir>        Normalize filenames
  linkora files dedup <dir>       Find duplicate files
  linkora files rescan <dir>      Fix moved file paths
  linkora files watch add <dir>   Watch for auto-import
  linkora files watch list        List watches

Health
──────
  linkora doctor       Full health check (incl. network)
  linkora doctor --light  Quick check (no network)

================================================================================"""


__all__ = ["main", "run"]
