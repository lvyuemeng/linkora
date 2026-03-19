"""matching.py — Paper matching and source dispatcher.

Contains:
- DefaultDispatcher: Source dispatcher for paper matching
- match_papers: Match papers from sources
- score_candidate: Score candidate against query
- parse_freeform_query: Parse free-form query strings
"""

from __future__ import annotations

from pathlib import Path

from linkora.log import get_logger
from linkora.sources.protocol import PaperCandidate, PaperQuery, PaperSource

_log = get_logger(__name__)

# rapidfuzz availability
try:
    from rapidfuzz import fuzz as fuzz_module

    _has_rapidfuzz = True
except ImportError:
    fuzz_module = None  # type: ignore[misc,assignment]
    _has_rapidfuzz = False


# ============================================================================
#  Source Dispatcher Implementation
# ============================================================================


class DefaultDispatcher:
    """Default source dispatcher - selects sources based on query.

    Uses query fields to determine which sources to try:
    - DOI -> OpenAlex (best for DOI lookup)
    - ISSN -> OpenAlex (best for journal papers)
    - Author -> OpenAlex (best for author search)
    - Title -> OpenAlex (best for title search)
    - Fallback -> Try local first, then remote

    Caches source instances for efficiency.
    """

    def __init__(
        self,
        local_pdf_dir: Path | None = None,
        http_client=None,
    ):
        self._local_pdf_dir = local_pdf_dir
        self._http_client = http_client
        # Cache source instances
        self._local_source: PaperSource | None = None
        self._openalex_source: PaperSource | None = None
        self._initialized = False

    def _ensure_sources(self) -> None:
        """Initialize and cache source instances."""
        if self._initialized:
            return

        from linkora.sources import LocalSource, OpenAlexSource

        # Create local source if configured
        if self._local_pdf_dir:
            try:
                self._local_source = LocalSource(pdf_dir=self._local_pdf_dir)
            except Exception as e:
                _log.debug("LocalSource failed: %s", e)

        # Create OpenAlex source if http_client available
        if self._http_client:
            try:
                self._openalex_source = OpenAlexSource(http_client=self._http_client)
            except Exception as e:
                _log.debug("OpenAlexSource failed: %s", e)

        self._initialized = True

    def select(self, query: PaperQuery) -> list[PaperSource]:
        """Select sources based on query fields."""
        self._ensure_sources()

        sources = []

        # DOI lookup - OpenAlex is best
        if query.doi and self._openalex_source:
            sources.append(self._openalex_source)

        # ISSN search - OpenAlex is best for journal
        if query.issn and self._openalex_source:
            sources.append(self._openalex_source)

        # Author search - OpenAlex
        if query.author and self._openalex_source:
            sources.append(self._openalex_source)

        # Title search - OpenAlex
        if query.title and self._openalex_source:
            sources.append(self._openalex_source)

        # Fallback - try local first, then remote
        if not sources:
            if self._local_source:
                sources.append(self._local_source)
            if self._openalex_source:
                sources.append(self._openalex_source)

        return sources


# ============================================================================
#  Candidate Scoring
# ============================================================================


def score_candidate(candidate: PaperCandidate, query: PaperQuery) -> float:
    """Score a candidate paper against query.

    Scoring weights:
    - DOI exact match: 1000
    - ISSN match: 500
    - Author fuzzy: 0-100
    - Title fuzzy: 0-100
    - Year match: 50
    - Has PDF: 10
    """
    score = 0.0

    # DOI scoring
    score += _score_doi(query.doi, candidate.doi)

    # ISSN scoring
    score += _score_issn(query.issn, candidate.journal)

    # Author scoring
    score += _score_author(query.author, candidate.authors)

    # Title scoring
    score += _score_title(query.title, candidate.title)

    # Year scoring
    score += _score_year(query.year_start, query.year_end, candidate.year)

    # PDF availability
    if candidate.pdf_url:
        score += 10

    return score


def _score_doi(query_doi: str | None, candidate_doi: str | None) -> float:
    """Score DOI match."""
    if not query_doi or not candidate_doi:
        return 0.0
    q = query_doi.lower()
    c = candidate_doi.lower()
    return 1000 if q == c else (100 if q in c else 0)


def _score_issn(query_issn: str | None, candidate_journal: str | None) -> float:
    """Score ISSN/journal match."""
    if not query_issn or not candidate_journal:
        return 0.0
    issn_clean = query_issn.replace("-", "")
    journal_clean = candidate_journal.replace("-", "").replace(" ", "")
    return 500 if issn_clean in journal_clean else 0


def _score_author(
    query_author: str | None, candidate_authors: list[str] | None
) -> float:
    """Score author match."""
    if not query_author or not candidate_authors:
        return 0.0
    author_lower = query_author.lower()
    for author in candidate_authors:
        if author_lower in author.lower():
            return 50
        if author_lower == author.lower():
            return 50
    return 0


def _score_title(query_title: str | None, candidate_title: str | None) -> float:
    """Score title match."""
    if not query_title or not candidate_title:
        return 0.0
    if _has_rapidfuzz and fuzz_module:
        title_score = fuzz_module.ratio(query_title.lower(), candidate_title.lower())  # type: ignore[union-attr]
        return title_score
    # Fallback to simple substring match
    return 50 if query_title.lower() in candidate_title.lower() else 0


def _score_year(
    year_start: int | None, year_end: int | None, candidate_year: int | None
) -> float:
    """Score year match."""
    if not year_start or not candidate_year:
        return 0.0
    end = year_end or year_start
    return 50 if year_start <= candidate_year <= end else 0


def _candidate_to_dict(candidate: PaperCandidate, query: PaperQuery) -> dict:
    """Convert PaperCandidate to dict with score."""
    return {
        "id": candidate.id,
        "doi": candidate.doi,
        "title": candidate.title,
        "authors": candidate.authors,
        "year": candidate.year,
        "journal": candidate.journal,
        "abstract": candidate.abstract,
        "cited_by_count": candidate.cited_by_count,
        "paper_type": candidate.paper_type,
        "pdf_url": candidate.pdf_url,
        "source": candidate.source,
        "source_id": candidate.source_id,
        "_match_score": score_candidate(candidate, query),
        "_match_source": candidate.source,
    }


# ============================================================================
#  Paper Matching
# ============================================================================


def _deduplicate_candidates(candidates: list[dict]) -> list[dict]:
    """Deduplicate candidates by DOI."""
    seen_dois: set[str] = set()
    unique: list[dict] = []

    for c in candidates:
        doi = c.get("doi", "")
        if doi and doi in seen_dois:
            continue
        if doi:
            seen_dois.add(doi)
        unique.append(c)

    return unique


def match_papers(
    query: PaperQuery,
    dispatcher: DefaultDispatcher,
    limit: int = 5,
) -> list[dict]:
    """Match papers using dispatcher for source selection.

    Args:
        query: Parsed query with doi/issn/author/title/year
        dispatcher: DefaultDispatcher to select sources
        limit: Max results to return (default: 5)

    Returns:
        List of matched paper dicts, sorted by relevance
    """
    all_candidates: list[dict] = []

    # Get sources from dispatcher
    sources = dispatcher.select(query)

    for source in sources:
        try:
            # Each source provides candidates
            for candidate in source.search(query):
                candidate_dict = _candidate_to_dict(candidate, query)
                all_candidates.append(candidate_dict)

        except Exception as e:
            _log.debug("Source %s failed: %s", source.name, e)
            continue

    # Also try fetch_by_id for DOI lookups
    if query.doi:
        for source in sources:
            try:
                candidate = source.fetch_by_id(query.doi)
                if candidate:
                    candidate_dict = _candidate_to_dict(candidate, query)
                    # Boost exact DOI matches
                    candidate_dict["_match_score"] += 500
                    all_candidates.append(candidate_dict)
            except Exception as e:
                _log.debug("Source %s fetch_by_id failed: %s", source.name, e)
                continue

    # Sort and return top N
    all_candidates.sort(key=lambda x: x.get("_match_score", 0), reverse=True)

    # Deduplicate by DOI
    return _deduplicate_candidates(all_candidates)[:limit]
