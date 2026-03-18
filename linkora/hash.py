"""
hash.py - Unified hash utilities for content change detection.

Provides consistent hash computation for:
- Full index content (FTS5)
- Embedding source text (vectors)

Follows design principles: pure functions, type safety, no repetition.
"""

from __future__ import annotations

import hashlib
import json


def compute_content_hash(title: str, abstract: str | None = None) -> str:
    """Compute hash for vector embedding source text.

    Args:
        title: Paper title.
        abstract: Paper abstract (optional).

    Returns:
        12-character MD5 hash string.
    """
    text = title
    if abstract:
        text += f"\n\n{abstract}"
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def compute_full_hash(meta: dict) -> str:
    """Compute hash for full FTS5 index content.

    Args:
        meta: Paper metadata dictionary.

    Returns:
        12-character MD5 hash string.
    """
    parts = [
        meta.get("title") or "",
        ", ".join(meta.get("authors") or []),
        str(meta.get("year") or ""),
        meta.get("journal") or "",
        meta.get("abstract") or "",
        meta.get("l3_conclusion") or "",
        meta.get("doi") or "",
        meta.get("paper_type") or "",
    ]
    cc = meta.get("citation_count")
    if cc and isinstance(cc, dict):
        vals = [v for v in cc.values() if isinstance(v, (int, float))]
        parts.append(str(max(vals)) if vals else "")
    parts.append(json.dumps(meta.get("references", []), sort_keys=True))
    text = "\n".join(parts)
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
