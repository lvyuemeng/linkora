"""
commands.py — CLI command handlers.

All handlers receive (args: argparse.Namespace, ctx: AppContext).
They access shared state via ctx.config, ctx.store, ctx.workspace_name,
and helper methods for log paths. They never access private
internals of AppConfig or WorkspaceStore.

Config file read/write
──────────────────────
``cmd_config_set`` writes to the global config YAML. There is no
workspace-local config. All settings live in the single global config file.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from linkora.cli.args import (
    AddArgs,
    SearchArgs,
    EnrichArgs,
    IndexArgs,
    ConfigShowArgs,
    ConfigSetArgs,
    FilesDedupArgs,
    FilesInboxArgs,
    FilesRescanArgs,
    FilesTidyArgs,
    FilesWatchAddArgs,
)
from linkora.log import ui
from linkora.cli.setup import set_config_value
from linkora.sources import (
    SourceIngestRequest,
    run_source_ingest,
)
from linkora.files import (
    FilesInboxRequest,
    FilesTidyRequest,
    FilesDedupRequest,
    FilesRescanRequest,
    FilesWatchAddRequest,
    run_files_inbox,
    run_files_tidy,
    run_files_dedup,
    run_files_rescan,
    run_files_watch_add,
    run_files_watch_list,
    run_files_watch_start,
)

if TYPE_CHECKING:
    from linkora.config import AppConfig
    from linkora.db import Database
    from linkora.workspace import WorkspaceStore


@dataclass(frozen=True)
class AppContext:
    """
    Per-invocation CLI context.

    Parameters
    ----------
    config:
        Loaded application settings (frozen Pydantic model).
    config_dir:
        Directory that contained the active config.yml.
    store:
        WorkspaceStore bound to the data root.
    workspace_name:
        Name of the active workspace for this invocation.
    """

    config: "AppConfig"
    config_dir: Path
    store: "WorkspaceStore"
    workspace_name: str
    data_root: Path
    db: "Database"

    def log_file(self, name: str) -> Path:
        return self.data_root / name

    def resolve_workspace_id(self, override: str | None = None) -> str:
        return override or self.workspace_name or "default"

    def close(self) -> None:
        """Close any open resources."""
        self.db.close()


# ============================================================================
#  Search commands
# ============================================================================


def cmd_search(args: argparse.Namespace, ctx: AppContext) -> None:
    """Search documents using full-text or vector search."""
    from linkora.schema.registry import (
        DEFAULT_SCHEMA_REGISTRY,
        SearchFilter,
        filter_schema_documents,
        parse_schema_documents,
    )

    cmd_args = SearchArgs.from_namespace(args)
    query = " ".join(cmd_args.query) if cmd_args.query else ""
    if not query:
        ui("Error: provide a search query")
        return

    mode = cmd_args.mode
    top_k = cmd_args.top

    store = ctx.store.document_store()
    search_index = ctx.store.search_index()
    vector_index = ctx.store.vector_index()
    ws_id = ctx.resolve_workspace_id()

    filter_fields: dict[str, str] = {}
    if args.year:
        filter_fields["year"] = args.year
    if args.journal:
        filter_fields["journal"] = args.journal
    filters = SearchFilter(
        doc_type=args.paper_type or None,
        fields=filter_fields,
    )

    run_fulltext = mode in (None, "fulltext")
    run_vector = mode in (None, "vector")

    if run_fulltext:
        doc_type = filters.doc_type
        candidates = list(
            search_index.search(
                query,
                workspace_id=ws_id,
                doc_type=doc_type,
                limit=top_k,
            )
        )
        docs: list = []
        for r in candidates:
            doc = store.get_by_id(r.doc_id)
            if not doc:
                continue
            docs.append(doc)
        parsed_docs = parse_schema_documents(docs, registry=DEFAULT_SCHEMA_REGISTRY)
        results = filter_schema_documents(parsed_docs, filters)
        ui(f"Found {len(results)} document(s) (fulltext: '{query}')")
        for r in results:
            ui(f"  - {r.title[:60]}")

    if run_vector:
        try:
            doc_type = filters.doc_type
            candidates = list(
                vector_index.search(
                    query,
                    workspace_id=ws_id,
                    doc_type=doc_type,
                    limit=top_k,
                )
            )
            docs: list = []
            score_map: dict[str, float] = {}
            for r in candidates:
                doc = store.get_by_id(r.doc_id)
                if not doc:
                    continue
                docs.append(doc)
                score_map[doc.id] = float(r.score)
            parsed_docs = parse_schema_documents(docs, registry=DEFAULT_SCHEMA_REGISTRY)
            filtered = filter_schema_documents(parsed_docs, filters)
            ui(f"Found {len(filtered)} document(s) (vector: '{query}')")
            for doc in filtered:
                ui(f"  - {doc.title[:60]} (score: {score_map.get(doc.id, 0.0):.2f})")
        except ImportError as e:
            ui(f"Vector search unavailable: {e}")


def cmd_add(args: argparse.Namespace, ctx: AppContext) -> None:
    """Add documents from various sources."""

    cmd_args = AddArgs.from_namespace(args)
    if not cmd_args.targets:
        ui("Error: provide at least one target")
        return

    output_dir = Path(cmd_args.output or (Path.home() / "Downloads"))
    request = SourceIngestRequest(
        targets=cmd_args.targets,
        source=cmd_args.source,
        output_dir=output_dir,
        workspace_id=ctx.resolve_workspace_id(cmd_args.workspace),
        doc_type_hint=cmd_args.doc_type,
        dry_run=cmd_args.dry_run,
        store=ctx.store.document_store(),
    )
    run_source_ingest(request)


# ============================================================================
#  Add / Enrich / Index
# ============================================================================


def cmd_enrich(args: argparse.Namespace, ctx: AppContext) -> None:
    """Re-run LLM enrichment on existing documents."""
    from linkora.pipeline.enrich import EnrichRequest, enrich_store

    cmd_args = EnrichArgs.from_namespace(args)
    store = ctx.store.document_store()
    request = EnrichRequest(
        workspace_id=ctx.resolve_workspace_id(),
        paper_id=cmd_args.paper,
        limit=cmd_args.limit,
        force=cmd_args.force,
        summary=cmd_args.summary,
        outline=cmd_args.outline,
    )
    asyncio.run(enrich_store(store, request))


def cmd_files_inbox(args: argparse.Namespace, ctx: AppContext) -> None:
    cmd_args = FilesInboxArgs.from_namespace(args)
    request = FilesInboxRequest(
        path=cmd_args.path,
        workspace_id=ctx.resolve_workspace_id(cmd_args.workspace),
        store=ctx.store.document_store(),
    )
    run_files_inbox(request)


def cmd_files_tidy(args: argparse.Namespace, ctx: AppContext) -> None:
    cmd_args = FilesTidyArgs.from_namespace(args)
    store = ctx.store.document_store()
    request = FilesTidyRequest(
        path=cmd_args.path,
        doc_type_hint=cmd_args.type or None,
        dry_run=cmd_args.dry_run or ctx.config.tidy.dry_run,
        confirm=ctx.config.tidy.confirm,
        templates=ctx.config.tidy.templates,
    )
    run_files_tidy(store, request)


def cmd_files_dedup(args: argparse.Namespace, ctx: AppContext) -> None:
    cmd_args = FilesDedupArgs.from_namespace(args)
    request = FilesDedupRequest(
        path=cmd_args.path,
        delete_older=cmd_args.delete_older,
    )
    run_files_dedup(request)


def cmd_files_rescan(args: argparse.Namespace, ctx: AppContext) -> None:
    cmd_args = FilesRescanArgs.from_namespace(args)
    store = ctx.store.document_store()
    request = FilesRescanRequest(
        workspace_id=ctx.resolve_workspace_id(),
        scan_path=cmd_args.path,
    )
    run_files_rescan(store, request)


def cmd_files_watch_add(args: argparse.Namespace, ctx: AppContext) -> None:
    cmd_args = FilesWatchAddArgs.from_namespace(args)
    request = FilesWatchAddRequest(
        path=cmd_args.path.resolve(),
        workspace_id=ctx.resolve_workspace_id(cmd_args.workspace),
        doc_type_hint=cmd_args.type or None,
    )
    run_files_watch_add(ctx.store, request)


def cmd_files_watch_list(args: argparse.Namespace, ctx: AppContext) -> None:
    run_files_watch_list(ctx.store)


def cmd_files_watch_start(args: argparse.Namespace, ctx: AppContext) -> None:
    daemon = args.daemon
    if daemon:
        ui("Daemon mode is not supported yet; running in foreground.")
    run_files_watch_start(ctx.store)


def cmd_index(args: argparse.Namespace, ctx: AppContext) -> None:
    """Build or rebuild search indexes."""
    from linkora.topics import TopicModelStore, TopicsUnavailable, build_topics

    cmd_args = IndexArgs.from_namespace(args)
    run_fts = cmd_args.fts
    run_vector = cmd_args.vector
    run_topics = cmd_args.topics
    if cmd_args.all:
        run_fts = True
        run_vector = True
        run_topics = True
    if not (run_fts or run_vector or run_topics):
        run_fts = True
        run_vector = True

    ui(f"Data root: {ctx.data_root}")

    if run_fts:
        ui("Building FTS index...")
        idx = ctx.store.search_index()
        idx.rebuild()
        ui("FTS index built.")

    if run_vector:
        ui("Building vector index...")
        try:
            vidx = ctx.store.vector_index()
            vidx.rebuild()
            ui("Vector index built.")
        except ImportError as e:
            ui(f"Vector index unavailable: {e}")

    if run_topics:
        ui("Building topics...")
        try:
            store = ctx.store.document_store()
            vidx = ctx.store.vector_index()
            model_store = TopicModelStore.from_config(ctx.config.topics)
            build_topics(
                store=store,
                vector_index=vidx,
                workspace_id=ctx.resolve_workspace_id(),
                cfg=ctx.config.topics,
                model_store=model_store,
            )
            ui("Topics built.")
        except TopicsUnavailable as e:
            ui(str(e))
        except ImportError as e:
            ui(f"Topics unavailable: {e}")


def cmd_doctor(args: argparse.Namespace, ctx: AppContext) -> None:
    """Run config/environment health check."""
    from linkora.cli.setup import run_doctor, format_result

    result = run_doctor(ctx)
    print(format_result(result, "Doctor"))


def cmd_config_show(args: argparse.Namespace, ctx: AppContext) -> None:
    """Show configuration values."""
    cmd_args = ConfigShowArgs.from_namespace(args)
    ui(ctx.config.to_yaml(cmd_args.field))


def cmd_config_set(args: argparse.Namespace, ctx: AppContext) -> None:
    """Set a configuration value in the global config file."""
    cmd_args = ConfigSetArgs.from_namespace(args)
    msg, _, note = set_config_value(cmd_args.field, cmd_args.value)
    if note:
        ui(note)
    ui(msg)


def cmd_topics_build(args: argparse.Namespace, ctx: AppContext) -> None:
    from linkora.topics import TopicModelStore, TopicsUnavailable, build_topics

    limit = args.limit
    workspace_id = ctx.resolve_workspace_id(args.workspace)
    try:
        store = ctx.store.document_store()
        vidx = ctx.store.vector_index()
        model_store = TopicModelStore.from_config(ctx.config.topics)
        build_topics(
            store=store,
            vector_index=vidx,
            workspace_id=workspace_id,
            cfg=ctx.config.topics,
            limit=limit,
            model_store=model_store,
        )
        ui("Topics built.")
    except TopicsUnavailable as e:
        ui(str(e))


def cmd_topics_list(args: argparse.Namespace, ctx: AppContext) -> None:
    workspace_id = ctx.resolve_workspace_id(args.workspace)
    topic_store = ctx.store.topic_store()
    topics = topic_store.list_topics(workspace_id)
    if not topics:
        ui("No topics found.")
        return
    ui(f"Topics in '{workspace_id}':")
    for topic in topics:
        ui(f"  {topic.topic_id:>4}  {topic.size:>4}  {topic.label}")


def cmd_topics_show(args: argparse.Namespace, ctx: AppContext) -> None:
    workspace_id = ctx.resolve_workspace_id(args.workspace)
    topic_store = ctx.store.topic_store()
    try:
        topic_id = int(args.topic_id)
    except Exception:
        ui("Invalid topic_id")
        return
    topic = topic_store.get_topic(workspace_id, topic_id)
    if not topic:
        ui("Topic not found.")
        return
    ui(f"Topic {topic.topic_id} ({topic.size} docs)")
    ui(f"Label: {topic.label}")
    if topic.top_terms:
        ui("Top terms:")
        ui("  " + ", ".join(topic.top_terms[:20]))


def cmd_topics_assign(args: argparse.Namespace, ctx: AppContext) -> None:
    from linkora.topics import TopicModelStore, TopicsUnavailable, assign_topics

    limit = args.limit
    workspace_id = ctx.resolve_workspace_id(args.workspace)
    try:
        store = ctx.store.document_store()
        vidx = ctx.store.vector_index()
        model_store = TopicModelStore.from_config(ctx.config.topics)
        assign_topics(
            store=store,
            vector_index=vidx,
            workspace_id=workspace_id,
            cfg=ctx.config.topics,
            limit=limit,
            model_store=model_store,
        )
        ui("Topics assigned.")
    except TopicsUnavailable as e:
        ui(str(e))


def cmd_topics_prune(args: argparse.Namespace, ctx: AppContext) -> None:
    from linkora.topics import prune_topics

    min_size = args.min_size or ctx.config.topics.min_topic_size
    workspace_id = ctx.resolve_workspace_id(args.workspace)
    store = ctx.store.document_store()
    removed_topics, removed_assignments = prune_topics(store, workspace_id, min_size)
    ui(f"Pruned {removed_topics} topic(s) and {removed_assignments} assignment(s).")


def cmd_topics_export(args: argparse.Namespace, ctx: AppContext) -> None:
    import csv
    import json

    workspace_id = ctx.resolve_workspace_id(args.workspace)
    fmt = args.format
    out_path = args.path or f"topics_{workspace_id}.{fmt}"
    path = Path(out_path)

    topic_store = ctx.store.topic_store()
    topics = topic_store.list_topics(workspace_id)
    assignments = topic_store.list_assignments(workspace_id)
    if fmt == "json":
        payload = {
            "workspace_id": workspace_id,
            "topics": [
                {
                    "topic_id": t.topic_id,
                    "label": t.label,
                    "top_terms": t.top_terms,
                    "size": t.size,
                    "created_at": t.created_at,
                }
                for t in topics
            ],
            "assignments": [
                {
                    "doc_id": a.doc_id,
                    "topic_id": a.topic_id,
                    "score": a.score,
                }
                for a in assignments
            ],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        topic_map = {t.topic_id: t.label for t in topics}
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["doc_id", "topic_id", "label", "score"])
            for a in assignments:
                writer.writerow(
                    [a.doc_id, a.topic_id, topic_map.get(a.topic_id, ""), a.score]
                )
    ui(f"Exported topics to {path}")


# ============================================================================
#  Command registration
# ============================================================================


def register_all(subparsers) -> None:
    """Register all CLI sub-commands."""

    # ── search ──────────────────────────────────────────────────────────
    p = subparsers.add_parser(
        "search",
        help="Search documents (FTS + vector)",
        description=(
            "Search documents in the active workspace.\n"
            "Default behavior runs both full-text and vector search paths.\n"
            "Use --mode to restrict to one path."
        ),
    )
    p.set_defaults(func=cmd_search)
    p.add_argument("query", nargs="*", help="Query text (required)")
    p.add_argument("--top", type=int, help="Max results per mode (default: 20)")
    p.add_argument(
        "--mode",
        choices=["fulltext", "vector"],
        help="Run only one mode (default: run both)",
    )
    _add_filter_args(p)

    # ── add ──────────────────────────────────────────────────────────────
    p = subparsers.add_parser(
        "add",
        help="Ingest targets (path/dir/DOI/arXiv/web)",
        description=(
            "Ingest one or more targets.\n"
            "Targets can be local paths, DOI IDs, arXiv IDs, or URLs.\n"
            "Remote targets may download artifacts to --output before ingest."
        ),
    )
    p.set_defaults(func=cmd_add)
    p.add_argument(
        "targets",
        nargs="+",
        help="Targets: paths, directories, DOI/arXiv IDs, or URLs",
    )
    p.add_argument(
        "--source",
        "-s",
        help="Force source scheme: file/local/doi/arxiv/web",
    )
    p.add_argument(
        "--output",
        "-o",
        help="Download output directory for remote sources (default: ~/Downloads)",
    )
    p.add_argument("--workspace", "-w", help="Target workspace")
    p.add_argument("--type", help="Document type hint, e.g. paper/invoice/manual")
    p.add_argument("--dry-run", action="store_true", help="Preview without saving")

    # ── enrich ───────────────────────────────────────────────────────────
    p = subparsers.add_parser(
        "enrich",
        help="Run enrichment for stored docs",
        description=(
            "Re-run schema-aware metadata enrichment for documents already in DB.\n"
            "Without --summary/--outline, both are refreshed by default."
        ),
    )
    p.set_defaults(func=cmd_enrich)
    p.add_argument("--paper", help="Specific document ID")
    p.add_argument("--summary", action="store_true", help="Update summary")
    p.add_argument("--outline", action="store_true", help="Update outline")
    p.add_argument("--limit", type=int, help="Max documents to process")
    p.add_argument("--force", action="store_true", help="Force re-extraction")

    # ── index ────────────────────────────────────────────────────────────
    p = subparsers.add_parser(
        "index",
        help="Build FTS/vector/topics indexes",
        description=(
            "Build search and topic indexes.\n"
            "Default behavior builds FTS + vector when no mode flags are provided."
        ),
    )
    p.set_defaults(func=cmd_index)
    p.add_argument(
        "--rebuild",
        action="store_true",
        help="Reserved rebuild flag (currently index build always refreshes)",
    )
    p.add_argument("--fts", action="store_true", help="Build FTS index")
    p.add_argument("--vector", action="store_true", help="Build vector index")
    p.add_argument("--topics", action="store_true", help="Build topics model")
    p.add_argument("--all", action="store_true", help="Build all indexes")

    # ── doctor ───────────────────────────────────────────────────────────
    p = subparsers.add_parser(
        "doctor",
        help="Run environment health checks",
        description="Report config resolution and environment/dependency status.",
    )
    p.set_defaults(func=cmd_doctor)

    # ── config ───────────────────────────────────────────────────────────
    cfg_p = subparsers.add_parser(
        "config",
        help="Read/write global config",
        description=(
            "Manage global linkora config.\nNo workspace-local config is supported."
        ),
    )
    cfg_sub = cfg_p.add_subparsers(dest="config_action", required=True)

    # config show
    p = cfg_sub.add_parser(
        "show",
        help="Show current config",
        description="Show full config or one dot-path field.",
    )
    p.set_defaults(func=cmd_config_show)
    p.add_argument("field", nargs="?", help="Dot-path field to show, e.g. llm.model")

    # config set
    p = cfg_sub.add_parser(
        "set",
        help="Set config value",
        description=(
            "Set one config key using dot-path syntax.\n"
            "Value is parsed as YAML scalar/list/map."
        ),
    )
    p.set_defaults(func=cmd_config_set)
    p.add_argument("field", help="Dot-path field, e.g. llm.model or index.top_k")
    p.add_argument("value", help="New value")

    # ── files ────────────────────────────────────────────────────────────
    files_p = subparsers.add_parser(
        "files",
        help="File system operations",
        description=(
            "Operations on user directories: tidy, dedup, rescan, inbox, watch.\n"
            "These commands are independent from source connectors."
        ),
    )
    files_sub = files_p.add_subparsers(dest="files_action", required=True)

    p = files_sub.add_parser(
        "tidy",
        help="Rename files from metadata templates",
        description=(
            "Rename files using schema fields and tidy.templates.\n"
            "Metadata is loaded from DB when available; otherwise extracted on the fly."
        ),
    )
    p.set_defaults(func=cmd_files_tidy)
    p.add_argument("path", help="Directory to tidy")
    p.add_argument("--type", help="Document type hint (auto-detect if omitted)")
    p.add_argument("--dry-run", action="store_true", help="Preview changes only")

    p = files_sub.add_parser(
        "dedup",
        help="Find duplicate files",
        description="Detect duplicates by content hash; optionally delete older copies.",
    )
    p.set_defaults(func=cmd_files_dedup)
    p.add_argument("path", help="Directory to scan for duplicates")
    p.add_argument(
        "--delete-older", action="store_true", help="Keep newest, delete others"
    )

    p = files_sub.add_parser(
        "rescan",
        help="Repair moved file paths",
        description="Rescan filesystem and update stored source_path references.",
    )
    p.set_defaults(func=cmd_files_rescan)
    p.add_argument("path", nargs="?", help="Directory to rescan (all if omitted)")

    p = files_sub.add_parser(
        "inbox",
        help="Ingest all supported files in directory",
        description="Scan a directory and ingest each supported file into workspace.",
    )
    p.set_defaults(func=cmd_files_inbox)
    p.add_argument("path", help="Directory to ingest")
    p.add_argument("--workspace", "-w", help="Target workspace")

    watch_p = files_sub.add_parser(
        "watch",
        help="Manage auto-import watchers",
        description="Add/list/start file watchers for automatic ingestion.",
    )
    watch_sub = watch_p.add_subparsers(dest="watch_action", required=True)

    p = watch_sub.add_parser(
        "add",
        help="Register watch directory",
        description="Add or update one directory watch rule.",
    )
    p.set_defaults(func=cmd_files_watch_add)
    p.add_argument("path", help="Directory to watch")
    p.add_argument("--workspace", "-w", help="Target workspace")
    p.add_argument("--type", help="Document type hint")

    p = watch_sub.add_parser(
        "list",
        help="List watch rules",
        description="List all configured watched directories.",
    )
    p.set_defaults(func=cmd_files_watch_list)

    p = watch_sub.add_parser(
        "start",
        help="Start watcher loop",
        description="Start foreground watcher loop (daemon flag is reserved).",
    )
    p.set_defaults(func=cmd_files_watch_start)
    p.add_argument("--daemon", action="store_true", help="Run in background")

    # ── topics ───────────────────────────────────────────────────────────
    topics_p = subparsers.add_parser(
        "topics",
        help="Topic modeling operations",
        description=("Build, inspect, assign, prune, and export workspace topics."),
    )
    topics_sub = topics_p.add_subparsers(dest="topics_action", required=True)

    p = topics_sub.add_parser(
        "build",
        help="Build workspace topics",
        description="Fit/update topic model for one workspace.",
    )
    p.set_defaults(func=cmd_topics_build)
    p.add_argument("--workspace", "-w", help="Target workspace")
    p.add_argument("--limit", type=int, help="Limit number of documents")

    p = topics_sub.add_parser(
        "list",
        help="List topics",
        description="List topic summaries in one workspace.",
    )
    p.set_defaults(func=cmd_topics_list)
    p.add_argument("--workspace", "-w", help="Target workspace")

    p = topics_sub.add_parser(
        "show",
        help="Show topic detail",
        description="Show label and top terms for one topic id.",
    )
    p.set_defaults(func=cmd_topics_show)
    p.add_argument("topic_id", help="Topic ID")

    p = topics_sub.add_parser(
        "assign",
        help="Assign docs to topics",
        description="Assign workspace documents to existing topic clusters.",
    )
    p.set_defaults(func=cmd_topics_assign)
    p.add_argument("--workspace", "-w", help="Target workspace")
    p.add_argument("--limit", type=int, help="Limit number of documents")

    p = topics_sub.add_parser(
        "prune",
        help="Prune small topics",
        description="Remove topics smaller than threshold and delete assignments.",
    )
    p.set_defaults(func=cmd_topics_prune)
    p.add_argument("--workspace", "-w", help="Target workspace")
    p.add_argument("--min-size", type=int, help="Minimum topic size")

    p = topics_sub.add_parser(
        "export",
        help="Export topics",
        description="Export topics and assignments as JSON or CSV.",
    )
    p.set_defaults(func=cmd_topics_export)
    p.add_argument("--format", choices=["json", "csv"], default="json")
    p.add_argument("--path", help="Output path")
    p.add_argument("--workspace", "-w", help="Target workspace")


def _add_filter_args(p) -> None:
    """Add common paper-filter arguments to a subcommand parser."""
    p.add_argument(
        "--year",
        default=None,
        help="Schema year filter value (string match), e.g. 2023",
    )
    p.add_argument(
        "--journal",
        default=None,
        help="Schema journal filter value (substring match)",
    )
    p.add_argument(
        "--type",
        dest="paper_type",
        default=None,
        help="Document type filter, e.g. paper/invoice/manual",
    )


__all__ = ["AppContext", "register_all"]
