"""files.py - File system operations."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from linkora import content_hash
from linkora.log import get_logger, ui
from linkora.pipeline.enrich import enrich
from linkora.pipeline.extract import extract_text
from linkora.schema.registry import (
    FilenameRenderRequest,
    DEFAULT_SCHEMA_REGISTRY,
    normalize_filename,
    resolve_doc_type,
    resolve_filename,
    resolve_schema,
)
from linkora.store import DocumentStore


SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".html", ".docx"}
_LOG = get_logger(__name__)


@dataclass(frozen=True)
class IngestTask:
    path: Path
    workspace_id: str
    doc_type_hint: str | None = None
    metadata_hint: dict | None = None


@dataclass(frozen=True)
class IngestOutcome:
    task: IngestTask
    doc_id: str | None
    success: bool
    error: str | None = None


@dataclass(frozen=True)
class FileScanSpec:
    root: Path
    suffixes: set[str] | None = None
    recursive: bool = True


@dataclass(frozen=True)
class FileBatch:
    root: Path
    files: list[Path]

    @classmethod
    def from_scan(
        cls, spec: FileScanSpec, allow_empty: bool = False
    ) -> "FileBatch | None":
        if not spec.root.exists() or not spec.root.is_dir():
            ui(f"Error: {spec.root} is not a directory", logger=_LOG)
            return None
        files = list(
            iter_supported_files(
                spec.root,
                suffixes=spec.suffixes,
                recursive=spec.recursive,
            )
        )
        if not files and not allow_empty:
            ui(f"No supported files found in {spec.root}", logger=_LOG)
            return None
        return cls(root=spec.root, files=files)


@dataclass(frozen=True)
class WatchRule:
    path: Path
    workspace_id: str
    doc_type_hint: str | None


@dataclass(frozen=True)
class FilesInboxRequest:
    path: Path
    workspace_id: str


@dataclass(frozen=True)
class FilesTidyRequest:
    path: Path
    doc_type_hint: str | None
    dry_run: bool
    confirm: bool
    templates: dict[str, str] | None


@dataclass(frozen=True)
class FilesDedupRequest:
    path: Path
    delete_older: bool


@dataclass(frozen=True)
class FilesRescanRequest:
    workspace_id: str
    scan_path: Path | None


@dataclass(frozen=True)
class FilesWatchAddRequest:
    path: Path
    workspace_id: str
    doc_type_hint: str | None


@dataclass(frozen=True)
class RescanStats:
    fixed: int = 0
    missing: int = 0


class WatchStoreLike(Protocol):
    def add_watched_dir(
        self,
        path: str,
        workspace_id: str,
        doc_type_hint: str | None = None,
    ) -> None: ...

    def list_watched_dirs(self) -> list[dict[str, Any]]: ...

    def document_store(self) -> DocumentStore: ...


def iter_supported_files(
    root_path: Path,
    suffixes: set[str] | None = None,
    recursive: bool = True,
) -> Iterable[Path]:
    """Iterate supported files under a directory."""
    use_suffixes = suffixes or SUPPORTED_SUFFIXES
    iterator = root_path.rglob("*") if recursive else root_path.glob("*")
    for path in iterator:
        if path.is_file() and path.suffix.lower() in use_suffixes:
            yield path


def run_files_inbox(request: FilesInboxRequest) -> None:
    """Ingest all supported files in a directory."""
    batch = FileBatch.from_scan(FileScanSpec(request.path))
    if not batch:
        return

    ui(f"Ingesting {len(batch.files)} files from {batch.root}...", logger=_LOG)
    tasks = [
        IngestTask(path=file_path, workspace_id=request.workspace_id)
        for file_path in batch.files
    ]
    outcomes = _process_ingest_tasks(tasks)
    ok = sum(1 for outcome in outcomes if outcome.success)
    ui(f"Ingested {ok}/{len(tasks)} files.", logger=_LOG)


def run_files_tidy(store: DocumentStore, request: FilesTidyRequest) -> None:
    """Normalize filenames based on metadata."""
    batch = FileBatch.from_scan(FileScanSpec(request.path))
    if not batch:
        return
    ui(f"Processing {len(batch.files)} files for tidying...", logger=_LOG)
    asyncio.run(_run_files_tidy_async(store, request, batch.files))
    ui("Tidy completed.", logger=_LOG)


async def _run_files_tidy_async(
    store: DocumentStore,
    request: FilesTidyRequest,
    files: list[Path],
) -> None:
    templates = request.templates or {}
    for file_path in files:
        await _tidy_one_file_async(
            store=store,
            file_path=file_path,
            doc_type_hint=request.doc_type_hint,
            dry_run=request.dry_run,
            confirm=request.confirm,
            templates=templates,
        )


async def _tidy_one_file_async(
    store: DocumentStore,
    file_path: Path,
    doc_type_hint: str | None,
    dry_run: bool,
    confirm: bool,
    templates: dict[str, str],
) -> None:
    fields, schema = await _resolve_file_fields_async(store, file_path, doc_type_hint)
    template = templates.get(schema.doc_type)
    new_name = resolve_filename(
        FilenameRenderRequest(
            schema=schema,
            fields=fields,
            template=template,
            use_schema_fallback=True,
        )
    ).value
    if not new_name:
        return

    new_name = normalize_filename(new_name, preserve_spaces=True)
    if not new_name:
        return
    new_name = new_name + file_path.suffix.lower()
    new_path = file_path.with_name(new_name)

    if dry_run:
        ui(f"[DRY RUN] {file_path.name} -> {new_path.name}", logger=_LOG)
        return

    if confirm:
        resp = input(f"Rename {file_path.name} -> {new_path.name}? [y/N] ")
        if resp.strip().lower() != "y":
            return

    file_path.rename(new_path)


async def _resolve_file_fields_async(
    store: DocumentStore,
    file_path: Path,
    doc_type_hint: str | None,
):
    doc = store.get_by_id(content_hash(file_path))
    if doc:
        schema = resolve_schema(doc.doc_type, registry=DEFAULT_SCHEMA_REGISTRY)
        return schema.fields_model.model_validate_json(doc.metadata_json), schema

    doc_type = resolve_doc_type(registry=DEFAULT_SCHEMA_REGISTRY, hint=doc_type_hint)
    schema = resolve_schema(doc_type, registry=DEFAULT_SCHEMA_REGISTRY)
    raw = await extract_text(file_path)
    result = await enrich(raw_content=raw.content, schema=schema, seed=None)
    return result.fields, schema


def run_files_dedup(request: FilesDedupRequest) -> None:
    """Find and optionally remove duplicate files."""
    batch = FileBatch.from_scan(FileScanSpec(request.path))
    if not batch:
        return

    ui(f"Scanning {len(batch.files)} files for duplicates...", logger=_LOG)
    hash_groups: dict[str, list[Path]] = defaultdict(list)
    for file_path in batch.files:
        try:
            hash_groups[content_hash(file_path)].append(file_path)
        except Exception as exc:
            ui(f"Warning: Could not hash {file_path}: {exc}", logger=_LOG)

    duplicates = {h: paths for h, paths in hash_groups.items() if len(paths) > 1}
    if not duplicates:
        ui("No duplicates found.", logger=_LOG)
        return

    ui(f"Found {len(duplicates)} duplicate groups:", logger=_LOG)
    total_files = 0
    for hash_val, paths in duplicates.items():
        total_files += len(paths)
        ui(f"\nHash: {hash_val[:16]}...", logger=_LOG)
        sorted_paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
        for idx, candidate in enumerate(sorted_paths):
            tag = "[NEWEST] " if idx == 0 else "         "
            ui(f"  {tag} {candidate}", logger=_LOG)
        if request.delete_older and len(sorted_paths) > 1:
            _delete_older_duplicates(sorted_paths[1:])

    ui(
        f"\nSummary: {total_files} files in {len(duplicates)} duplicate groups",
        logger=_LOG,
    )
    if request.delete_older:
        ui("Older duplicates have been deleted.", logger=_LOG)


def run_files_rescan(store: DocumentStore, request: FilesRescanRequest) -> None:
    """Update source paths for moved files."""
    docs = store.list_by_workspace(request.workspace_id)
    location_store = store.file_location_store()
    hash_index = _build_hash_index(request.scan_path)
    if request.scan_path and hash_index is None:
        return
    hash_index = hash_index or {}

    stats = RescanStats()
    for doc in docs:
        old_path = Path(doc.source_path)
        if old_path.exists():
            continue
        if request.scan_path and doc.content_hash and doc.content_hash in hash_index:
            candidate = hash_index[doc.content_hash]
            store.update_source_path(doc.id, str(candidate))
            location_store.upsert(
                content_hash=doc.content_hash, path=str(candidate), status="ok"
            )
            ui(f"Updated: {doc.id} -> {candidate}", logger=_LOG)
            stats = RescanStats(fixed=stats.fixed + 1, missing=stats.missing)
            continue

        store.update_status(doc.id, "missing")
        if doc.content_hash:
            location_store.mark_missing(doc.content_hash, doc.source_path)
        stats = RescanStats(fixed=stats.fixed, missing=stats.missing + 1)

    ui(
        f"Rescan complete: {stats.fixed} paths updated, {stats.missing} marked as missing",
        logger=_LOG,
    )


def run_files_watch_add(store: WatchStoreLike, request: FilesWatchAddRequest) -> None:
    if not request.path.exists() or not request.path.is_dir():
        ui(f"Error: {request.path} is not a directory", logger=_LOG)
        return
    store.add_watched_dir(
        str(request.path), request.workspace_id, request.doc_type_hint
    )
    suffix = f" (type: {request.doc_type_hint})" if request.doc_type_hint else ""
    ui(
        f"Added watch: {request.path} -> workspace '{request.workspace_id}'{suffix}",
        logger=_LOG,
    )


def run_files_watch_list(store: WatchStoreLike) -> None:
    watched = store.list_watched_dirs()
    if not watched:
        ui("No watched directories.", logger=_LOG)
        return

    ui("Watched directories:", logger=_LOG)
    for row in watched:
        suffix = f" ({row['doc_type_hint']})" if row["doc_type_hint"] else ""
        ui(f"  {row['path']} -> {row['workspace_id']}{suffix}", logger=_LOG)


def run_files_watch_start(store: WatchStoreLike) -> None:
    """Poll watched directories and ingest newly stable files."""
    from time import sleep

    watch_rules = _load_watch_rules(store)
    if not watch_rules:
        return

    ui("Watching for new files (Ctrl+C to stop)...", logger=_LOG)
    known: dict[Path, tuple[float, int]] = {}
    processed: set[Path] = set()
    doc_store = store.document_store()

    try:
        while True:
            pending: list[IngestTask] = []
            for rule in watch_rules:
                _collect_pending_tasks(rule, known, processed, doc_store, pending)

            if pending:
                outcomes = _process_ingest_tasks(pending)
                for outcome in outcomes:
                    if not outcome.success:
                        continue
                    processed.add(outcome.task.path)
                    if outcome.doc_id and not outcome.task.path.exists():
                        doc_store.update_status(outcome.doc_id, "missing")

            sleep(2.0)
    except KeyboardInterrupt:
        ui("File watcher stopped.", logger=_LOG)


def _build_hash_index(scan_path: Path | None) -> dict[str, Path] | None:
    if not scan_path:
        return {}
    batch = FileBatch.from_scan(FileScanSpec(scan_path), allow_empty=True)
    if not batch:
        return None
    hash_index: dict[str, Path] = {}
    for candidate in batch.files:
        try:
            hash_index[content_hash(candidate)] = candidate
        except Exception:
            continue
    return hash_index


def _collect_pending_tasks(
    rule: WatchRule,
    known: dict[Path, tuple[float, int]],
    processed: set[Path],
    doc_store: DocumentStore,
    pending: list[IngestTask],
) -> None:
    for file_path in iter_supported_files(rule.path):
        if file_path in processed:
            continue
        try:
            stat = file_path.stat()
        except Exception:
            continue

        stamp = (stat.st_mtime, stat.st_size)
        previous = known.get(file_path)
        known[file_path] = stamp
        if previous is None or previous != stamp:
            continue

        try:
            doc_id = content_hash(file_path)
        except Exception as exc:
            ui(f"Hash failed for {file_path}: {exc}", logger=_LOG)
            processed.add(file_path)
            continue

        if doc_store.get_by_id(doc_id):
            ui(f"Already indexed: {file_path}", logger=_LOG)
            processed.add(file_path)
            continue

        pending.append(
            IngestTask(
                path=file_path,
                workspace_id=rule.workspace_id,
                doc_type_hint=rule.doc_type_hint,
            )
        )


def _load_watch_rules(store: WatchStoreLike) -> list[WatchRule]:
    watched = store.list_watched_dirs()
    if not watched:
        ui("No watched directories.", logger=_LOG)
        return []

    rules: list[WatchRule] = []
    for row in watched:
        path = Path(row["path"]).expanduser()
        if not path.exists():
            ui(f"Skipping missing watch path: {path}", logger=_LOG)
            continue
        rules.append(
            WatchRule(
                path=path,
                workspace_id=row["workspace_id"],
                doc_type_hint=row["doc_type_hint"],
            )
        )
    if not rules:
        ui("No valid watch paths.", logger=_LOG)
    return rules


def _process_ingest_tasks(tasks: Iterable[IngestTask]) -> list[IngestOutcome]:
    from linkora.pipeline.ingest import ingest

    async def _run_all() -> list[IngestOutcome]:
        outcomes: list[IngestOutcome] = []
        for task in tasks:
            try:
                ingest_result = await ingest(
                    path=task.path,
                    workspace_id=task.workspace_id,
                    metadata_hint=task.metadata_hint,
                    doc_type_hint=task.doc_type_hint,
                )
                ui(f"+ {task.path.name} -> {ingest_result.doc_id}", logger=_LOG)
                outcomes.append(
                    IngestOutcome(task=task, doc_id=ingest_result.doc_id, success=True)
                )
            except Exception as exc:
                ui(f"x {task.path.name}: {exc}", logger=_LOG)
                outcomes.append(
                    IngestOutcome(task=task, doc_id=None, success=False, error=str(exc))
                )
        return outcomes

    return asyncio.run(_run_all())


def _delete_older_duplicates(paths: list[Path]) -> None:
    for old_file in paths:
        try:
            old_file.unlink()
            ui(f"  DELETED: {old_file}", logger=_LOG)
        except Exception as exc:
            ui(f"  ERROR deleting {old_file}: {exc}", logger=_LOG)


__all__ = [
    "SUPPORTED_SUFFIXES",
    "IngestTask",
    "IngestOutcome",
    "FileScanSpec",
    "FileBatch",
    "WatchRule",
    "FilesInboxRequest",
    "FilesTidyRequest",
    "FilesDedupRequest",
    "FilesRescanRequest",
    "FilesWatchAddRequest",
    "RescanStats",
    "iter_supported_files",
    "run_files_inbox",
    "run_files_tidy",
    "run_files_dedup",
    "run_files_rescan",
    "run_files_watch_add",
    "run_files_watch_list",
    "run_files_watch_start",
]
