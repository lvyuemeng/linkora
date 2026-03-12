"""Shared argument parsers for CLI commands."""

from __future__ import annotations

import argparse


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    """Add common filter arguments (--year, --journal, --type)."""
    parser.add_argument(
        "--year", type=str, default=None, help="Year filter: 2023 / 2020-2024 / 2020-"
    )
    parser.add_argument(
        "--journal", type=str, default=None, help="Journal name filter (LIKE)"
    )
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        dest="paper_type",
        help="Paper type filter: review / journal-article etc. (LIKE)",
    )


def resolve_top_k(args: argparse.Namespace, default: int) -> int:
    """Resolve top_k from args or return default."""
    return args.top if args.top is not None else default


__all__ = [
    "add_filter_args",
    "resolve_top_k",
]
