"""CLI command handlers - grouped by functionality."""

from __future__ import annotations

import argparse
import logging

from scholaraio.cli.args import add_filter_args, resolve_top_k
from scholaraio.cli.output import ui, print_results_list
from scholaraio.cli.errors import IndexNotFoundError
from scholaraio.index import SearchIndex
from scholaraio.papers import PaperStore


_log = logging.getLogger(__name__)


# ============================================================================
#  Search Commands (index.py, vectors.py)
# ============================================================================


def cmd_search(args: argparse.Namespace, cfg) -> None:
    """Full-text search using FTS5."""
    query = " ".join(args.query)
    try:
        with SearchIndex(cfg.index_db) as idx:
            results = idx.search(
                query,
                top_k=resolve_top_k(args, cfg.search.top_k),
                year=args.year,
                journal=args.journal,
                paper_type=args.paper_type,
            )
    except FileNotFoundError:
        raise IndexNotFoundError(str(cfg.index_db))
    print_results_list(results, f'Found {len(results)} papers (query: "{query}")')


def cmd_search_author(args: argparse.Namespace, cfg) -> None:
    """Search by author name."""
    query = " ".join(args.query)
    try:
        with SearchIndex(cfg.index_db) as idx:
            results = idx.search_author(
                query,
                top_k=resolve_top_k(args, cfg.search.top_k),
                year=args.year,
                journal=args.journal,
                paper_type=args.paper_type,
            )
    except FileNotFoundError:
        raise IndexNotFoundError(str(cfg.index_db))
    print_results_list(results, f'Found {len(results)} papers (author: "{query}")')


def cmd_vsearch(args: argparse.Namespace, cfg) -> None:
    """Semantic vector search."""
    query = " ".join(args.query)
    try:
        from scholaraio.vectors import VectorIndex

        with VectorIndex(cfg.index_db) as vidx:
            results = vidx.search(
                query,
                top_k=resolve_top_k(args, cfg.embed.top_k),
                year=args.year,
                journal=args.journal,
                paper_type=args.paper_type,
            )
    except FileNotFoundError:
        raise IndexNotFoundError(str(cfg.index_db))
    print_results_list(results, f'Found {len(results)} papers (vector: "{query}")')


def cmd_usearch(args: argparse.Namespace, cfg) -> None:
    """Unified/hybrid search."""
    query = " ".join(args.query)
    try:
        with SearchIndex(cfg.index_db) as idx:
            results = idx.unified_search(
                query,
                top_k=resolve_top_k(args, cfg.search.top_k),
                year=args.year,
                journal=args.journal,
                paper_type=args.paper_type,
            )
    except FileNotFoundError:
        raise IndexNotFoundError(str(cfg.index_db))
    print_results_list(results, f'Found {len(results)} papers (hybrid: "{query}")')


def cmd_top_cited(args: argparse.Namespace, cfg) -> None:
    """Get top-cited papers."""
    try:
        with SearchIndex(cfg.index_db) as idx:
            results = idx.top_cited(
                top_k=resolve_top_k(args, cfg.search.top_k),
                year=args.year,
                journal=args.journal,
                paper_type=args.paper_type,
            )
    except FileNotFoundError:
        raise IndexNotFoundError(str(cfg.index_db))
    print_results_list(results, f"Found {len(results)} papers (top-cited)")


# ============================================================================
#  Index Commands (index.py, vectors.py)
# ============================================================================


def cmd_index(args: argparse.Namespace, cfg) -> None:
    """Build FTS5 index."""
    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("papers_dir does not exist: %s", papers_dir)
        return
    action = "Rebuilding" if args.rebuild else "Building"
    ui(f"{action} index: {papers_dir} -> {cfg.index_db}")
    with SearchIndex(cfg.index_db) as idx:
        count = idx.rebuild(papers_dir) if args.rebuild else idx.update(papers_dir)
    ui(f"Done, indexed {count} papers.")


def cmd_embed(args: argparse.Namespace, cfg) -> None:
    """Build vector index."""
    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("papers_dir does not exist: %s", papers_dir)
        return
    try:
        from scholaraio.vectors import VectorIndex

        action = "Rebuilding" if args.rebuild else "Building"
        ui(f"{action} vectors: {papers_dir} -> {cfg.index_db}")
        with VectorIndex(cfg.index_db) as vidx:
            count = (
                vidx.rebuild(papers_dir) if args.rebuild else vidx.update(papers_dir)
            )
        ui(f"Done, embedded {count} papers.")
    except ImportError as e:
        _log.error("Missing dependency: %s", e)


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


def cmd_metrics(args: argparse.Namespace, cfg) -> None:
    """Show LLM metrics."""
    from scholaraio.metrics import show_summary, show_metrics

    if args.summary:
        show_summary(category=args.category)
    else:
        show_metrics(
            cfg.metrics_db_path,
            last=args.last,
            category=args.category,
            since=args.since,
        )


# ============================================================================
#  Command Registration
# ============================================================================


def register_all(subparsers) -> None:
    """Register all CLI commands."""
    # Search commands
    p = subparsers.add_parser("search", help="Full-text search")
    p.set_defaults(func=cmd_search)
    p.add_argument("query", nargs="+", help="Search query")
    p.add_argument("--top", type=int, help="Max results")
    add_filter_args(p)

    p = subparsers.add_parser("search-author", help="Search by author")
    p.set_defaults(func=cmd_search_author)
    p.add_argument("query", nargs="+", help="Author name")
    p.add_argument("--top", type=int, help="Max results")
    add_filter_args(p)

    p = subparsers.add_parser("vsearch", help="Vector search")
    p.set_defaults(func=cmd_vsearch)
    p.add_argument("query", nargs="+", help="Search query")
    p.add_argument("--top", type=int, help="Max results")
    add_filter_args(p)

    p = subparsers.add_parser("usearch", help="Hybrid search")
    p.set_defaults(func=cmd_usearch)
    p.add_argument("query", nargs="+", help="Search query")
    p.add_argument("--top", type=int, help="Max results")
    add_filter_args(p)

    p = subparsers.add_parser("top-cited", help="Top cited papers")
    p.set_defaults(func=cmd_top_cited)
    p.add_argument("--top", type=int, help="Max results")
    add_filter_args(p)

    # Index commands
    p = subparsers.add_parser("index", help="Build FTS5 index")
    p.set_defaults(func=cmd_index)
    p.add_argument("--rebuild", action="store_true", help="Rebuild")

    p = subparsers.add_parser("embed", help="Build vector index")
    p.set_defaults(func=cmd_embed)
    p.add_argument("--rebuild", action="store_true", help="Rebuild")

    # System commands
    p = subparsers.add_parser("audit", help="Audit data quality")
    p.set_defaults(func=cmd_audit)
    p.add_argument("--severity", choices=["error", "warning", "info"])
    p.add_argument("--fix", action="store_true", help="Auto fix")

    p = subparsers.add_parser("setup", help="Setup wizard")
    p.set_defaults(func=cmd_setup)
    p_sub = p.add_subparsers(dest="action")
    p_check = p_sub.add_parser("check", help="Check environment")
    p_check.add_argument("--lang", choices=["en", "zh"], default="zh")

    p = subparsers.add_parser("metrics", help="Show metrics")
    p.set_defaults(func=cmd_metrics)
    p.add_argument("--last", type=int, default=20)
    p.add_argument("--category", default="llm")
    p.add_argument("--since")
    p.add_argument("--summary", action="store_true")


__all__ = ["register_all"]
