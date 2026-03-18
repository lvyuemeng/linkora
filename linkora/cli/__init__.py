"""linkora CLI - Modular command-line interface."""

from __future__ import annotations

import argparse

from linkora.config import load_config
from linkora import log as linkora_log
from linkora import metrics as linkora_metrics
from linkora.cli.context import AppContext
from linkora.cli.errors import handle_error


def main() -> None:
    """Entry point for the CLI."""
    # Early parse for --help and --context flags
    early_parser = argparse.ArgumentParser(add_help=False)
    early_parser.add_argument(
        "--help",
        action="store_true",
        help="Show this help message",
    )
    early_parser.add_argument(
        "--context",
        action="store_true",
        help="Show design context for AI agents: CLI workflow and usage patterns",
    )
    early_args, _ = early_parser.parse_known_args()

    if early_args.context:
        print(_show_design_context())
        return

    # Build the main parser
    parser = _build_parser()
    args = parser.parse_args()

    # Load config and initialize
    cfg = load_config()
    cfg.ensure_dirs()

    session_id = linkora_log.setup(cfg)
    linkora_metrics.init(cfg.metrics_db_path, session_id)

    # Create AppContext for lazy initialization
    ctx = AppContext(cfg)
    try:
        # Execute command with AppContext
        args.func(args, ctx)
    finally:
        ctx.close()


def run() -> int:
    """Run the CLI and return exit code."""
    try:
        main()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        handle_error(e)
        return 1


def _show_design_context() -> str:
    """Display design context for AI agents: CLI workflow and usage patterns."""
    return """
================================================================================
                        linkora Design Context for AI Agents
================================================================================

## CLI Workflow

The CLI follows a simple pipeline: init → add → index → search

1. INIT:    linkora init           # Set up workspace and config
2. ADD:     linkora add <file>     # Add papers to workspace
3. INDEX:   linkora index          # Build search index
4. SEARCH:  linkora search <query> # Query papers

## Usage Patterns

### Paper Ingestion
- Place PDFs in workspace/papers/ or use 'linkora add'
- Papers are stored with UUID, metadata in meta.json, full text in paper.md
- Use MinerU for high-quality PDF extraction (set MINERU_API_KEY)

### Search Workflow
- Default mode: FTS5 full-text search (fast, keyword-based)
- --mode vector: Semantic search using embeddings (requires faiss)
- --mode hybrid: Combined FTS + vector (RRF fusion)
- Results include paper metadata (L1), abstract (L2), sections (L3)

### Layered Loading (L1-L4)
- L1: title, authors, year, journal, doi (from index.db)
- L2: abstract (from meta.json)
- L3: structural sections (from chunks.jsonl)
- L4: full markdown (from paper.md)

### Workspace Isolation
- Each workspace is independent: papers/, index.db, vectors.faiss
- Use --workspace flag or SYNAPSE_WORKSPACE env var to switch
- Config precedence: CLI > env > workspace-local > global > defaults

### MCP Server
- Run 'linkora-mcp' to start MCP server
- 31 tools available for Claude Desktop, Cursor, etc.
- Tools include: search, add_paper, get_paper, build_index, etc.

## Communication Pattern

When user asks for help:
1. Show relevant command examples
2. Explain with context (workspace, papers loaded)
3. Suggest next steps based on current state

When user asks about papers:
1. Use 'linkora search' to find relevant papers
2. Use 'linkora audit' to check data quality
3. Use 'linkora doctor' for full health check

When user wants to add papers:
1. Use 'linkora add <path>' for single file
2. Use 'linkora index --rebuild' after adding papers

================================================================================

Quick Reference:
  linkora --context     # Show this design context
  linkora --help        # Show CLI help
  linkora init          # Initialize workspace
  linkora add <file>    # Add paper
  linkora index         # Build index
  linkora search <q>    # Search papers

================================================================================
"""


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    from linkora.cli import commands as cli_commands

    parser = argparse.ArgumentParser(
        prog="linkora",
        description="linkora - Local Knowledge Network\n\n"
        "linkora is a local knowledge network for AI-powered research. "
        "All data is stored locally for privacy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="Show design context for AI agents: CLI workflow and usage patterns",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # Register all commands
    cli_commands.register_all(sub)

    return parser


__all__ = ["main", "run"]
