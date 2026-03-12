"""ScholarAIO CLI - Modular command-line interface."""

from __future__ import annotations

import argparse
import sys

from scholaraio.config import load_config
from scholaraio import log as scholaraio_log
from scholaraio import metrics as scholaraio_metrics


def main() -> None:
    """Entry point for the CLI."""
    # Early parse for --philosophy flag
    early_parser = argparse.ArgumentParser(add_help=False)
    early_parser.add_argument(
        "--philosophy", action="store_true", help="Show design philosophy"
    )
    early_args, _ = early_parser.parse_known_args()

    if early_args.philosophy:
        print(_show_philosophy())
        return

    # Build the main parser
    parser = _build_parser()
    args = parser.parse_args()

    # Load config and initialize
    cfg = load_config()
    cfg.ensure_dirs()

    session_id = scholaraio_log.setup(cfg)
    scholaraio_metrics.init(cfg.metrics_db_path, session_id)

    # Execute command
    args.func(args, cfg)


def run() -> int:
    """Run the CLI and return exit code."""
    try:
        main()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _show_philosophy() -> str:
    """Display project design philosophy."""
    return """
+=========================================================================+
|                         ScholarAIO Design Philosophy                        |
+=========================================================================+
|
|  1. Local-First
|     * All data stored locally (privacy, offline capability)
|     * No cloud sync, no external dependencies for core features
|
|  2. AI-Native
|     * Designed for AI coding agents, not end users
|     * Machine-friendly output (JSON)
|     * MCP server integrated for agent workflows
|
|  3. Minimal but Complete
|     * PDF parsing (MinerU) -> structured Markdown
|     * Hybrid search (FTS5 + Vector + RRF fusion)
|     * Topic modeling (BERTopic)
|     * Citation graph analysis
|
|  4. Zero Config
|     * Environment variables auto-detected
|     * Smart defaults for all settings
|     * Cross-platform (Linux / macOS / Windows)
|
+=========================================================================+

Quick Start:
  1. Install: uv tool install -e .  (or pip install -e .)
  2. Configure: export SCHOLARAIO_LLM_API_KEY=your-key
  3. Ingest: echo "*.pdf" -> data/inbox/ && scholaraio pipeline full
  4. Search: scholaraio search "your topic"

For more: scholaraio --help
"""


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    from scholaraio.cli import commands as cli_commands

    parser = argparse.ArgumentParser(
        prog="scholaraio",
        description="ScholarAIO - AI Research Terminal\n\n"
        "ScholarAIO is designed for AI coding agents to manage local academic "
        "knowledge bases. All data is stored locally for privacy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--philosophy", action="store_true", help="Show design philosophy"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # Register all commands
    cli_commands.register_all(sub)

    return parser


__all__ = ["main", "run"]
