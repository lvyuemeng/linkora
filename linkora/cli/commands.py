"""
commands.py — CLI command handlers.

All handlers receive (args: argparse.Namespace, ctx: AppContext).
They access workspace paths via ctx.workspace and workspace
management via ctx.store.  They never access private internals of
AppConfig or WorkspaceStore.

Config file read/write
──────────────────────
``cmd_config_set`` writes to the global config YAML.  To preserve
comments and key ordering we use ruamel.yaml when available, falling
back to plain PyYAML with a notice that comments will be lost.

There is no workspace-local config.  All settings live in the single
global config file.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable, Literal

from linkora.cli.context import AppContext
from linkora.cli.errors import IndexNotFoundError
from linkora.cli.output import ui, print_results_list
from linkora.config import ConfigLoader
from linkora.log import get_logger

_log = get_logger(__name__)

SearchMode = Literal["fulltext", "author", "vector", "hybrid"]
IndexType = Literal["fts", "vector"]


# ============================================================================
#  YAML round-trip helpers
# ============================================================================


def _load_yaml_roundtrip(path: Path) -> tuple[Any, str]:
    """
    Load a YAML file for in-place editing.

    Returns (document, engine) where engine is either "ruamel" or "pyyaml".
    With ruamel.yaml the document preserves comments and key order.
    With pyyaml it is a plain dict (comments will be lost on write).
    """
    try:
        from ruamel.yaml import YAML  # type: ignore[import]

        yaml = YAML()
        yaml.preserve_quotes = True
        with path.open(encoding="utf-8") as f:
            return yaml.load(f) or {}, "ruamel"
    except ImportError:
        import yaml as pyyaml

        data = pyyaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data, "pyyaml"


def _dump_yaml_roundtrip(data: Any, path: Path, engine: str) -> None:
    """Write *data* back to *path* using the same engine it was loaded with."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if engine == "ruamel":
        from ruamel.yaml import YAML  # type: ignore[import]

        yaml = YAML()
        yaml.preserve_quotes = True
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
    else:
        import yaml as pyyaml

        path.write_text(
            pyyaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )


def _set_nested(doc: Any, parts: list[str], value: Any) -> None:
    """
    Set a nested key path in *doc* (dict or ruamel CommentedMap) to *value*.

    Creates intermediate dicts as needed.
    """
    current = doc
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            # Preserve ruamel type if possible.
            try:
                from ruamel.yaml.comments import CommentedMap  # type: ignore[import]

                current[part] = CommentedMap()
            except ImportError:
                current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _get_nested(doc: dict, parts: list[str]) -> Any:
    """Return the value at *parts* key path, or ``None`` if not found."""
    current: Any = doc
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _parse_cli_value(raw: str) -> Any:
    """
    Coerce a CLI string to the most specific Python type.

    Conversion order: bool → int → float → str.
    """
    lower = raw.strip().lower()
    if lower in ("true", "yes", "on"):
        return True
    if lower in ("false", "no", "off"):
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _resolve_config_write_path(ctx: AppContext) -> Path:
    """
    Return the path to write config changes to.

    Uses the currently active config file when one exists; otherwise
    returns the canonical default write path so a new file is created
    in the right place.
    """
    from linkora.config import get_config_path

    return get_config_path() or ConfigLoader.default_write_path()


# ============================================================================
#  Config commands
# ============================================================================


def cmd_config_show(args: argparse.Namespace, ctx: AppContext) -> None:
    """
    Show configuration or workspace information.

    Subcommands (via positional field arg and flags):
      linkora config show               — active workspace summary
      linkora config show --all         — all workspaces
      linkora config show <field>       — single effective config value
                                          e.g.  llm.model  or  index.top_k
    """
    if getattr(args, "all", False):
        _show_all_workspaces(ctx)
        return

    field: str | None = getattr(args, "field", None)
    if field:
        _show_config_field(field, ctx)
        return

    _show_workspace(getattr(args, "workspace", None) or ctx.workspace_name, ctx)


def _show_all_workspaces(ctx: AppContext) -> None:
    workspaces = ctx.store.list_workspaces()
    default_ws = ctx.store.get_default()
    ui("All workspaces:\n")
    for name in workspaces:
        meta = ctx.store.get_metadata(name)
        count = ctx.store.get_paper_count(name)
        marker = " *" if name == default_ws else "  "
        desc = meta.description or "(no description)"
        ui(f"{marker} {name:<18} {desc}  ({count} papers)")
    ui("\n* = default workspace")


def _show_config_field(field: str, ctx: AppContext) -> None:
    """Print the effective (env-resolved) value of a dot-separated field."""
    import yaml

    # Serialise AppConfig to a plain dict via Pydantic, then navigate it.
    # We use model_dump() so nested Pydantic models become plain dicts.
    config_dict = ctx.config.model_dump()
    parts = field.split(".")
    value = _get_nested(config_dict, parts)

    if value is None:
        ui(f"Field '{field}' not found in config.")
        return

    ui(yaml.dump({field: value}, allow_unicode=True, default_flow_style=False).rstrip())


def _show_workspace(name: str, ctx: AppContext) -> None:
    meta = ctx.store.get_metadata(name)
    count = ctx.store.get_paper_count(name)
    default_ws = ctx.store.get_default()
    paths = ctx.store.paths(name)

    from linkora.config import get_config_path

    active_config = get_config_path()

    ui(f"Workspace: {name}" + (" (default)" if name == default_ws else ""))
    ui(f"  Description : {meta.description or '(none)'}")
    ui(f"  Papers      : {count}")
    ui(f"  Data dir    : {paths.workspace_dir}")
    ui(f"  Papers dir  : {paths.papers_dir}")
    ui(f"  Index DB    : {paths.index_db}")
    ui(f"  Config file : {active_config or '(built-in defaults)'}")


def cmd_config_set(args: argparse.Namespace, ctx: AppContext) -> None:
    """
    Set a configuration value in the global config file.

    Usage:
        linkora config set llm.model gpt-4o
        linkora config set index.top_k 30
        linkora config set sources.local.enabled false

    Values are coerced: "true"/"false" → bool, numeric strings → int/float.
    The file is rewritten preserving comments when ruamel.yaml is installed.
    """
    field: str = args.field
    raw_value: str = args.value
    value = _parse_cli_value(raw_value)

    # Reject attempts to set unknown top-level sections.
    _VALID_TOP_KEYS = {"sources", "index", "llm", "ingest", "topics", "logging"}
    top_key = field.split(".")[0]
    if top_key not in _VALID_TOP_KEYS:
        ui(
            f"Error: Unknown config section '{top_key}'. "
            f"Valid sections: {', '.join(sorted(_VALID_TOP_KEYS))}"
        )
        return

    config_path = _resolve_config_write_path(ctx)

    if config_path.exists():
        doc, engine = _load_yaml_roundtrip(config_path)
    else:
        doc, engine = {}, "pyyaml"
        ui(f"Creating new config file at {config_path}")

    if engine == "pyyaml":
        ui("Note: ruamel.yaml not installed — comments will not be preserved.")

    _set_nested(doc, field.split("."), value)
    _dump_yaml_roundtrip(doc, config_path, engine)
    ui(f"Set {field} = {value!r}  ({config_path})")


def cmd_config_mv(args: argparse.Namespace, ctx: AppContext) -> None:
    """
    Rename or relocate a workspace.

    Usage:
        linkora config mv old-name new-name
        linkora config mv my-ws /data/linkora/my-ws
    """
    source: str = args.source
    target: str = args.target

    src_paths = ctx.store.paths(source)
    target_p = Path(target)
    dst_display = str(
        target_p
        if target_p.is_absolute()
        else ctx.store.data_root / "workspace" / target
    )

    ui(f"Migrating workspace '{source}' → '{target}'")
    ui(f"  Source : {src_paths.workspace_dir}")
    ui(f"  Target : {dst_display}")

    try:
        count = ctx.store.migrate(source, target)
    except FileNotFoundError as exc:
        ui(f"Error: {exc}")
        return
    except FileExistsError as exc:
        ui(f"Error: {exc}")
        return

    new_name = target_p.name if target_p.is_absolute() else target
    ui(f"Done — {count} paper(s) migrated.")

    if ctx.workspace_name == source:
        ui(f"\nNote: '{source}' was your active workspace.")
        ui(f"Use '--workspace {new_name}' to switch to it.")


def cmd_config_set_default(args: argparse.Namespace, ctx: AppContext) -> None:
    """Set the default workspace."""
    name: str = args.workspace
    try:
        old = ctx.store.get_default()
        ctx.store.set_default(name)
        ui(f"Default workspace: '{old}' → '{name}'")
    except KeyError as exc:
        ui(f"Error: {exc}")


def cmd_config_set_meta(args: argparse.Namespace, ctx: AppContext) -> None:
    """
    Set workspace metadata.

    Settable fields:
        description   — free-text description of the workspace

    Usage:
        linkora config set-meta description "My ML papers"
        linkora config set-meta description "My ML papers" --workspace ml
    """
    name: str = getattr(args, "workspace", None) or ctx.workspace_name
    field: str = args.field
    value: str = args.value

    if field == "description":
        ctx.store.set_metadata(name, description=value)
        ui(f"Updated workspace '{name}' description: \"{value}\"")
    else:
        ui(f"Error: Unknown metadata field '{field}'. Available fields: description")


# ============================================================================
#  Search commands
# ============================================================================


def cmd_search(args: argparse.Namespace, ctx: AppContext) -> None:
    """Unified search with --mode flag (fulltext / author / vector / hybrid)."""
    query = " ".join(args.query) if getattr(args, "query", None) else ""
    mode: SearchMode = args.mode
    top_k: int = args.top if args.top is not None else ctx.config.index.top_k
    filters = _extract_filters(args)

    try:
        _SEARCH_DISPATCH[mode](ctx, query, top_k, filters)
    except FileNotFoundError:
        raise IndexNotFoundError(str(ctx.workspace.index_db))


def _extract_filters(args: argparse.Namespace) -> dict:
    return {
        "year": getattr(args, "year", None),
        "journal": getattr(args, "journal", None),
        "paper_type": getattr(args, "paper_type", None),
    }


def _search_fulltext(ctx: AppContext, query: str, top_k: int, filters: dict) -> None:
    with ctx.search_index() as idx:
        results = idx.search(query, top_k=top_k, **filters)
    print_results_list(results, f'Found {len(results)} papers (fulltext: "{query}")')


def _search_author(ctx: AppContext, query: str, top_k: int, filters: dict) -> None:
    with ctx.search_index() as idx:
        results = idx.search_author(query, top_k=top_k, **filters)
    print_results_list(results, f'Found {len(results)} papers (author: "{query}")')


def _search_vector(ctx: AppContext, query: str, top_k: int, filters: dict) -> None:
    try:
        with ctx.vector_index() as vidx:
            results = vidx.search(query, top_k=top_k, **filters)
        print_results_list(results, f'Found {len(results)} papers (vector: "{query}")')
    except ImportError as exc:
        ui(f"Vector search unavailable: {exc}")
        ui("Install faiss-cpu to enable vector search.")


def _search_hybrid(ctx: AppContext, query: str, top_k: int, filters: dict) -> None:
    _log.warning("Hybrid search not yet implemented; falling back to fulltext.")
    _search_fulltext(ctx, query, top_k, filters)


_SEARCH_DISPATCH: dict[SearchMode, Callable[[AppContext, str, int, dict], None]] = {
    "fulltext": _search_fulltext,
    "author": _search_author,
    "vector": _search_vector,
    "hybrid": _search_hybrid,
}


def cmd_top_cited(args: argparse.Namespace, ctx: AppContext) -> None:
    """List top-cited papers."""
    top_k: int = args.top if args.top is not None else ctx.config.index.top_k
    filters = _extract_filters(args)
    with ctx.search_index() as idx:
        results = idx.top_cited(top_k=top_k, **filters)
    print_results_list(results, f"Found {len(results)} papers (top-cited)")


# ============================================================================
#  Add / Enrich / Index / Audit
# ============================================================================


def _parse_year_arg(year_val: str | None) -> tuple[int | None, int | None]:
    if not year_val:
        return None, None
    s = str(year_val)
    if "-" not in s:
        y = int(s)
        return y, y
    lo, hi = s.split("-", 1)
    return (int(lo) if lo else None), (int(hi) if hi else None)


def cmd_add(args: argparse.Namespace, ctx: AppContext) -> None:
    """Add papers from various sources."""
    from linkora.ingest.matching import DefaultDispatcher, match_papers
    from linkora.sources.protocol import PaperQuery

    doi: str = getattr(args, "doi", "") or ""
    issn: str = getattr(args, "issn", "") or ""
    author: str = getattr(args, "author", "") or ""
    title: str = getattr(args, "title", "") or ""
    freeform: str = getattr(args, "query", "") or ""
    year_start, year_end = _parse_year_arg(getattr(args, "year", None))

    if any((doi, issn, author, title, year_start)):
        query = PaperQuery(
            doi=doi,
            issn=issn,
            author=author,
            title=title,
            year_start=year_start,
            year_end=year_end,
        )
    elif freeform:
        query = _parse_freeform(freeform)
    else:
        ui("Error: provide --doi, --issn, --author, --title, or a free-form query.")
        return

    if query.is_empty:
        ui("Error: query is empty.")
        return

    local_dirs = ctx.resolve_local_source_paths()
    http = ctx.http_client()

    try:
        dispatcher = DefaultDispatcher(local_pdf_dirs=local_dirs, http_client=http)
        limit: int = getattr(args, "limit", 5) or 5

        ui(f"Searching: {query}")
        matched = match_papers(query=query, dispatcher=dispatcher, limit=limit)

        if not matched:
            ui("No papers found.")
            return

        ui(f"Found {len(matched)} paper(s):")
        for i, paper in enumerate(matched, 1):
            title_s = paper.get("title", "Untitled")[:60]
            doi_s = paper.get("doi", "")
            score = paper.get("_match_score", 0)
            source = paper.get("_match_source", "unknown")
            ui(f"  {i}. {title_s}…")
            ui(f"     doi={doi_s}  score={score:.0f}  source={source}")

        if getattr(args, "dry_run", False):
            ui("(dry-run — nothing saved)")
    finally:
        http.close()


def _parse_freeform(query_str: str):
    import re
    from linkora.sources.protocol import PaperQuery

    q = query_str.strip()
    if re.match(r"^10\.\d{4,}/", q):
        return PaperQuery(doi=q)
    if re.match(r"^\d{4}\.\d{4,5}$", q):
        return PaperQuery(title=q)
    return PaperQuery(title=q)


def cmd_enrich(args: argparse.Namespace, ctx: AppContext) -> None:
    """Enrich papers with table-of-contents and conclusions."""
    paper_id: str | None = getattr(args, "paper", None)
    do_toc: bool = getattr(args, "toc", False)
    do_conclusion: bool = getattr(args, "conclusion", False)
    limit: int | None = getattr(args, "limit", None)
    force: bool = getattr(args, "force", False)

    if not do_toc and not do_conclusion:
        do_toc = do_conclusion = True

    enricher = ctx.paper_enricher()
    store = ctx.paper_store()

    papers = [paper_id] if paper_id else [p.name for p in store.iter_papers()]
    if limit:
        papers = papers[:limit]

    if not papers:
        ui("No papers found.")
        return

    ui(
        f"Enriching {len(papers)} paper(s)  toc={do_toc}  conclusion={do_conclusion}  force={force}"
    )
    ok = 0
    for pid in papers:
        try:
            toc_ok = enricher.enrich_toc(pid, force=force) if do_toc else False
            conc_ok = (
                enricher.enrich_conclusion(pid, force=force) if do_conclusion else False
            )
            if toc_ok or conc_ok:
                ok += 1
        except Exception as exc:
            _log.error("Failed to enrich %s: %s", pid, exc)

    ui(f"Enriched {ok}/{len(papers)} papers.")


def cmd_index(args: argparse.Namespace, ctx: AppContext) -> None:
    """Build or rebuild a search index (fts or vector)."""
    index_type: IndexType = args.type
    rebuild: bool = args.rebuild

    if not ctx.workspace.papers_dir.exists():
        ui(f"Error: papers directory does not exist: {ctx.workspace.papers_dir}")
        return

    store = ctx.paper_store()
    action = "Rebuilding" if rebuild else "Building"

    if index_type == "fts":
        ui(f"{action} FTS index → {ctx.workspace.index_db}")
        with ctx.search_index() as idx:
            count = idx.rebuild(store) if rebuild else idx.update(store)
        ui(f"Done — indexed {count} papers.")

    elif index_type == "vector":
        try:
            ui(f"{action} vector index → {ctx.workspace.vectors_file}")
            with ctx.vector_index() as vidx:
                count = vidx.rebuild(store) if rebuild else vidx.update(store)
            ui(f"Done — embedded {count} papers.")
        except ImportError as exc:
            ui(f"Vector index unavailable: {exc}")
            ui("Install faiss-cpu to enable vector indexing.")


def cmd_audit(args: argparse.Namespace, ctx: AppContext) -> None:
    """Audit paper data quality."""
    store = ctx.paper_store()
    issues = store.audit()

    if not issues:
        ui("No issues found.")
        return

    severity: str | None = getattr(args, "severity", None)
    if severity:
        issues = [i for i in issues if i.severity == severity]

    _SEVERITY_PREFIX = {"error": "[ERROR]", "warning": "[WARN ]", "info": "[INFO ]"}
    ui(f"Found {len(issues)} issue(s):\n")
    for issue in issues:
        prefix = _SEVERITY_PREFIX.get(issue.severity, "[     ]")
        ui(f"{prefix} {issue.rule}: {issue.message}")
        ui(f"        paper: {issue.paper_id}\n")

    if getattr(args, "fix", False):
        ui(f"Auto-fix not yet implemented ({len(issues)} issues).")


# ============================================================================
#  System commands
# ============================================================================


def cmd_metrics(args: argparse.Namespace, ctx: AppContext) -> None:
    """Show LLM / system metrics."""
    from datetime import datetime, timezone
    from linkora.metrics import EventCategory, MetricsQuery, MetricsStore, TimeRange

    metrics_db = ctx.workspace.metrics_db(ctx.config.log.metrics_db)
    store = MetricsStore(metrics_db, session_id="cli")

    if getattr(args, "summary", False):
        s = store.summary()
        ui(f"LLM calls     : {s.call_count}")
        ui(f"Input tokens  : {s.total_tokens_in}")
        ui(f"Output tokens : {s.total_tokens_out}")
        ui(f"Total tokens  : {s.total_tokens_in + s.total_tokens_out}")
        ui(f"Total duration: {s.total_duration_s:.2f}s")
        return

    cat_str = getattr(args, "category", None) or "llm"
    try:
        category = EventCategory(cat_str)
    except ValueError:
        category = None

    time_range = None
    if getattr(args, "since", None):
        since_dt = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        time_range = TimeRange(since=since_dt)

    result = store.query_events(
        MetricsQuery(category=category, time_range=time_range, limit=args.last)
    )

    if not result.events:
        ui("No metrics found.")
        return

    ui(f"Recent {len(result.events)} event(s):")
    for ev in result.events:
        ui(
            f"  [{ev.get('timestamp', '')}] {ev.get('category', '')}:{ev.get('name', '')}  status={ev.get('status', '')}"
        )
        if ev.get("duration_s"):
            ui(f"    duration={ev['duration_s']:.2f}s")
        if ev.get("tokens_in") or ev.get("tokens_out"):
            ui(
                f"    tokens: {ev.get('tokens_in', 0)} in / {ev.get('tokens_out', 0)} out"
            )
        if ev.get("model"):
            ui(f"    model={ev['model']}")


def cmd_doctor(args: argparse.Namespace, ctx: AppContext) -> None:
    """Run full or quick health check."""
    from linkora.setup import run_check, run_doctor, format_result

    if getattr(args, "light", False):
        result = run_check(ctx)
        print(format_result(result, "Quick Check"))
    else:
        result = run_doctor(ctx)
        print(format_result(result, "Doctor"))


def cmd_init(args: argparse.Namespace, ctx: AppContext) -> None:
    """Interactive setup wizard."""
    from linkora.setup import run_init

    run_init(force=getattr(args, "force", False))


# ============================================================================
#  Command registration
# ============================================================================


def register_all(subparsers) -> None:
    """Register all CLI sub-commands."""

    # ── search ──────────────────────────────────────────────────────────
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
    _add_filter_args(p)

    # ── top-cited ────────────────────────────────────────────────────────
    p = subparsers.add_parser("top-cited", help="List top-cited papers")
    p.set_defaults(func=cmd_top_cited)
    p.add_argument("--top", type=int, help="Max results")
    _add_filter_args(p)

    # ── add ──────────────────────────────────────────────────────────────
    p = subparsers.add_parser("add", help="Add papers from various sources")
    p.set_defaults(func=cmd_add)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--doi", help="DOI (exact match)")
    g.add_argument("--issn", help="Journal ISSN")
    g.add_argument("--author", help="Author name")
    g.add_argument("--title", help="Paper title")
    p.add_argument("--year", help="Year or range (e.g. 2024, 2020-2024)")
    p.add_argument("query", nargs="?", help="Free-form query (fallback)")
    p.add_argument("--source", "-s", help="Preferred source (local / openalex / auto)")
    p.add_argument(
        "--limit", "-n", type=int, default=5, help="Max papers to fetch (default: 5)"
    )
    p.add_argument("--cache", "-c", action="store_true", help="Cache as symlinks")
    p.add_argument("--dry-run", action="store_true", help="Preview without saving")

    # ── enrich ───────────────────────────────────────────────────────────
    p = subparsers.add_parser("enrich", help="Enrich papers with TOC and conclusions")
    p.set_defaults(func=cmd_enrich)
    p.add_argument("--paper", help="Specific paper ID")
    p.add_argument("--toc", action="store_true", help="Extract table of contents")
    p.add_argument("--conclusion", action="store_true", help="Extract conclusion")
    p.add_argument("--limit", type=int, help="Max papers to process")
    p.add_argument("--force", action="store_true", help="Force re-extraction")

    # ── index ────────────────────────────────────────────────────────────
    p = subparsers.add_parser("index", help="Build search index")
    p.set_defaults(func=cmd_index)
    p.add_argument("--rebuild", action="store_true", help="Force full rebuild")
    p.add_argument(
        "--type",
        choices=["fts", "vector"],
        default="fts",
        help="Index type (default: fts)",
    )

    # ── metrics ──────────────────────────────────────────────────────────
    p = subparsers.add_parser("metrics", help="Show performance metrics")
    p.set_defaults(func=cmd_metrics)
    p.add_argument("--last", type=int, default=20, help="Number of recent events")
    p.add_argument("--category", default="llm", help="Event category")
    p.add_argument("--since", help="ISO datetime lower bound")
    p.add_argument("--summary", action="store_true", help="Show aggregate summary")

    # ── audit ────────────────────────────────────────────────────────────
    p = subparsers.add_parser("audit", help="Audit data quality")
    p.set_defaults(func=cmd_audit)
    p.add_argument("--severity", choices=["error", "warning", "info"])
    p.add_argument("--fix", action="store_true", help="Auto-fix where possible")

    # ── doctor ───────────────────────────────────────────────────────────
    p = subparsers.add_parser("doctor", help="Health check")
    p.set_defaults(func=cmd_doctor)
    p.add_argument("--light", action="store_true", help="Quick check (no network)")
    p.add_argument("--fix", action="store_true", help="Auto-fix issues")

    # ── config ───────────────────────────────────────────────────────────
    cfg_p = subparsers.add_parser(
        "config", help="Configuration and workspace management"
    )
    cfg_sub = cfg_p.add_subparsers(dest="config_action", required=True)

    # config show
    p = cfg_sub.add_parser("show", help="Show config or workspace info")
    p.set_defaults(func=cmd_config_show)
    p.add_argument("field", nargs="?", help="Dot-path field to show, e.g. llm.model")
    p.add_argument("--workspace", "-w", help="Workspace name (default: active)")
    p.add_argument("--all", "-a", action="store_true", help="List all workspaces")

    # config set
    p = cfg_sub.add_parser("set", help="Set a config value")
    p.set_defaults(func=cmd_config_set)
    p.add_argument("field", help="Dot-path field, e.g. llm.model or index.top_k")
    p.add_argument("value", help="New value")

    # config set-meta
    p = cfg_sub.add_parser("set-meta", help="Set workspace metadata")
    p.set_defaults(func=cmd_config_set_meta)
    p.add_argument("field", help="Metadata field: description")
    p.add_argument("value", help="New value")
    p.add_argument("--workspace", "-w", help="Workspace name (default: active)")

    # config mv
    p = cfg_sub.add_parser("mv", help="Rename or relocate a workspace")
    p.set_defaults(func=cmd_config_mv)
    p.add_argument("source", help="Current workspace name")
    p.add_argument("target", help="New name or absolute destination path")

    # config set-default
    p = cfg_sub.add_parser("set-default", help="Set the default workspace")
    p.set_defaults(func=cmd_config_set_default)
    p.add_argument("workspace", help="Workspace name to make default")

    # ── init ─────────────────────────────────────────────────────────────
    p = subparsers.add_parser("init", help="Interactive setup wizard")
    p.set_defaults(func=cmd_init)
    p.add_argument("--force", action="store_true", help="Overwrite existing config")


def _add_filter_args(p) -> None:
    """Add common paper-filter arguments to a subcommand parser."""
    p.add_argument("--year", default=None, help="Year filter: 2023 / 2020-2024 / 2020-")
    p.add_argument("--journal", default=None, help="Journal name filter (LIKE)")
    p.add_argument(
        "--type",
        dest="paper_type",
        default=None,
        help="Paper type filter: review / journal-article etc. (LIKE)",
    )


__all__ = ["register_all"]
