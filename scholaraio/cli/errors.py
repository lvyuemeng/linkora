"""CLI exceptions and error handling."""

from __future__ import annotations

import sys
import logging


_log = logging.getLogger(__name__)


class CLIError(Exception):
    """Base exception for CLI errors."""

    def __init__(self, message: str, exit_code: int = 1):
        self.message = message
        self.exit_code = exit_code
        super().__init__(message)


class ConfigError(CLIError):
    """Configuration-related errors."""

    pass


class PaperNotFoundError(CLIError):
    """Paper not found in the library."""

    def __init__(self, paper_id: str):
        super().__init__(f"Paper not found: {paper_id}", exit_code=2)


class IndexNotFoundError(CLIError):
    """Index database not found."""

    def __init__(self, db_path: str):
        super().__init__(
            f"Index file not found: {db_path}\nRun `scholaraio index` first.",
            exit_code=3,
        )


def handle_error(e: Exception) -> None:
    """Handle an exception and exit with appropriate code."""
    if isinstance(e, CLIError):
        _log.error("%s", e.message)
        sys.exit(e.exit_code)
    else:
        _log.error("%s", e)
        sys.exit(1)


__all__ = [
    "CLIError",
    "ConfigError",
    "PaperNotFoundError",
    "IndexNotFoundError",
    "handle_error",
]
