"""ingest — Paper ingestion pipeline.

Submodules:
- download: PDF download utilities
- pipeline: Functional data pipe for paper ingestion

Main exports:
- DefaultDispatcher: Source dispatcher for paper matching
- match_papers: Match papers from sources
- score_candidate: Score candidate against query
- parse_freeform_query: Parse free-form query strings
- cmd_add: CLI command handler
- register: CLI argument registration
- IngestResult: Result of paper ingestion
- ingest: Functional pipeline for processing candidates
"""

from __future__ import annotations

import re

# Core matching (from matching.py)
from linkora.ingest.matching import (
    DefaultDispatcher,
    match_papers,
    score_candidate,
)

# Pipeline
from linkora.ingest.pipeline import ingest, IngestResult


# ============================================================================
#  Query Parsing Helpers
# ============================================================================


def _parse_year_arg(year_val: str | None) -> tuple[int | None, int | None]:
    """Parse year argument into start/end tuple."""
    if not year_val:
        return None, None

    year_str = str(year_val)
    if "-" not in year_str:
        year = int(year_str)
        return year, year

    parts = year_str.split("-", 1)
    start = int(parts[0]) if parts[0] else None
    end = int(parts[1]) if parts[1] else None
    return start, end


def _build_query(
    doi_val: str,
    issn_val: str,
    author_val: str,
    title_val: str,
    year_start: int | None,
    year_end: int | None,
    freeform_query: str,
):
    """Build PaperQuery from parsed arguments."""
    from linkora.sources.protocol import PaperQuery

    has_structured = any([doi_val, issn_val, author_val, title_val, year_start])

    if has_structured:
        return PaperQuery(
            doi=doi_val,
            issn=issn_val,
            author=author_val,
            title=title_val,
            year_start=year_start,
            year_end=year_end,
        )

    if freeform_query:
        return parse_freeform_query(freeform_query)

    return PaperQuery()


def parse_freeform_query(query_str: str):
    """Parse free-form query string into PaperQuery."""
    from linkora.sources.protocol import PaperQuery

    query_str = query_str.strip()

    # DOI detection
    if re.match(r"^10\.\d{4,}/", query_str):
        return PaperQuery(doi=query_str)

    # arXiv detection
    if re.match(r"^\d{4}\.\d{4,5}$", query_str):
        return PaperQuery(title=query_str)

    # Default: title search
    return PaperQuery(title=query_str)


__all__ = [
    # Matching
    "DefaultDispatcher",
    "match_papers",
    "score_candidate",
    "parse_freeform_query",
    # Types
    "IngestResult",
    # Pipeline
    "ingest",
]
