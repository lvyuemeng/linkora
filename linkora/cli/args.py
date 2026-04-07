"""
cli/args.py - Unified CLI argument handling.

Replaces repetitive getattr usage with structured dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import argparse


# ============================================================================
# Command Argument Dataclasses
# ============================================================================


@dataclass(frozen=True)
class AddArgs:
    """Arguments for 'add' command."""

    targets: list[str]
    workspace: str = ""
    source: str | None = None
    output: str = ""
    doc_type: str | None = None
    dry_run: bool = False

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> AddArgs:
        return cls(
            targets=getattr(args, "targets", []) or [],
            workspace=getattr(args, "workspace", "") or "",
            source=getattr(args, "source", None) or None,
            output=getattr(args, "output", "") or "",
            doc_type=getattr(args, "type", None) or None,
            dry_run=getattr(args, "dry_run", False) or False,
        )


@dataclass(frozen=True)
class SearchArgs:
    """Arguments for 'search' command."""

    query: list[str] = None  # type: ignore
    top: int = 20
    mode: str | None = None

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> SearchArgs:
        query = getattr(args, "query", []) or []
        return cls(
            query=query,
            top=getattr(args, "top", 20) or 20,
            mode=getattr(args, "mode", None) or None,
        )


@dataclass(frozen=True)
class EnrichArgs:
    """Arguments for 'enrich' command."""

    paper: str | None = None
    limit: int | None = None
    force: bool = False
    summary: bool = False
    outline: bool = False

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> EnrichArgs:
        return cls(
            paper=getattr(args, "paper", None) or None,
            limit=getattr(args, "limit", None) or None,
            force=getattr(args, "force", False) or False,
            summary=getattr(args, "summary", False) or False,
            outline=getattr(args, "outline", False) or False,
        )


@dataclass(frozen=True)
class IndexArgs:
    """Arguments for 'index' command."""

    fts: bool = False
    vector: bool = False
    topics: bool = False
    all: bool = False
    rebuild: bool = False

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> IndexArgs:
        return cls(
            fts=getattr(args, "fts", False) or False,
            vector=getattr(args, "vector", False) or False,
            topics=getattr(args, "topics", False) or False,
            all=getattr(args, "all", False) or False,
            rebuild=getattr(args, "rebuild", False) or False,
        )


@dataclass(frozen=True)
class ConfigShowArgs:
    """Arguments for 'config show' command."""

    field: str | None = None

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> ConfigShowArgs:
        return cls(field=getattr(args, "field", None) or None)


@dataclass(frozen=True)
class ConfigSetArgs:
    """Arguments for 'config set' command."""

    field: str
    value: str

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> ConfigSetArgs:
        return cls(field=args.field, value=args.value)


@dataclass(frozen=True)
class FilesInboxArgs:
    """Arguments for 'files inbox' command."""

    path: Path
    workspace: str = ""
    tidy: bool = False
    move_to: str = ""

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> FilesInboxArgs:
        return cls(
            path=Path(getattr(args, "path", ".")),
            workspace=getattr(args, "workspace", "") or "",
            tidy=getattr(args, "tidy", False) or False,
            move_to=getattr(args, "move_to", "") or "",
        )


@dataclass(frozen=True)
class FilesDedupArgs:
    """Arguments for 'files dedup' command."""

    path: Path
    delete_older: bool = False

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> FilesDedupArgs:
        return cls(
            path=Path(getattr(args, "path", ".")),
            delete_older=getattr(args, "delete_older", False) or False,
        )


@dataclass(frozen=True)
class FilesWatchAddArgs:
    """Arguments for 'files watch add' command."""

    path: Path
    workspace: str = ""
    type: str = ""

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> FilesWatchAddArgs:
        return cls(
            path=Path(getattr(args, "path", ".")),
            workspace=getattr(args, "workspace", "") or "",
            type=getattr(args, "type", "") or "",
        )


@dataclass(frozen=True)
class FilesRescanArgs:
    """Arguments for 'files rescan' command."""

    path: Path | None = None

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> FilesRescanArgs:
        path_str = getattr(args, "path", None)
        return cls(
            path=Path(path_str) if path_str else None,
        )


@dataclass(frozen=True)
class FilesTidyArgs:
    """Arguments for 'files tidy' command."""

    path: Path
    type: str = ""
    dry_run: bool = False

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> FilesTidyArgs:
        return cls(
            path=Path(getattr(args, "path", ".")),
            type=getattr(args, "type", "") or "",
            dry_run=getattr(args, "dry_run", False) or False,
        )


# ============================================================================
# Utility Functions
# ============================================================================


def safe_getattr(args: argparse.Namespace, name: str, default: Any = None) -> Any:
    """Safe getattr that doesn't violate philosophy - used only for migration."""
    return getattr(args, name, default) or default


__all__ = [
    "AddArgs",
    "SearchArgs",
    "EnrichArgs",
    "IndexArgs",
    "ConfigShowArgs",
    "ConfigSetArgs",
    "FilesInboxArgs",
    "FilesDedupArgs",
    "FilesWatchAddArgs",
    "FilesRescanArgs",
    "FilesTidyArgs",
    "safe_getattr",
]
