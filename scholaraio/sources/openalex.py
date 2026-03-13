"""sources/openalex.py — OpenAlex API paper source for journal exploration.

Refactored to use OpenAlexSource class with PaperSource Protocol.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import requests

from scholaraio.log import get_logger
from scholaraio.sources.protocol import PaperSource

_log = get_logger(__name__)

# ============================================================================
#  Constants
# ============================================================================

_OA_WORKS = "https://api.openalex.org/works"
_PER_PAGE = 200


# ============================================================================
#  Internal Helpers
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
#  OpenAlexSource (PaperSource Protocol)
# ============================================================================


@dataclass(frozen=True)
class OpenAlexSource:
    """OpenAlex API paper source for journal exploration.

    Implements PaperSource Protocol for unified access to OpenAlex data.

    Example:
        source = OpenAlexSource()
        for paper in source.fetch(issn="0022-1120", year_range="2020-2025"):
            print(paper["title"])
    """

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
        """Get total paper count from OpenAlex.

        Note: OpenAlex doesn't provide count without fetching.
        This is a placeholder - actual count comes after fetch.
        """
        return 0
