"""
__init__.py / main.py — linkora CLI entry point.

Startup sequence
────────────────
1.  Early-parse --help / --context / --workspace before full parse.
2.  Load AppConfig  (config file → singleton).
3.  Determine data root  (via workspace.get_data_root()).
4.  Build WorkspaceStore.
5.  Resolve active workspace name  (CLI arg > env var > registry default).
6.  Build AppContext and create workspace directories.
7.  Initialise logging  (log.setup with workspace log path).
8.  Initialise metrics  (metrics.init with workspace metrics path).
9.  Full argument parse and command dispatch.

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


def main() -> None:
    """CLI entry point."""

    # ── Step 1: early parse ──────────────────────────────────────────────
    # We need --context and --workspace before loading anything heavy.
    early = argparse.ArgumentParser(add_help=False)
    early.add_argument("--context", action="store_true")
    early.add_argument("--workspace", "-W", default=None, metavar="NAME")
    early_args, _ = early.parse_known_args()

    if early_args.context:
        print(_design_context())
        return

    # ── Step 2: config ───────────────────────────────────────────────────
    from linkora.config import get_config, get_config_dir

    cfg = get_config()
    config_dir = get_config_dir()

    # ── Step 3 & 4: data root + store ────────────────────────────────────
    from linkora.workspace import WorkspaceStore, get_data_root

    data_root = get_data_root()
    store = WorkspaceStore(data_root)

    # ── Step 5: active workspace name ────────────────────────────────────
    workspace_name: str = (
        early_args.workspace
        or os.environ.get("LINKORA_WORKSPACE", "")
        or store.get_default()
    )

    # ── Step 6: context + directories ───────────────────────────────────
    from linkora.cli.context import AppContext

    ctx = AppContext(
        config=cfg,
        config_dir=config_dir,
        store=store,
        workspace_name=workspace_name,
    )
    ctx.ensure_workspace_dirs()

    # ── Step 7: logging ──────────────────────────────────────────────────
    from linkora import log as linkora_log

    log_file = ctx.workspace.log_file(cfg.log.file)
    session_id = linkora_log.init(cfg.log, log_file)

    # ── Step 8: metrics ──────────────────────────────────────────────────
    from linkora import metrics as linkora_metrics

    metrics_db = ctx.workspace.metrics_db(cfg.log.metrics_db)
    linkora_metrics.init(metrics_db, session_id)

    # ── Step 9: full parse + dispatch ────────────────────────────────────
    parser = _build_parser()
    args = parser.parse_args()

    try:
        args.func(args, ctx)
    finally:
        ctx.close()


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
    from linkora.cli import commands as cli_commands

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
    cli_commands.register_all(sub)
    return parser


def _design_context() -> str:
    return """\
================================================================================
                    linkora Design Context for AI Agents
================================================================================

CLI workflow:  init → add → index → search

  linkora init                    Set up workspace and config
  linkora add --doi 10.xxx/yyy    Add a paper by DOI
  linkora add --author "Smith"    Add papers by author
  linkora index                   Build full-text search index
  linkora index --type vector     Build semantic vector index
  linkora search "transformers"   Full-text search
  linkora search --mode vector    Semantic search

Workspace layout
────────────────
  <data_root>/workspace/<name>/
    papers/          One subdirectory per paper (UUID)
    index.db         FTS5 + metadata database
    vectors.faiss    Semantic search index
    logs/            Rotating log files
    workspace.json   Name + description (CLI-managed, not user-editable)

Config location (~/.linkora/config.yml)
────────────────────────────────────────
  index, sources, llm, ingest, topics, logging.
  Workspace names and paths are NOT stored in config.

Workspace commands
──────────────────
  linkora config show             Active workspace summary
  linkora config show --all       All workspaces
  linkora config show llm.model   Single config field
  linkora config set llm.model gpt-4o
  linkora config mv old new       Rename workspace (safe: no stored paths)
  linkora config set-default ml   Change default workspace
  linkora config set-meta description "My ML papers"

Health
──────
  linkora doctor       Full health check (incl. network)
  linkora doctor --light  Quick check (no network)

================================================================================"""


__all__ = ["main", "run"]
