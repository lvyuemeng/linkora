"""
explore.py — 期刊全量探索
==========================

从 OpenAlex 批量拉取期刊论文（title + abstract），本地嵌入 + FAISS
语义搜索。主题建模、可视化、查询复用 ``topics.py``（通过 ``papers_map``
参数）。数据存储在 ``data/explore/<name>/``，与主库完全隔离。

用法::

    from scholaraio.explore import fetch_journal, build_explore_vectors, build_explore_topics
    fetch_journal("jfm", issn="0022-1120")
    build_explore_vectors("jfm")
    build_explore_topics("jfm")
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import requests

from scholaraio.log import ui

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from scholaraio.config import Config

# ============================================================================
#  Config / paths
# ============================================================================

_DEFAULT_EXPLORE_DIR = Path("data/explore")


def _explore_dir(name: str, cfg: Config | None = None) -> Path:
    if cfg is not None:
        return cfg._root / "data" / "explore" / name
    return _DEFAULT_EXPLORE_DIR / name


def _papers_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "papers.jsonl"


def _db_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "explore.db"


def _meta_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "meta.json"


# ============================================================================
#  Fetch from OpenAlex
# ============================================================================


def _is_boilerplate(abstract: str) -> bool:
    """Detect publisher boilerplate instead of real abstract."""
    low = abstract.lower()
    return (
        "abstract is not available" in low
        or "preview has been provided" in low
        or "access link" in low
    )


_OA_WORKS = "https://api.openalex.org/works"
_PER_PAGE = 200


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """Reconstruct abstract from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


def _fetch_page(
    issn: str, page: int, year_range: str | None = None, cursor: str = "*"
) -> tuple[list[dict], str | None]:
    """Fetch one page of results from OpenAlex."""
    filt = f"primary_location.source.issn:{issn}"
    if year_range:
        filt += f",publication_year:{year_range}"

    params = {
        "filter": filt,
        "per_page": _PER_PAGE,
        "cursor": cursor,
        "select": "id,title,publication_year,doi,authorships,abstract_inverted_index,"
        "primary_location,cited_by_count,type",
        "sort": "publication_year:asc",
    }
    # Retry with exponential backoff for transient errors
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(
                _OA_WORKS,
                params=params,
                timeout=30,
                proxies={"http": None, "https": None},
            )
            if resp.status_code == 429:
                wait = 2**attempt
                _log.warning("OpenAlex 429 rate limit, retrying in %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            wait = 2**attempt
            _log.warning(
                "OpenAlex request failed (attempt %d/3): %s, retrying in %ds",
                attempt + 1,
                e,
                wait,
            )
            time.sleep(wait)
    else:
        if last_exc:
            raise last_exc
        raise requests.HTTPError("OpenAlex API returned 429 after 3 retries")

    papers = []
    for item in data.get("results", []):
        doi_raw = item.get("doi") or ""
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""

        authors = []
        for a in item.get("authorships") or []:
            name = (a.get("author") or {}).get("display_name")
            if name:
                authors.append(name)

        abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))

        # Strip HTML tags from title (OpenAlex includes <b>, <scp>, <i>, etc.)
        raw_title = item.get("title") or ""
        clean_title = re.sub(r"<[^>]+>", "", raw_title)

        papers.append(
            {
                "openalex_id": item.get("id", ""),
                "doi": doi,
                "title": clean_title,
                "abstract": abstract,
                "authors": authors,
                "year": item.get("publication_year"),
                "cited_by_count": item.get("cited_by_count", 0),
                "type": item.get("type", ""),
            }
        )

    next_cursor = data.get("meta", {}).get("next_cursor")
    return papers, next_cursor


def fetch_journal(
    name: str,
    issn: str,
    *,
    year_range: str | None = None,
    cfg: Config | None = None,
) -> int:
    """从 OpenAlex 批量拉取期刊全量论文。

    使用 cursor-based 分页遍历指定 ISSN 的所有论文，
    提取 title、abstract、authors 等字段，写入 JSONL 文件。

    Args:
        name: 探索库名称（如 ``"jfm"``），用作目录名。
        issn: 期刊 ISSN（如 ``"0022-1120"``）。
        year_range: 年份过滤（如 ``"2020-2025"``），为 ``None`` 时拉取全量。
        cfg: 可选的全局配置。

    Returns:
        拉取的论文总数。
    """
    out_dir = _explore_dir(name, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    papers_file = _papers_path(name, cfg)
    meta_file = _meta_path(name, cfg)

    from scholaraio.metrics import timer

    total = 0
    cursor = "*"

    with timer("explore.fetch", "api") as t:
        tmp_file = papers_file.with_suffix(".jsonl.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            page = 0
            while cursor:
                page += 1
                papers, cursor = _fetch_page(issn, page, year_range, cursor)
                if not papers:
                    break
                for p in papers:
                    f.write(json.dumps(p, ensure_ascii=False) + "\n")
                total += len(papers)
                _log.info(
                    "page %d: +%d papers (total %d, %.0fs)",
                    page,
                    len(papers),
                    total,
                    t.elapsed,
                )
        tmp_file.replace(papers_file)

    meta = {
        "name": name,
        "source": "openalex",
        "issn": issn,
        "year_range": year_range,
        "count": total,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_seconds": round(t.elapsed, 1),
    }
    meta_file.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    ui(f"Done: {total} papers, {t.elapsed:.0f}s -> {papers_file}")
    return total


# ============================================================================
#  Load papers from JSONL
# ============================================================================


def iter_papers(name: str, cfg: Config | None = None) -> Iterator[dict]:
    """逐行读取 JSONL，yield 论文字典。"""
    path = _papers_path(name, cfg)
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def count_papers(name: str, cfg: Config | None = None) -> int:
    """返回探索库中的论文数量。"""
    meta_file = _meta_path(name, cfg)
    if meta_file.exists():
        return json.loads(meta_file.read_text("utf-8")).get("count", 0)
    return sum(1 for _ in iter_papers(name, cfg))


# ============================================================================
#  Paper Map Builder
# ============================================================================


def build_papers_map(name: str, cfg: Config | None = None) -> dict[str, dict]:
    """从 JSONL 构建 paper_id → metadata 映射。

    Args:
        name: 探索库名称。
        cfg: 可选的全局配置。

    Returns:
        ``{paper_id: paper_dict}`` 映射，paper_id 为 DOI 或 openalex_id。
    """
    pm: dict[str, dict] = {}
    for p in iter_papers(name, cfg):
        pid = p.get("doi") or p.get("openalex_id", "")
        if pid:
            pm[pid] = p
    return pm


# ============================================================================
#  Path Helpers (for external use with VectorIndex/TopicTrainer)
# ============================================================================


def get_explore_dir(name: str, cfg: Config | None = None) -> Path:
    """Get explore directory path."""
    return _explore_dir(name, cfg)


def get_explore_db_path(name: str, cfg: Config | None = None) -> Path:
    """Get explore vector database path."""
    return _db_path(name, cfg)
