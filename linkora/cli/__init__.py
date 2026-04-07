"""
__init__.py / main.py — linkora CLI entry point.

Startup sequence
────────────────
1. Early-parse `--context` / `--workspace`.
2. Bootstrap runtime via `linkora.setup.run_init`.
3. Initialize logging with runtime context.
4. Build full parser and dispatch command.

Workspace flag
──────────────
  linkora --workspace <name> <command> …

Environment variable
────────────────────
  LINKORA_WORKSPACE=<name> linkora <command> …
"""

from __future__ import annotations

import argparse
from typing import Sequence


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


def main() -> None:
    """CLI entry point."""

    early_args = _parse_early_args()
    if early_args.context:
        print(_design_context())
        return

    from linkora.setup import run_init

    ctx = run_init(cli_workspace=early_args.workspace)

    from linkora import log as linkora_log

    linkora_log.init(ctx.config.log, ctx.log_file(ctx.config.log.file))

    parser = _build_parser()
    args = parser.parse_args()

    try:
        args.func(args, ctx)
    finally:
        ctx.close()


def _add_global_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        "-W",
        default=None,
        metavar="NAME",
        help="Active workspace (overrides LINKORA_WORKSPACE env var and registry default)",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="Show design context for AI agents",
    )


def _parse_early_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse flags needed before full parser construction."""
    early = argparse.ArgumentParser(add_help=False)
    _add_global_args(early)
    early_args, _ = early.parse_known_args(argv)
    return early_args


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
    _add_global_args(parser)

    sub = parser.add_subparsers(dest="command", required=True)
    register_all(sub)
    return parser


def _design_context() -> str:
    from linkora.setup import get_config_candidates

    candidates_text = "\n".join(
        f"    {idx}) {path}"
        for idx, path in enumerate(get_config_candidates(), start=1)
    )

    return f"""\
================================================================================
                    linkora Design Context for AI Agents
================================================================================

CLI workflow:  add -> index -> search

  # No explicit init step is required.
  # DB/workspace bootstrap happens automatically on first run.
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
  linkora loads one global config file and does not merge multiple files.
  Candidates are checked in order; the first existing file is active:
{candidates_text}

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
  linkora doctor       Config/environment diagnostics

================================================================================"""


__all__ = ["main", "run"]
