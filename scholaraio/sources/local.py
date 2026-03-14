"""
sources/local.py — 扫描 data/papers/ 目录，产出论文记录

Refactored to use LocalSource class with PaperSource Protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from scholaraio.papers import iter_paper_dirs, read_meta
from scholaraio.log import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class LocalSource:
    """Scan local papers directory as paper source.

    Implements PaperSource Protocol for unified access to local papers.

    Example:
        source = LocalSource(papers_dir=Path("data/papers"))
        for paper in source.fetch():
            print(paper["title"])
    """

    papers_dir: Path

    @property
    def name(self) -> str:
        return "local"

    def fetch(self, **kwargs) -> Iterator[dict]:
        """Fetch papers from local directory.

        Yields:
            Paper dicts with fields: id, title, authors, year, doi, journal, etc.
        """
        if not self.papers_dir.exists():
            _log.warning("Papers directory does not exist: %s", self.papers_dir)
            return

        # Iterate without sorted() - faster for large directories
        for pdir in self.papers_dir.iterdir():
            if not pdir.is_dir():
                continue

            # Single filesystem operation - use exception handling
            md_path = pdir / "paper.md"
            try:
                md_path.read_text()
            except FileNotFoundError:
                _log.debug("missing paper.md, skipping: %s", pdir.name)
                continue

            # Try to read meta.json
            try:
                meta = json.loads((pdir / "meta.json").read_text())
            except (json.JSONDecodeError, FileNotFoundError) as e:
                _log.debug("failed to read meta.json in %s: %s", pdir.name, e)
                continue

            paper_id = meta.get("id") or pdir.name
            yield {
                "id": paper_id,
                "title": meta.get("title", ""),
                "authors": meta.get("authors", []),
                "year": meta.get("year"),
                "doi": meta.get("doi"),
                "journal": meta.get("journal"),
                "abstract": meta.get("abstract"),
                "meta": meta,
                "md_path": str(md_path),
            }

    def count(self, **kwargs) -> int:
        """Count total papers in directory."""
        if not self.papers_dir.exists():
            return 0
        return sum(1 for p in self.papers_dir.iterdir() if p.is_dir())


# BROKEN: Use LocalSource class instead - kept for backward compatibility
def iter_papers(papers_dir: Path) -> Iterator[tuple[str, dict, Path]]:
    """遍历论文目录，逐篇产出元数据。

    .. deprecated::
        Use :class:`LocalSource` class instead.

    扫描 ``papers_dir`` 中每篇一目录的子目录结构，
    要求 ``meta.json`` 和 ``paper.md`` 均存在。

    Args:
        papers_dir: 已入库论文目录（每篇一目录结构）。

    Yields:
        ``(paper_id, meta_dict, md_path)`` 三元组。
        ``paper_id`` 为 ``meta.json["id"]``（UUID），
        回退到目录名。跳过缺少 ``paper.md`` 或解析失败的目录。
    """
    source = LocalSource(papers_dir)
    for paper in source.fetch():
        yield paper["id"], paper["meta"], Path(paper["md_path"])
