"""sources/endnote.py — Parse Endnote XML and RIS files.

Refactored to use EndnoteSource class with PaperSource Protocol.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from endnote_utils.core import (
    iter_records_ris,
    iter_records_xml,
    process_record_xml,
)

from scholaraio.papers import _extract_lastname
from scholaraio.log import get_logger

_log = get_logger(__name__)

# ref_type string → Crossref-style paper_type
REF_TYPE_MAP: dict[str, str] = {
    "Journal Article": "journal-article",
    "Conference Paper": "conference-paper",
    "Conference Proceedings": "conference-paper",
    "Book": "book",
    "Book Section": "book-chapter",
    "Thesis": "thesis",
    "Report": "report",
    "Generic": "",
}

JOURNAL_REF_TYPES = {"Journal Article", "Conference Paper", "Conference Proceedings"}

DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)


# ============================================================================
#  Internal helpers
# ============================================================================


def _normalize_author_name(name: str) -> str:
    """Convert "Last, First" to "First Last"."""
    if "," in name:
        parts = name.split(",", 1)
        return f"{parts[1].strip()} {parts[0].strip()}"
    return name


def _clean_doi(raw: str) -> str:
    """Strip URL prefix from DOI."""
    if not raw:
        return ""
    return DOI_PREFIX_RE.sub("", raw).strip()


def _record_to_dict(record: dict, source_file: str) -> dict:
    """Convert Endnote record to standardized dict."""
    # Parse authors
    raw_authors = record.get("authors", "")
    authors_raw = (
        [a.strip() for a in raw_authors.split("; ") if a.strip()] if raw_authors else []
    )
    authors = [_normalize_author_name(a) for a in authors_raw]

    first_author = authors[0] if authors else ""
    first_author_lastname = _extract_lastname(first_author) if first_author else ""

    # Parse year
    year_str = record.get("year", "")
    year: int | None = None
    if year_str:
        try:
            year = int(year_str)
        except ValueError:
            _log.debug("Failed to parse year: %r", year_str)

    # Parse paper type
    ref_type = record.get("ref_type", "")
    paper_type = REF_TYPE_MAP.get(ref_type, ref_type.lower().replace(" ", "-"))

    # Parse ISSN
    issn = ""
    if ref_type in JOURNAL_REF_TYPES:
        issn = record.get("isbn", "")

    return {
        "id": _clean_doi(record.get("doi", "")) or record.get("title", ""),
        "title": record.get("title", ""),
        "authors": authors,
        "first_author": first_author,
        "first_author_lastname": first_author_lastname,
        "year": year,
        "doi": _clean_doi(record.get("doi", "")),
        "journal": record.get("journal", ""),
        "abstract": record.get("abstract", ""),
        "paper_type": paper_type,
        "volume": record.get("volume", ""),
        "issue": record.get("number", ""),
        "pages": record.get("pages", ""),
        "publisher": record.get("publisher", ""),
        "issn": issn,
        "source_file": source_file,
        "extraction_method": "endnote",
    }


# ============================================================================
#  EndnoteSource class (PaperSource Protocol)
# ============================================================================


@dataclass(frozen=True)
class EndnoteSource:
    """Parse Endnote XML/RIS files as paper source.

    Implements PaperSource Protocol for unified access to Endnote exports.

    Example:
        source = EndnoteSource()
        for paper in source.fetch(paths=[Path("export.xml")]):
            print(paper["title"])
    """

    @property
    def name(self) -> str:
        return "endnote"

    def fetch(self, paths: list[Path] | None = None, **kwargs) -> Iterator[dict]:
        """Fetch papers from Endnote XML/RIS files."""
        if not paths:
            return

        for path in paths:
            suffix = path.suffix.lower()
            source_file = path.name

            if suffix == ".xml":
                _log.info("Parsing Endnote XML: %s", path)
                for elem in iter_records_xml(path):
                    rec = process_record_xml(elem, "endnote")
                    yield _record_to_dict(rec, source_file)

            elif suffix == ".ris":
                _log.info("Parsing Endnote RIS: %s", path)
                for rec in iter_records_ris(path):
                    yield _record_to_dict(rec, source_file)

            else:
                _log.warning("Unsupported file format, skipping: %s", path)

    def count(self, paths: list[Path] | None = None, **kwargs) -> int:
        """Count papers in Endnote files."""
        if not paths:
            return 0
        return sum(1 for _ in self.fetch(paths=paths))
