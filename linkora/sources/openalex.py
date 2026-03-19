"""sources/openalex.py — OpenAlex API paper source.

Redesigned to use PaperSource Protocol with search() + fetch_by_id().
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

from linkora.log import get_logger
from linkora.sources.protocol import PaperCandidate, PaperQuery

if TYPE_CHECKING:
    from linkora.http import HTTPClient

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


def _parse_work_to_candidate(
    item: dict, source_name: str = "openalex"
) -> PaperCandidate:
    """Parse OpenAlex work item to PaperCandidate."""
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

    # Get journal name from primary location
    journal = None
    primary_location = item.get("primary_location", {})
    source = primary_location.get("source") or {}
    journal = source.get("display_name")

    openalex_id = item.get("id", "")

    return PaperCandidate(
        id=doi or openalex_id,
        doi=doi,
        title=clean_title,
        authors=authors,
        year=item.get("publication_year"),
        journal=journal,
        abstract=abstract if abstract and not _is_boilerplate(abstract) else None,
        cited_by_count=item.get("cited_by_count", 0),
        paper_type=item.get("type"),
        pdf_url=None,
        source=source_name,
        source_id=openalex_id,
    )


# ============================================================================
#  OpenAlexSource Implementation
# ============================================================================


@dataclass(frozen=True)
class OpenAlexSource:
    """OpenAlex API paper source.

    Redesigned to use PaperSource Protocol.
    Requires HTTPClient injection.
    """

    http_client: HTTPClient

    @property
    def name(self) -> str:
        return "openalex"

    def search(self, query: PaperQuery) -> Iterator[PaperCandidate]:
        """Search papers by ISSN, author, or title.

        Args:
            query: PaperQuery with search criteria

        Yields:
            PaperCandidate instances matching the query
        """
        if query.issn:
            yield from self._search_by_issn(query)

        if query.author:
            yield from self._search_by_author(query)

        if query.title:
            yield from self._search_by_title(query)

    def _search_by_issn(self, query: PaperQuery) -> Iterator[PaperCandidate]:
        """Search by journal ISSN."""
        if not query.issn:
            return

        year_range = self._build_year_filter(query)
        cursor = "*"

        while cursor:
            papers, cursor = self._fetch_issn_page(query.issn, cursor, year_range)
            if not papers:
                break
            for item in papers:
                yield _parse_work_to_candidate(item, self.name)

    def _search_by_author(self, query: PaperQuery) -> Iterator[PaperCandidate]:
        """Search by author name."""
        if not query.author:
            return

        year_range = self._build_year_filter(query)
        cursor = "*"

        while cursor:
            papers, cursor = self._fetch_search_page(
                f"author.name:{query.author}", cursor, year_range
            )
            if not papers:
                break
            for item in papers:
                yield _parse_work_to_candidate(item, self.name)

    def _search_by_title(self, query: PaperQuery) -> Iterator[PaperCandidate]:
        """Search by paper title."""
        if not query.title:
            return

        year_range = self._build_year_filter(query)
        cursor = "*"

        while cursor:
            papers, cursor = self._fetch_search_page(query.title, cursor, year_range)
            if not papers:
                break
            for item in papers:
                yield _parse_work_to_candidate(item, self.name)

    def _build_year_filter(self, query: PaperQuery) -> str | None:
        """Build OpenAlex year filter string."""
        if not query.year_start:
            return None
        if query.year_end:
            return f"{query.year_start}-{query.year_end}"
        return f"{query.year_start}-{query.year_start}"

    def _fetch_issn_page(
        self,
        issn: str,
        cursor: str,
        year_range: str | None = None,
        per_page: int = _PER_PAGE,
    ) -> tuple[list[dict], str | None]:
        """Fetch one page of results by ISSN."""
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

        return self._do_request(params)

    def _fetch_search_page(
        self,
        search_term: str,
        cursor: str,
        year_range: str | None = None,
        per_page: int = _PER_PAGE,
    ) -> tuple[list[dict], str | None]:
        """Fetch one page of search results."""
        params = {
            "search": search_term,
            "per_page": per_page,
            "cursor": cursor,
            "select": "id,title,publication_year,doi,authorships,abstract_inverted_index,"
            "primary_location,cited_by_count,type",
        }
        if year_range:
            params["filter"] = f"publication_year:{year_range}"

        return self._do_request(params)

    def _do_request(self, params: dict) -> tuple[list[dict], str | None]:
        """Execute request and parse response."""
        resp = self.http_client.get(_OA_WORKS, params=params, timeout=30)

        # Handle rate limiting
        if resp.status_code == 429:
            raise RuntimeError("OpenAlex API rate limit exceeded")

        resp.raise_for_status()
        data = resp.json()

        papers = data.get("results", [])
        next_cursor = data.get("meta", {}).get("next_cursor")
        return papers, next_cursor

    def fetch_by_id(self, paper_id: str) -> PaperCandidate | None:
        """Fetch paper by DOI.

        Args:
            paper_id: DOI (preferred) or OpenAlex ID

        Returns:
            PaperCandidate if found, None otherwise
        """
        # Check if it's a DOI
        if paper_id.startswith("10."):
            url = f"{_OA_WORKS}/doi:{paper_id}"
        else:
            # Assume it's an OpenAlex ID
            url = f"{_OA_WORKS}/{paper_id}"

        try:
            resp = self.http_client.get(url, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return _parse_work_to_candidate(data, self.name)
        except Exception as e:
            _log.debug("Failed to fetch paper by ID %s: %s", paper_id, e)
            return None
