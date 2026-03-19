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
#  Add Command Helpers (moved from ingest/__init__.py)
# ============================================================================


def _parse_year_arg(year_val: str | None) -> tuple[int | None, int | None]:
    """Parse year argument into start/end tuple."""
    if not year_val:
        return None, None

    year_str = str(year_val)
    if "-" not in year_str:
        year = int(year_str)
        return year, year

    parts = year_str.split("-", 1)
    start = int(parts[0]) if parts[0] else None
    end = int(parts[1]) if parts[1] else None
    return start, end


def _build_query(
    doi_val: str,
    issn_val: str,
    author_val: str,
    title_val: str,
    year_start: int | None,
    year_end: int | None,
    freeform_query: str,
):
    """Build PaperQuery from parsed arguments."""
    from linkora.sources.protocol import PaperQuery

    has_structured = any([doi_val, issn_val, author_val, title_val, year_start])

    if has_structured:
        return PaperQuery(
            doi=doi_val,
            issn=issn_val,
            author=author_val,
            title=title_val,
            year_start=year_start,
            year_end=year_end,
        )

    if freeform_query:
        return _parse_freeform_query(freeform_query)

    return PaperQuery()


def _parse_freeform_query(query_str: str):
    """Parse free-form query string into PaperQuery."""
    import re

    from linkora.sources.protocol import PaperQuery

    query_str = query_str.strip()

    # DOI detection
    if re.match(r"^10\.\d{4,}/", query_str):
        return PaperQuery(doi=query_str)

    # arXiv detection
    if re.match(r"^\d{4}\.\d{4,5}$", query_str):
        return PaperQuery(title=query_str)

    # Default: title search
    return PaperQuery(title=query_str)


def cmd_add(args: argparse.Namespace, ctx: AppContext) -> None:
    """Add papers from various sources."""
    # Import core matching functions (local - not via ingest/__init__.py)
    from linkora.ingest.matching import DefaultDispatcher, match_papers

    # Extract query arguments with type hints (AGENT.md compliant)
    doi_val: str = getattr(args, "doi", "") or ""
    issn_val: str = getattr(args, "issn", "") or ""
    author_val: str = getattr(args, "author", "") or ""
    title_val: str = getattr(args, "title", "") or ""
    freeform_query: str = getattr(args, "query", "") or ""

    # Parse year and build query (use local helpers)
    year_start, year_end = _parse_year_arg(getattr(args, "year", None))
    query = _build_query(
        doi_val, issn_val, author_val, title_val, year_start, year_end, freeform_query
    )

    if query.is_empty:
        ui(
            "Error: Query cannot be empty. Use --doi, --issn, --author, --title, or free-form query."
        )
        return

    # Setup dispatcher with injected dependencies (context separation)
    config = ctx.config
    local_pdf_dir = config.resolve_local_source_dir()
    http_client = ctx.http_client()

    try:
        dispatcher = DefaultDispatcher(
            local_pdf_dir=local_pdf_dir, http_client=http_client
        )

        limit: int = getattr(args, "limit", 5) or 5
        ui(f"Searching for papers: {query}")
        ui(f"Using {len(dispatcher.select(query))} source(s)")

        # Match papers
        matched = match_papers(query=query, dispatcher=dispatcher, limit=limit)

        if not matched:
            ui("No papers found.")
            return

        ui(f"Found {len(matched)} papers:")
        for i, paper in enumerate(matched, 1):
            score = paper.get("_match_score", 0)
            title = paper.get("title", "Untitled")[:60]
            doi = paper.get("doi", "")
            source = paper.get("_match_source", "unknown")
            ui(f"  {i}. {title}...")
            ui(f"     DOI: {doi} | Score: {score:.0f} | Source: {source}")

        if getattr(args, "dry_run", False):
            ui("(dry-run mode, not saving)")
            return

        # Process papers (placeholder for actual implementation)
        ui(f"\nAdd command implementation pending - found {len(matched)} papers to add")
    finally:
        if http_client:
            http_client.close()


def cmd_enrich(args: argparse.Namespace, ctx: AppContext) -> None:
    """Enrich papers with TOC and conclusions.

    Uses PaperEnricher from loader.py with context injection.
    """
    paper_id = getattr(args, "paper", None)
    extract_toc = getattr(args, "toc", False)
    extract_conclusion = getattr(args, "conclusion", False)
    limit = getattr(args, "limit", None)
    force = getattr(args, "force", False)

    # Default: extract both if neither specified
    if not extract_toc and not extract_conclusion:
        extract_toc = True
        extract_conclusion = True

    # Get enricher from context (lazy init)
    enricher = ctx.paper_enricher()
    store = ctx.paper_store()

    # Get papers to process
    if paper_id:
        papers = [paper_id]
    else:
        papers = [p.name for p in store.iter_papers()]
        if limit:
            papers = papers[:limit]

    if not papers:
        ui("No papers found to enrich")
        return

    ui(
        f"Enriching {len(papers)} paper(s) (toc={extract_toc}, conclusion={extract_conclusion}, force={force})"
    )

    success_count = 0
    for pid in papers:
        try:
            toc_ok = False
            conc_ok = False

            if extract_toc:
                toc_ok = enricher.enrich_toc(pid, force=force)

            if extract_conclusion:
                conc_ok = enricher.enrich_conclusion(pid, force=force)

            if toc_ok or conc_ok:
                success_count += 1
                _log.debug("Enriched %s: toc=%s, conclusion=%s", pid, toc_ok, conc_ok)

        except Exception as e:
            _log.error("Failed to enrich %s: %s", pid, e)

    ui(f"Enriched {success_count}/{len(papers)} papers successfully")


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

    papers_store_dir = ctx.config.papers_store_dir
    if not papers_store_dir.exists():
        _log.error("papers_store_dir does not exist: %s", papers_store_dir)
        return

    store = ctx.paper_store()

    if index_type == "fts":
        action = "Rebuilding" if rebuild else "Building"
        ui(f"{action} FTS index: {papers_store_dir} -> {ctx.config.index_db}")
        with ctx.search_index() as idx:
            count = idx.rebuild(store) if rebuild else idx.update(store)
        ui(f"Done, indexed {count} papers.")
    elif index_type == "vector":
        try:
            with ctx.vector_index() as vidx:
                action = "Rebuilding" if rebuild else "Building"
                ui(f"{action} vectors: {papers_store_dir} -> {ctx.config.index_db}")
                count = vidx.rebuild(store) if rebuild else vidx.update(store)
            ui(f"Done, embedded {count} papers.")
        except ImportError as e:
            _log.error("Missing dependency for vector index: %s", e)


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
#  System Commands
# ============================================================================


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

    """Register 'add' command with argparse."""
    p = subparsers.add_parser("add", help="Add papers from various sources")
    p.set_defaults(func=cmd_add)

    # Structured query arguments (recommended)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--doi", help="DOI identifier (exact match)")
    g.add_argument("--issn", help="Journal ISSN")
    g.add_argument("--author", help="Author name")
    g.add_argument("--title", help="Paper title")

    # Year filter
    p.add_argument("--year", help="Year or range (e.g., 2024, 2020-2024)")

    # Free-form fallback (for backward compatibility)
    p.add_argument("query", nargs="?", help="Free-form query (fallback)")

    # Options
    p.add_argument("--source", "-s", help="Primary source (local, openalex, auto)")
    p.add_argument(
        "--limit", "-n", type=int, default=5, help="Max papers to fetch (default: 5)"
    )
    p.add_argument("--cache", "-c", action="store_true", help="Cache as symlinks")
    p.add_argument("--dry-run", action="store_true", help="Preview only")

    """Register 'enrich' command with argparse."""
    p = subparsers.add_parser(
        "enrich",
        help="Enrich papers with TOC and conclusions",
    )
    p.set_defaults(func=cmd_enrich)
    p.add_argument("--paper", type=str, help="Specific paper ID (directory name)")
    p.add_argument("--toc", action="store_true", help="Extract TOC")
    p.add_argument("--conclusion", action="store_true", help="Extract conclusion")
    p.add_argument("--limit", type=int, help="Max papers to process")
    p.add_argument("--force", action="store_true", help="Force re-extraction")

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

    # Metrics command
    p = subparsers.add_parser("metrics", help="Show metrics")
    p.set_defaults(func=cmd_metrics)
    p.add_argument("--last", type=int, default=20)
    p.add_argument("--category", default="llm")
    p.add_argument("--since")
    p.add_argument("--summary", action="store_true")

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


__all__ = ["register_all"]
