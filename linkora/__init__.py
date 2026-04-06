"""linkora — local-first document corpus CLI."""

from __future__ import annotations

import hashlib
from pathlib import Path

__version__ = "0.3.0"


def content_hash(path: Path, buffer_size: int = 65536) -> str:
    """Compute stable SHA-256 hash of file content.

    Args:
        path: Path to file
        buffer_size: Read buffer size

    Returns:
        64 character hex digest string
    """
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(buffer_size):
            sha256.update(chunk)
    return sha256.hexdigest()


def string_hash(content: str) -> str:
    """Compute hash of string content.

    Args:
        content: String content to hash

    Returns:
        64 character hex digest string
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = ["__version__", "content_hash", "string_hash"]
