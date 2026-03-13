"""
explore.py — Journal Exploration

Fetch papers from OpenAlex, build local embeddings + FAISS for semantic search.
Topic modeling, visualization, queries reuse topics.py (via papers_map parameter).
Data stored in data/explore/<name>/, isolated from main library.

Usage::

    from scholaraio.explore import OpenAlexSource, ExploreSession

    # Fetch papers from OpenAlex
    source = OpenAlexSource()
    session = ExploreSession(name="jfm", source=source)
    session.fetch(issn="0022-1120")

    # Build vectors
    session.build_vectors()

    # Build topics
    session.build_topics()
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Iterator

import requests

from scholaraio.log import get_logger, ui
from scholaraio.config import Config

_log = get_logger(__name__)

# ============================================================================
#  Constants
# ============================================================================

_OA_WORKS = "https://api.openalex.org/works"
_PER_PAGE = 200
_DEFAULT_EXPLORE_DIR = Path("data/explore")

# ============================================================================
#  PaperSource Protocol (Unified)
# ============================================================================


class PaperSource(Protocol):
    """Protocol for paper data sources (local files, remote APIs, databases)."""

    @property
    def name(self) -> str:
        """Source name identifier."""
        ...

    def fetch(self, **kwargs) -> Iterator[dict]:
        """Fetch paper data from source.

        Yields paper dicts with title, abstract, authors, etc.
        """
        ...

    def count(self, **kwargs) -> int:
        """Count papers available in source."""
        ...


# ============================================================================
#  Helper Functions
# ============================================================================


def _is_boilerplate(abstract: str) -> bool:
    """Detect publisher boilerplate instead of real abstract."""
    low = abstract.lower()
    return (
        "abstract is not available" in low
        or "preview has been provided" in low
        or "access link" in low
    )


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


# ============================================================================
#  OpenAlexSource Implementation
# ============================================================================


class OpenAlexSource:
    """OpenAlex API paper source for journal exploration."""

    @property
    def name(self) -> str:
        return "openalex"

    def fetch(
        self,
        issn: str,
        year_range: str | None = None,
        **kwargs,
    ) -> Iterator[dict]:
        """Fetch papers from OpenAlex API.

        Args:
            issn: Journal ISSN.
            year_range: Year range filter (e.g., "2020-2025").
            **kwargs: Additional parameters (page_size, etc.).

        Yields:
            Paper dicts with openalex_id, doi, title, abstract, authors, etc.
        """
        page_size = kwargs.get("page_size", _PER_PAGE)
        cursor = "*"

        while cursor:
            papers, cursor = _fetch_page(issn, cursor, year_range, page_size)
            if not papers:
                break
            yield from papers

    def count(self, issn: str, **kwargs) -> int:
        """Get total paper count from OpenAlex."""
        # Note: OpenAlex doesn't provide count without fetching
        # This is a placeholder - actual count comes after fetch
        return 0


def _fetch_page(
    issn: str, cursor: str, year_range: str | None = None, per_page: int = _PER_PAGE
) -> tuple[list[dict], str | None]:
    """Fetch one page of results from OpenAlex."""
    filt = f"primary_location.source.issn:{issn}"
    if year_range:
        filt += f",publication_year:{year_range}"

    params = {
        "filter": filt,
        "per_page": per_page,
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
                proxies={"http": None, "https": None},  # type: ignore[arg-type]
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

        # Strip HTML tags from title
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


# ============================================================================
#  Separated States
# ============================================================================


@dataclass(frozen=True)
class ExploreOptions:
    """Options for exploration."""

    name: str
    issn: str
    year_range: str | None = None


@dataclass(frozen=True)
class FetchedPapers:
    """Stage 1: Fetched papers from source."""

    name: str
    total: int
    elapsed: float


@dataclass(frozen=True)
class StoredPapers:
    """Stage 2: Papers stored in JSONL."""

    name: str
    papers_file: Path
    meta_file: Path
    count: int


@dataclass(frozen=True)
class PaperMap:
    """Stage 3: Paper ID to metadata mapping."""

    name: str
    mapping: dict[str, dict]


@dataclass(frozen=True)
class ExploreError:
    """Error state."""

    name: str
    stage: str
    error: str


# ============================================================================
#  ExploreSession
# ============================================================================


class ExploreSession:
    """Exploration session with injectable source."""

    def __init__(self, name: str, source: PaperSource, cfg: Config | None = None):
        """Initialize exploration session.

        Args:
            name: Exploration name (e.g., "jfm"), used as directory name.
            source: PaperSource implementation (e.g., OpenAlexSource).
            cfg: Optional global config.
        """
        self._name = name
        self._source = source
        self._cfg = cfg

    def _explore_dir(self) -> Path:
        if self._cfg is not None:
            return self._cfg._root / "data" / "explore" / self._name
        return _DEFAULT_EXPLORE_DIR / self._name

    def _papers_path(self) -> Path:
        return self._explore_dir() / "papers.jsonl"

    def _meta_path(self) -> Path:
        return self._explore_dir() / "meta.json"

    # Stage 1: Fetch
    def fetch(
        self, issn: str, year_range: str | None = None
    ) -> FetchedPapers | ExploreError:
        """Fetch papers from source and store in JSONL."""
        out_dir = self._explore_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        papers_file = self._papers_path()
        meta_file = self._meta_path()

        from scholaraio.metrics import timer

        total = 0

        with timer("explore.fetch", "api") as t:
            tmp_file = papers_file.with_suffix(".jsonl.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                for paper in self._source.fetch(issn=issn, year_range=year_range):
                    f.write(json.dumps(paper, ensure_ascii=False) + "\n")
                    total += 1
                    if total % 1000 == 0:
                        _log.info(
                            "fetched %d papers (%.0fs)", total, t.elapsed
                        )
            tmp_file.replace(papers_file)

        meta = {
            "name": self._name,
            "source": self._source.name,
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

        return FetchedPapers(
            name=self._name,
            total=total,
            elapsed=t.elapsed,
        )

    # Stage 2: Iterate papers
    def iter_papers(self) -> Iterator[dict]:
        """Iterate over stored papers."""
        path = self._papers_path()
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    # Stage 3: Build paper map
    def build_papers_map(self) -> PaperMap:
        """Build paper_id to metadata mapping."""
        pm: dict[str, dict] = {}
        for p in self.iter_papers():
            pid = p.get("doi") or p.get("openalex_id", "")
            if pid:
                pm[pid] = p
        return PaperMap(name=self._name, mapping=pm)

    # Path helpers for external use
    def get_dir(self) -> Path:
        """Get explore directory path."""
        return self._explore_dir()

    def get_db_path(self) -> Path:
        """Get explore vector database path."""
        return self._explore_dir() / "explore.db"


# ============================================================================
#  Legacy Functions
# ============================================================================

# BROKEN: Old standalone functions - removed.
# Use ExploreSession with OpenAlexSource instead.
