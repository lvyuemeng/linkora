"""sources/endnote.py — Parse Endnote XML and RIS files.

Redesigned with PaperSource Protocol - unified search() + fetch_by_id() API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from linkora.log import get_logger
from linkora.sources.protocol import PaperCandidate, PaperQuery, matches_query

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


def _record_to_candidate(record: dict, source_file: str) -> PaperCandidate:
    """Convert Endnote record to PaperCandidate."""
    # Parse authors
    raw_authors = record.get("authors", "")
    authors_raw = (
        [a.strip() for a in raw_authors.split("; ") if a.strip()] if raw_authors else []
    )
    authors = [_normalize_author_name(a) for a in authors_raw]

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
    if ref_type in JOURNAL_REF_TYPES:
        # ISSN is in isbn field for journals in some formats
        pass

    doi = _clean_doi(record.get("doi", ""))
    paper_id = doi or record.get("title", "")

    return PaperCandidate(
        id=paper_id,
        doi=doi,
        title=record.get("title", ""),
        authors=authors,
        year=year,
        journal=record.get("journal") or None,
        abstract=record.get("abstract") or None,
        cited_by_count=0,
        paper_type=paper_type,
        pdf_url=None,
        source="endnote",
        source_id=None,
    )


# ============================================================================
#  EndnoteSource class (PaperSource Protocol)
# ============================================================================


@dataclass
class EndnoteSource:
    """Parse Endnote XML/RIS files as paper source.

    Implements PaperSource Protocol for unified access to Endnote exports.

    Note: Endnote source is file-based, so paths must be provided.
    The source stores paths internally for search operations.

    Example:
        source = EndnoteSource(paths=[Path("export.xml"), Path("export.ris")])
        for paper in source.search(query):
            print(paper.title)

        # Or fetch by ID
        paper = source.fetch_by_id("10.1234/example")
    """

    paths: list[Path] = field(default_factory=list)
    _cache: list[PaperCandidate] = field(default_factory=list, init=False, repr=False)

    @property
    def name(self) -> str:
        return "endnote"

    def _load_cache(self) -> None:
        """Load all papers from files into cache."""
        if self._cache:
            return

        for path in self.paths:
            self._load_file(path)

    def _load_file(self, path: Path) -> None:
        """Load a single Endnote file into cache."""
        if not path.exists():
            _log.warning("Endnote file not found: %s", path)
            return

        suffix = path.suffix.lower()
        source_file = path.name

        if suffix == ".xml":
            self._load_xml(path, source_file)
        elif suffix == ".ris":
            self._load_ris(path, source_file)
        else:
            _log.warning("Unsupported file format, skipping: %s", path)

    def _load_xml(self, path: Path, source_file: str) -> None:
        """Parse Endnote XML file."""
        try:
            _log.info("Parsing Endnote XML: %s", path)
            for elem in _iter_records_xml(path):
                rec = _process_record_xml(elem, "endnote")
                candidate = _record_to_candidate(rec, source_file)
                self._cache.append(candidate)
        except Exception as e:
            _log.error("Failed to parse %s: %s", path, e)

    def _load_ris(self, path: Path, source_file: str) -> None:
        """Parse Endnote RIS file."""
        try:
            _log.info("Parsing Endnote RIS: %s", path)
            for rec in _iter_records_ris(path):
                candidate = _record_to_candidate(rec, source_file)
                self._cache.append(candidate)
        except Exception as e:
            _log.error("Failed to parse %s: %s", path, e)

    # === PaperSource Protocol ===

    def search(self, query: PaperQuery) -> Iterator[PaperCandidate]:
        """Search papers matching query.

        Args:
            query: PaperQuery with search criteria

        Yields:
            PaperCandidate instances matching the query
        """
        self._load_cache()

        for candidate in self._cache:
            if matches_query(candidate, query):
                yield candidate

    def fetch_by_id(self, paper_id: str) -> PaperCandidate | None:
        """Fetch paper by DOI or title.

        Args:
            paper_id: DOI or title

        Returns:
            PaperCandidate if found, None otherwise
        """
        self._load_cache()

        for candidate in self._cache:
            if candidate.doi and paper_id.lower() in candidate.doi.lower():
                return candidate
            if candidate.title and paper_id.lower() in candidate.title.lower():
                return candidate

        return None


# ============================================================================
#  Inline implementations (avoid external dependency issues)
# ============================================================================


def _iter_records_xml(path: Path):
    """Iterate records from Endnote XML file."""
    try:
        import xml.etree.ElementTree as ET

        tree = ET.parse(path)
        root = tree.getroot()

        # Find all records
        for elem in root.iter():
            if elem.tag.endswith("record"):
                yield elem
    except ImportError:
        # Fallback: try endnote_utils
        try:
            from endnote_utils.core import iter_records_xml as _iter

            yield from _iter(path)
        except ImportError:
            _log.error("endnote-utils not installed")
            return


def _process_record_xml(elem, ref_type: str):
    """Process XML element to record dict."""
    try:
        from endnote_utils.core import process_record_xml as _process

        return _process(elem, ref_type)
    except ImportError:
        # Manual parsing fallback
        record = {}
        for child in elem:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            record[tag] = child.text or ""
        return record


def _iter_records_ris(path: Path):
    """Iterate records from RIS file."""
    try:
        from endnote_utils.core import iter_records_ris as _iter

        yield from _iter(path)
    except ImportError:
        # Manual parsing fallback
        record = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    if record:
                        yield record
                        record = {}
                    continue
                if line.startswith("TY  -"):
                    record["ref_type"] = line[5:].strip()
                elif line.startswith("ER  -"):
                    if record:
                        yield record
                        record = {}
                elif "  -" in line:
                    tag, value = line.split("-", 1)
                    record[tag.strip()] = value.strip()
        if record:
            yield record
