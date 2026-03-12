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
import sqlite3
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
#  Embedding
# ============================================================================


def build_explore_vectors(
    name: str, *, rebuild: bool = False, cfg: Config | None = None
) -> int:
    """为探索库生成语义向量。

    复用主库的 Qwen3-Embedding 模型，向量存入探索库自己的
    ``explore.db``。

    Args:
        name: 探索库名称。
        rebuild: 为 ``True`` 时清空重建。
        cfg: 可选的全局配置（用于模型加载）。

    Returns:
        本次新嵌入的论文数量。
    """
    from scholaraio.vectors import (
        _append_faiss_files,
        _embed_batch,
        _ensure_schema,
        _load_model,
        _pack,
    )

    _load_model(cfg)

    db = _db_path(name, cfg)
    conn = sqlite3.connect(db)
    try:
        _ensure_schema(conn)

        if rebuild:
            conn.execute("DELETE FROM paper_vectors")

        existing = set()
        if not rebuild:
            existing = {
                row[0]
                for row in conn.execute("SELECT paper_id FROM paper_vectors").fetchall()
            }

        to_embed: list[tuple[str, str]] = []
        for p in iter_papers(name, cfg):
            pid = p.get("doi") or p.get("openalex_id", "")
            if not pid or pid in existing:
                continue
            title = (p.get("title") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            if not abstract or _is_boilerplate(abstract):
                continue
            if p.get("type") in ("paratext", "erratum", "editorial"):
                continue
            text = f"{title}\n\n{abstract}" if title else abstract
            to_embed.append((pid, text))

        if not to_embed:
            return 0

        _log.info("Embedding %d papers...", len(to_embed))

        batch_size = 64
        total = 0
        all_new_ids: list[str] = []
        all_new_vecs: list[list[float]] = []
        for i in range(0, len(to_embed), batch_size):
            batch = to_embed[i : i + batch_size]
            texts = [t for _, t in batch]
            vecs = _embed_batch(texts, cfg)
            for (pid, _), vec in zip(batch, vecs):
                blob = _pack(vec)
                conn.execute(
                    "INSERT OR REPLACE INTO paper_vectors "
                    "(paper_id, embedding) VALUES (?, ?)",
                    (pid, blob),
                )
                all_new_ids.append(pid)
                all_new_vecs.append(vec)
            total += len(batch)
            if total % (batch_size * 10) == 0 or i + batch_size >= len(to_embed):
                _log.info("Progress: %d/%d", total, len(to_embed))

        conn.commit()
    finally:
        conn.close()

    if all_new_ids:
        explore_dir = _explore_dir(name, cfg)
        _append_faiss_files(
            explore_dir / "faiss.index",
            explore_dir / "faiss_ids.json",
            all_new_ids,
            all_new_vecs,
        )

    return len(to_embed)


# ============================================================================
#  Topics (BERTopic) — delegates to topics.py
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


def build_explore_topics(
    name: str,
    *,
    rebuild: bool = False,
    min_topic_size: int = 30,
    nr_topics: int | str | None = None,
    cfg: Config | None = None,
) -> dict:
    """对探索库运行 BERTopic 主题建模。

    复用主库的 ``build_topics()`` 流程，但参数针对大规模数据调整
    （默认 ``min_topic_size=30``）。模型以统一格式保存（bertopic_model.pkl +
    scholaraio_meta.pkl），可直接用 ``topics.load_model()`` 加载。

    Args:
        name: 探索库名称。
        rebuild: 为 ``True`` 时重建模型。
        min_topic_size: HDBSCAN 最小聚类大小。
        nr_topics: 目标主题数。``"auto"`` 自动合并。
        cfg: 可选的全局配置。

    Returns:
        统计字典：``{"n_topics": N, "n_outliers": N, "n_papers": N}``。
    """
    from scholaraio.vectors import _load_model

    _load_model(cfg)

    model_dir = _explore_dir(name, cfg) / "topic_model"
    if model_dir.exists() and not rebuild:
        return _load_topic_info(name, cfg)

    db = _db_path(name, cfg)
    if not db.exists():
        raise FileNotFoundError(
            f"向量库不存在: {db}\n请先运行 explore embed --name {name}"
        )

    papers_map = build_papers_map(name, cfg)

    from scholaraio.topics import build_topics

    # Compute explore-tuned hyperparameters
    n = len(papers_map)
    model = build_topics(
        db,
        papers_map=papers_map,
        min_topic_size=min_topic_size,
        nr_topics=nr_topics,
        save_path=model_dir,
        cfg=cfg,
        n_neighbors=min(15, max(5, n // 50)),
        n_components=min(5, max(2, n // 200)),
        min_samples=max(1, min_topic_size // 5),
        ngram_range=(1, 2),
        min_df=1,
    )

    # Write info.json for quick stats retrieval
    topics = getattr(model, "_topics", [])
    n_topics = len(set(topics)) - (1 if -1 in topics else 0)
    n_outliers = sum(1 for t in topics if t == -1)
    info = {"n_topics": n_topics, "n_outliers": n_outliers, "n_papers": len(topics)}
    (model_dir / "info.json").write_text(
        json.dumps(info, indent=2) + "\n", encoding="utf-8"
    )
    return info


def _load_topic_info(name: str, cfg: Config | None = None) -> dict:
    info_path = _explore_dir(name, cfg) / "topic_model" / "info.json"
    if info_path.exists():
        return json.loads(info_path.read_text("utf-8"))
    return {}


def _build_faiss_index(name: str, cfg: Config | None = None):
    """Build or load a FAISS index for an explore silo."""
    from scholaraio.vectors import _build_faiss_from_db

    explore_dir = _explore_dir(name, cfg)
    return _build_faiss_from_db(
        _db_path(name, cfg),
        explore_dir / "faiss.index",
        explore_dir / "faiss_ids.json",
        empty_msg=f"向量库为空: {_db_path(name, cfg)}",
    )


def explore_vsearch(
    name: str, query: str, *, top_k: int = 10, cfg: Config | None = None
) -> list[dict]:
    """在探索库中进行语义搜索（FAISS 加速）。

    Args:
        name: 探索库名称。
        query: 查询文本。
        top_k: 返回条数。
        cfg: 可选的全局配置。

    Returns:
        论文列表，按 cosine similarity 降序。
    """
    from scholaraio.vectors import _vsearch_faiss

    index, paper_ids = _build_faiss_index(name, cfg)
    hits = _vsearch_faiss(query, index, paper_ids, top_k, cfg=cfg)

    paper_map = {}
    for p in iter_papers(name, cfg):
        pid = p.get("doi") or p.get("openalex_id", "")
        if pid:
            paper_map[pid] = p

    results = []
    for pid, score in hits:
        p = paper_map.get(pid, {})
        results.append({**p, "score": score})
    return results
