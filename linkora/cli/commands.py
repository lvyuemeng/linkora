"""CLI command handlers - unified commands with context injection."""

from __future__ import annotations

import argparse
from typing import Literal, Callable

from linkora.cli.output import ui, print_results_list
from linkora.cli.errors import IndexNotFoundError
from linkora.cli.context import AppContext

from linkora.log import get_logger

_log = get_logger(__name__)

# Type aliases for clarity
SearchMode = Literal["fulltext", "author", "vector", "hybrid"]
IndexType = Literal["fts", "vector"]


# ============================================================================
#  Unified Search Command
# ============================================================================


def cmd_search(args: argparse.Namespace, ctx: AppContext) -> None:
    """Unified search command with --mode flag.

    Modes:
        fulltext - Full-text search using FTS5
        author   - Search by author name
        vector   - Semantic vector search (requires faiss)
        hybrid   - Combined FTS + vector search
    """
    query = " ".join(args.query) if hasattr(args, "query") and args.query else ""
    mode: SearchMode = args.mode
    top_k = args.top if args.top is not None else ctx.config.index.top_k
    filters = {
        "year": getattr(args, "year", None),
        "journal": getattr(args, "journal", None),
        "paper_type": getattr(args, "paper_type", None),
    }

    try:
        handler = _SEARCH_HANDLERS.get(mode, _search_fulltext)
        handler(ctx, query, top_k, filters)
    except FileNotFoundError:
        raise IndexNotFoundError(str(ctx.config.index_db))


def _search_fulltext(ctx: AppContext, query: str, top_k: int, filters: dict) -> None:
    """Full-text search using FTS5."""
    with ctx.search_index() as idx:
        results = idx.search(query, top_k=top_k, **filters)
    print_results_list(results, f'Found {len(results)} papers (fulltext: "{query}")')


def _search_author(ctx: AppContext, query: str, top_k: int, filters: dict) -> None:
    """Search by author name."""
    with ctx.search_index() as idx:
        results = idx.search_author(query, top_k=top_k, **filters)
    print_results_list(results, f'Found {len(results)} papers (author: "{query}")')


def _search_vector(ctx: AppContext, query: str, top_k: int, filters: dict) -> None:
    """Semantic vector search."""
    try:
        with ctx.vector_index() as vidx:
            results = vidx.search(query, top_k=top_k, **filters)
        print_results_list(results, f'Found {len(results)} papers (vector: "{query}")')
    except ImportError as e:
        _log.error("Missing dependency for vector search: %s", e)


def _search_hybrid(ctx: AppContext, query: str, top_k: int, filters: dict) -> None:
    """Hybrid search (FTS + vector combined)."""
    _log.warning("Hybrid search not fully implemented, using fulltext fallback")
    with ctx.search_index() as idx:
        results = idx.search(query, top_k=top_k, **filters)
    print_results_list(results, f'Found {len(results)} papers (hybrid: "{query}")')


# Dictionary dispatch for search modes (per AGENT.md guidelines)
_SEARCH_HANDLERS: dict[SearchMode, Callable[[AppContext, str, int, dict], None]] = {
    "fulltext": _search_fulltext,
    "author": _search_author,
    "vector": _search_vector,
    "hybrid": _search_hybrid,
}


# ============================================================================
#  Top Cited Command
# ============================================================================


def cmd_top_cited(args: argparse.Namespace, ctx: AppContext) -> None:
    """Get top-cited papers."""
    top_k = args.top if args.top is not None else ctx.config.index.top_k
    filters = {
        "year": getattr(args, "year", None),
        "journal": getattr(args, "journal", None),
        "paper_type": getattr(args, "paper_type", None),
    }

    with ctx.search_index() as idx:
        results = idx.top_cited(top_k=top_k, **filters)
    print_results_list(results, f"Found {len(results)} papers (top-cited)")


# ============================================================================
#  Unified Index Command
# ============================================================================


def cmd_index(args: argparse.Namespace, ctx: AppContext) -> None:
    """Unified index command with --type flag.

    Types:
        fts     - Build FTS5 full-text index
        vector  - Build vector index (requires faiss)
    """
    index_type: IndexType = args.type
    rebuild = args.rebuild

    papers_dir = ctx.config.papers_dir
    if not papers_dir.exists():
        _log.error("papers_dir does not exist: %s", papers_dir)
        return

    store = ctx.paper_store()

    if index_type == "fts":
        action = "Rebuilding" if rebuild else "Building"
        ui(f"{action} FTS index: {papers_dir} -> {ctx.config.index_db}")
        with ctx.search_index() as idx:
            count = idx.rebuild(store) if rebuild else idx.update(store)
        ui(f"Done, indexed {count} papers.")
    elif index_type == "vector":
        try:
            with ctx.vector_index() as vidx:
                action = "Rebuilding" if rebuild else "Building"
                ui(f"{action} vectors: {papers_dir} -> {ctx.config.index_db}")
                count = vidx.rebuild(store) if rebuild else vidx.update(store)
            ui(f"Done, embedded {count} papers.")
        except ImportError as e:
            _log.error("Missing dependency for vector index: %s", e)


# ============================================================================
#  System Commands
# ============================================================================


def cmd_audit(args: argparse.Namespace, ctx: AppContext) -> None:
    """Audit paper data quality."""
    store = ctx.paper_store()
    issues = store.audit()
    if not issues:
        ui("No issues found.")
        return
    if args.severity:
        issues = [i for i in issues if i.severity == args.severity]
    ui(f"Found {len(issues)} issues:\n")
    for issue in issues:
        prefix = {"error": "[ERROR]", "warning": "[WARNING]", "info": "[INFO]"}.get(
            issue.severity, ""
        )
        ui(f"{prefix} {issue.rule}: {issue.message}")
        ui(f"  Paper: {issue.paper_id}\n")

    if args.fix:
        ui(f"Auto-fix not yet implemented for {len(issues)} issues")


def cmd_doctor(args: argparse.Namespace, ctx: AppContext) -> None:
    """Full health check (with network) or quick check (no network)."""
    from linkora.setup import cmd_doctor as doctor_check

    if args.light:
        from linkora.setup import cmd_check

        cmd_check(args)
    else:
        doctor_check(args)


def cmd_init(args: argparse.Namespace, ctx: AppContext) -> None:
    """Interactive setup wizard."""
    from linkora.setup import cmd_init as init_wizard

    init_wizard(args)


def cmd_metrics(args: argparse.Namespace, ctx: AppContext) -> None:
    """Show LLM metrics."""
    from datetime import datetime, timezone

    from linkora.metrics import (
        EventCategory,
        MetricsQuery,
        MetricsStore,
        TimeRange,
    )

    store = MetricsStore(ctx.config.metrics_db_path, session_id="cli")

    if args.summary:
        summary = store.summary()
        total_tokens = summary.total_tokens_in + summary.total_tokens_out
        ui(f"LLM calls: {summary.call_count}")
        ui(f"Input tokens: {summary.total_tokens_in}")
        ui(f"Output tokens: {summary.total_tokens_out}")
        ui(f"Total tokens: {total_tokens}")
        ui(f"Total duration: {summary.total_duration_s:.2f}s")
    else:
        category_str = args.category or "llm"
        try:
            category = EventCategory(category_str)
        except ValueError:
            category = None

        time_range = None
        if args.since:
            since_dt = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
            time_range = TimeRange(since=since_dt)

        query = MetricsQuery(
            category=category,
            time_range=time_range,
            limit=args.last,
        )
        result = store.query_events(query)

        if not result.events:
            ui("No metrics found.")
            return

        ui(f"Recent {len(result.events)} events:")
        for event in result.events:
            ts = event.get("timestamp", "")
            name = event.get("name", "")
            cat = event.get("category", "")
            duration = event.get("duration_s")
            tokens_in = event.get("tokens_in")
            tokens_out = event.get("tokens_out")
            model = event.get("model", "")
            status = event.get("status", "")

            ui(f"[{ts}] {cat}:{name} status={status}")
            if duration:
                ui(f"  duration={duration:.2f}s")
            if tokens_in or tokens_out:
                ui(f"  tokens: {tokens_in or 0} in, {tokens_out or 0} out")
            if model:
                ui(f"  model={model}")


# ============================================================================
#  Command Registration
# ============================================================================


def register_all(subparsers) -> None:
    """Register all CLI commands."""
    # Unified search command with --mode
    p = subparsers.add_parser("search", help="Search papers")
    p.set_defaults(func=cmd_search)
    p.add_argument("query", nargs="*", help="Search query")
    p.add_argument("--top", type=int, help="Max results")
    p.add_argument(
        "--mode",
        choices=["fulltext", "author", "vector", "hybrid"],
        default="fulltext",
        help="Search mode (default: fulltext)",
    )
    p.add_argument(
        "--year", type=str, default=None, help="Year filter: 2023 / 2020-2024 / 2020-"
    )
    p.add_argument(
        "--journal", type=str, default=None, help="Journal name filter (LIKE)"
    )
    p.add_argument(
        "--type",
        type=str,
        default=None,
        dest="paper_type",
        help="Paper type filter: review / journal-article etc. (LIKE)",
    )

    # Top cited command (separate from search)
    p = subparsers.add_parser("top-cited", help="Get top cited papers")
    p.set_defaults(func=cmd_top_cited)
    p.add_argument("--top", type=int, help="Max results")
    p.add_argument(
        "--year", type=str, default=None, help="Year filter: 2023 / 2020-2024 / 2020-"
    )
    p.add_argument(
        "--journal", type=str, default=None, help="Journal name filter (LIKE)"
    )
    p.add_argument(
        "--type",
        type=str,
        default=None,
        dest="paper_type",
        help="Paper type filter: review / journal-article etc. (LIKE)",
    )

    # Unified index command with --type
    p = subparsers.add_parser("index", help="Build search index")
    p.set_defaults(func=cmd_index)
    p.add_argument("--rebuild", action="store_true", help="Rebuild")
    p.add_argument(
        "--type",
        choices=["fts", "vector"],
        default="fts",
        help="Index type (default: fts)",
    )

    # Audit command
    p = subparsers.add_parser("audit", help="Audit data quality")
    p.set_defaults(func=cmd_audit)
    p.add_argument("--severity", choices=["error", "warning", "info"])
    p.add_argument("--fix", action="store_true", help="Auto fix")

    # Doctor command (health check)
    p = subparsers.add_parser("doctor", help="Health check")
    p.set_defaults(func=cmd_doctor)
    p.add_argument("--light", action="store_true", help="Quick check (no network)")
    p.add_argument("--fix", action="store_true", help="Auto-fix issues")

    # Init command (interactive setup wizard)
    p = subparsers.add_parser("init", help="Interactive setup wizard")
    p.set_defaults(func=cmd_init)
    p.add_argument(
        "--force", action="store_true", help="Force overwrite existing config"
    )

    # Metrics command
    p = subparsers.add_parser("metrics", help="Show metrics")
    p.set_defaults(func=cmd_metrics)
    p.add_argument("--last", type=int, default=20)
    p.add_argument("--category", default="llm")
    p.add_argument("--since")
    p.add_argument("--summary", action="store_true")


__all__ = ["register_all"]
