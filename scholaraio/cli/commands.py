"""CLI command handlers - unified commands with context injection."""

from __future__ import annotations

import argparse
from typing import Literal

from scholaraio.cli.args import add_filter_args, resolve_top_k
from scholaraio.cli.output import ui, print_results_list
from scholaraio.cli.errors import IndexNotFoundError
from scholaraio.index import SearchIndex
from scholaraio.papers import PaperStore

from scholaraio.log import get_logger

_log = get_logger(__name__)

# Type aliases for clarity
SearchMode = Literal["fts", "author", "vector", "hybrid", "cited"]
IndexType = Literal["fts", "vector"]


# ============================================================================
#  Unified Search Command
# ============================================================================


def cmd_search(args: argparse.Namespace, cfg) -> None:
    """Unified search command with --mode flag.

    Modes:
        fts     - Full-text search using FTS5
        author  - Search by author name
        vector  - Semantic vector search (requires faiss)
        hybrid  - Combined FTS + vector search
        cited   - Top cited papers
    """
    query = " ".join(args.query) if hasattr(args, "query") and args.query else ""
    mode: SearchMode = getattr(args, "mode", "fts")
    top_k = resolve_top_k(args, cfg.index.top_k)
    year = getattr(args, "year", None)
    journal = getattr(args, "journal", None)
    paper_type = getattr(args, "paper_type", None)

    try:
        if mode == "fts":
            _search_fts(cfg, query, top_k, year, journal, paper_type)
        elif mode == "author":
            _search_author(cfg, query, top_k, year, journal, paper_type)
        elif mode == "vector":
            _search_vector(cfg, query, top_k, year, journal, paper_type)
        elif mode == "hybrid":
            _search_hybrid(cfg, query, top_k, year, journal, paper_type)
        elif mode == "cited":
            _search_cited(cfg, top_k, year, journal, paper_type)
    except FileNotFoundError:
        raise IndexNotFoundError(str(cfg.index_db))


def _search_fts(cfg, query: str, top_k: int, year, journal, paper_type) -> None:
    """Full-text search using FTS5."""
    with SearchIndex(cfg.index_db) as idx:
        results = idx.search(
            query, top_k=top_k, year=year, journal=journal, paper_type=paper_type
        )
    print_results_list(results, f'Found {len(results)} papers (FTS: "{query}")')


def _search_author(cfg, query: str, top_k: int, year, journal, paper_type) -> None:
    """Search by author name."""
    with SearchIndex(cfg.index_db) as idx:
        results = idx.search_author(
            query, top_k=top_k, year=year, journal=journal, paper_type=paper_type
        )
    print_results_list(results, f'Found {len(results)} papers (author: "{query}")')


def _search_vector(cfg, query: str, top_k: int, year, journal, paper_type) -> None:
    """Semantic vector search."""
    try:
        from scholaraio.index import VectorIndex

        with VectorIndex(cfg.index_db) as vidx:
            results = vidx.search(
                query, top_k=top_k, year=year, journal=journal, paper_type=paper_type
            )
        print_results_list(results, f'Found {len(results)} papers (vector: "{query}")')
    except ImportError as e:
        _log.error("Missing dependency for vector search: %s", e)


def _search_hybrid(cfg, query: str, top_k: int, year, journal, paper_type) -> None:
    """Hybrid search (FTS + vector combined)."""
    # Fallback to FTS - hybrid requires implementation
    _log.warning("Hybrid search not fully implemented, using FTS fallback")
    with SearchIndex(cfg.index_db) as idx:
        results = idx.search(
            query, top_k=top_k, year=year, journal=journal, paper_type=paper_type
        )
    print_results_list(results, f'Found {len(results)} papers (hybrid: "{query}")')


def _search_cited(cfg, top_k: int, year, journal, paper_type) -> None:
    """Get top-cited papers."""
    with SearchIndex(cfg.index_db) as idx:
        results = idx.top_cited(
            top_k=top_k, year=year, journal=journal, paper_type=paper_type
        )
    print_results_list(results, f"Found {len(results)} papers (top-cited)")


# ============================================================================
#  Unified Index Command
# ============================================================================


def cmd_index(args: argparse.Namespace, cfg) -> None:
    """Unified index command with --type flag.

    Types:
        fts     - Build FTS5 full-text index
        vector  - Build vector index (requires faiss)
    """
    index_type: IndexType = getattr(args, "type", "fts")
    rebuild = getattr(args, "rebuild", False)

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("papers_dir does not exist: %s", papers_dir)
        return

    store = PaperStore(papers_dir)

    if index_type == "fts":
        action = "Rebuilding" if rebuild else "Building"
        ui(f"{action} FTS index: {papers_dir} -> {cfg.index_db}")
        with SearchIndex(cfg.index_db) as idx:
            count = idx.rebuild(store) if rebuild else idx.update(store)
        ui(f"Done, indexed {count} papers.")
    elif index_type == "vector":
        try:
            from scholaraio.index import VectorIndex

            action = "Rebuilding" if rebuild else "Building"
            ui(f"{action} vectors: {papers_dir} -> {cfg.index_db}")
            with VectorIndex(cfg.index_db) as vidx:
                count = vidx.rebuild(store) if rebuild else vidx.update(store)
            ui(f"Done, embedded {count} papers.")
        except ImportError as e:
            _log.error("Missing dependency for vector index: %s", e)


# ============================================================================
#  System Commands
# ============================================================================


def cmd_audit(args: argparse.Namespace, cfg) -> None:
    """Audit paper data quality."""
    store = PaperStore(cfg.papers_dir)
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


def cmd_setup(args: argparse.Namespace, cfg) -> None:
    """Setup wizard."""
    from scholaraio.setup import check_environment

    if args.action == "check":
        check_environment(lang=args.lang)
    else:
        from scholaraio.setup import main as setup_main

        setup_main()


def cmd_check(args: argparse.Namespace, cfg) -> None:
    """Quick environment diagnostics (no network)."""
    from scholaraio.setup import cmd_check

    cmd_check(args)


def cmd_doctor(args: argparse.Namespace, cfg) -> None:
    """Full health check (with network)."""
    from scholaraio.setup import cmd_doctor

    cmd_doctor(args)


def cmd_init(args: argparse.Namespace, cfg) -> None:
    """Interactive setup wizard."""
    from scholaraio.setup import cmd_init

    cmd_init(args)


def cmd_metrics(args: argparse.Namespace, cfg) -> None:
    """Show LLM metrics."""
    from datetime import datetime, timezone

    from scholaraio.metrics import (
        EventCategory,
        MetricsQuery,
        MetricsStore,
        TimeRange,
    )
    from scholaraio.cli.output import ui

    store = MetricsStore(cfg.metrics_db_path, session_id="cli")

    if args.summary:
        category = args.category
        summary = store.summary()
        total_tokens = summary.total_tokens_in + summary.total_tokens_out
        ui(f"LLM 调用次数: {summary.call_count}")
        ui(f"输入 tokens: {summary.total_tokens_in}")
        ui(f"输出 tokens: {summary.total_tokens_out}")
        ui(f"总 tokens: {total_tokens}")
        ui(f"总耗时: {summary.total_duration_s:.2f}s")
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
        choices=["fts", "author", "vector", "hybrid", "cited"],
        default="fts",
        help="Search mode (default: fts)",
    )
    add_filter_args(p)

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

    # System commands
    p = subparsers.add_parser("audit", help="Audit data quality")
    p.set_defaults(func=cmd_audit)
    p.add_argument("--severity", choices=["error", "warning", "info"])
    p.add_argument("--fix", action="store_true", help="Auto fix")

    p = subparsers.add_parser("setup", help="Setup wizard")
    p.set_defaults(func=cmd_setup)
    p_sub = p.add_subparsers(dest="action")
    p_sub.add_parser("check", help="Check environment")
    p_sub.add_parser("wizard", help="Interactive setup wizard")

    p = subparsers.add_parser(
        "check", help="Quick environment diagnostics (no network)"
    )
    p.set_defaults(func=cmd_check)

    p = subparsers.add_parser("doctor", help="Full health check (with network)")
    p.set_defaults(func=cmd_doctor)

    p = subparsers.add_parser("init", help="Interactive setup wizard")
    p.set_defaults(func=cmd_init)
    p.add_argument(
        "--force", action="store_true", help="Force overwrite existing config"
    )

    p = subparsers.add_parser("metrics", help="Show metrics")
    p.set_defaults(func=cmd_metrics)
    p.add_argument("--last", type=int, default=20)
    p.add_argument("--category", default="llm")
    p.add_argument("--since")
    p.add_argument("--summary", action="store_true")


__all__ = ["register_all"]
