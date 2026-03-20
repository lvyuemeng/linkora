"""
papers.py — linkora paper directory utilities

Single source for paper storage, caching, audit, filtering, and export.
Uses elegant data pipe flow with PaperFilterParams.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Callable, Protocol

from linkora.log import get_logger
from linkora.filters import QueryFilter

_log = get_logger(__name__)

# ============================================================================
#  Data Structures
# ============================================================================


@dataclass
class PaperMetadata:
    """Paper metadata - complete record of academic paper.

    Attributes:
        id: UUID, assigned at ingest time, never changes.
        title: Paper title.
        authors: Author list.
        first_author: First author full name.
        first_author_lastname: First author last name (for filename).
        year: Publication year.
        doi: DOI identifier (without https://doi.org/ prefix).
        journal: Journal or conference name.
        abstract: Abstract text.
        paper_type: Paper type (article, review, conference-paper, etc.).
        citation_count_s2: Semantic Scholar citation count.
        citation_count_openalex: OpenAlex citation count.
        citation_count_crossref: Crossref citation count.
        s2_paper_id: Semantic Scholar paper ID.
        openalex_id: OpenAlex paper ID.
        crossref_doi: Crossref returned DOI.
        api_sources: List of APIs that returned data.
        references: Reference DOI list (from Semantic Scholar).
        source_file: Original filename.
        extraction_method: Extraction method (doi_lookup, title_search, etc.).
    """

    id: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    first_author: str = ""
    first_author_lastname: str = ""
    year: int | None = None
    doi: str = ""
    journal: str = ""
    abstract: str = ""
    paper_type: str = ""
    citation_count_s2: int | None = None
    citation_count_openalex: int | None = None
    citation_count_crossref: int | None = None
    s2_paper_id: str = ""
    openalex_id: str = ""
    crossref_doi: str = ""
    api_sources: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    volume: str = ""
    issue: str = ""
    pages: str = ""
    publisher: str = ""
    issn: str = ""
    source_file: str = ""
    extraction_method: str = ""


# ============================================================================
#  Audit Types (merged from audit.py)
# ============================================================================


@dataclass(frozen=True)
class Issue:
    """Audit issue report - immutable."""

    paper_id: str
    severity: str  # "error" | "warning" | "info"
    rule: str
    message: str


class YearRange(tuple):
    """Year filter range: (start, end) with None for unbounded."""

    __slots__ = ()

    def __new__(cls, start: int | None, end: int | None) -> "YearRange":
        return super().__new__(cls, (start, end))

    @property
    def start(self) -> int | None:
        return self[0]

    @property
    def end(self) -> int | None:
        return self[1]


# ============================================================================
#  Filter Protocol & Parameters
# ============================================================================


class PaperFilter(Protocol):
    """Protocol for paper filters."""

    def matches(self, meta: dict) -> bool:
        """Check if paper metadata matches filter."""
        ...


# QueryFilter has: year, journal, paper_type, author fields
# and matches() method with flattened implementation


# ============================================================================
#  Audit Rules (merged from audit.py)
# ============================================================================


def _rule_missing_fields(paper_d: Path, data: dict) -> list[Issue]:
    """Check missing required fields."""
    pid = paper_d.name
    required = ["doi", "abstract", "year", "authors", "journal", "title"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        issues = []
        for field_name in missing:
            severity = "error" if field_name == "title" else "warning"
            issues.append(
                Issue(pid, severity, f"missing_{field_name}", f"Missing {field_name}")
            )
        return issues
    return []


def _rule_file_pairing(paper_d: Path, data: dict) -> list[Issue]:
    """Check meta.json / paper.md pairing."""
    pid = paper_d.name
    md_path = paper_d / "paper.md"
    if not md_path.exists():
        return [
            Issue(pid, "error", "missing_md", "meta.json exists but paper.md missing")
        ]

    # Check content length
    try:
        content = md_path.read_text(encoding="utf-8", errors="replace")
        if content and len(content.strip()) < 200:
            return [
                Issue(
                    pid,
                    "warning",
                    "short_md",
                    f"paper.md too short ({len(content.strip())} chars)",
                )
            ]
    except Exception:
        pass
    return []


def _rule_title_match(paper_d: Path, data: dict) -> list[Issue]:
    """Check JSON title vs MD H1 consistency."""
    pid = paper_d.name
    md_path = paper_d / "paper.md"

    if not md_path.exists():
        return []

    md_content = md_path.read_text(encoding="utf-8", errors="replace")
    h1_match = re.search(r"^#\s+(.+)$", md_content, re.MULTILINE)
    if not h1_match:
        return []

    json_title = data.get("title", "").lower()
    md_title = h1_match.group(1).strip().lower()
    json_words = set(re.findall(r"\w{4,}", json_title))
    md_words = set(re.findall(r"\w{4,}", md_title))
    if json_words and md_words:
        overlap = len(json_words & md_words) / max(len(json_words), 1)
        if overlap < 0.3:
            return [Issue(pid, "warning", "title_mismatch", "JSON vs MD H1 mismatch")]
    return []


def _rule_filename_format(paper_d: Path, data: dict) -> list[Issue]:
    """Check directory name format."""
    pid = paper_d.name
    m = re.match(r"^(.+?)-(\d{4})-(.+)$", pid)
    if not m:
        return [
            Issue(pid, "info", "nonstandard_filename", "Not Author-Year-Title format")
        ]

    file_year = int(m.group(2))
    json_year = data.get("year")
    if json_year and file_year != json_year:
        return [
            Issue(
                pid,
                "warning",
                "filename_year_mismatch",
                f"Dir year {file_year} != JSON year {json_year}",
            )
        ]
    return []


DEFAULT_RULES: list[Callable[[Path, dict], list[Issue]]] = [
    _rule_missing_fields,
    _rule_file_pairing,
    _rule_title_match,
    _rule_filename_format,
]


def format_audit(issues: list[Issue]) -> str:
    """Format audit issues as report."""
    if not issues:
        return "Audit passed, no issues found."

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    lines = [
        f"Audit: {len(errors)} errors, {len(warnings)} warnings, {len(infos)} info\n"
    ]

    if errors:
        lines.extend(["=" * 40, "Errors", "=" * 40])
        for i in errors:
            lines.append(f"  [{i.rule}] {i.paper_id}: {i.message}")

    if warnings:
        lines.extend(["", "-" * 40, "Warnings", "-" * 40])
        for i in warnings:
            lines.append(f"  [{i.rule}] {i.paper_id}: {i.message}")

    if infos:
        lines.extend(["", "-" * 40, "Info", "-" * 40])
        for i in infos:
            lines.append(f"  [{i.rule}] {i.paper_id}: {i.message}")

    return "\n".join(lines)


# ============================================================================
#  PaperStore - Data Pipe Flow Design
# ============================================================================


class PaperStore:
    """Paper storage with in-memory caching.

    Provides unified interface for paper operations:
    - Cached read/write of meta.json and paper.md
    - Audit with configurable rules
    - Lazy iteration with filters (data pipe flow)
    - Export to BibTeX

    Data Pipe Flow Example:
        # Select papers by filter
        for meta in store.select_meta(PaperFilterParams(year=">2020")):
            print(meta.get("title"))

        # Or iterate with paths
        for pdir, meta in store.select(PaperFilterParams(author="Smith")):
            print(pdir.name, meta.get("title"))
    """

    _papers_dir: Path  # Private - use get_paper_dir() method
    _meta_cache: dict[Path, dict] = {}  # Cache for meta.json
    _md_cache: dict[Path, str] = {}  # Cache for paper.md

    def __init__(self, papers_dir: Path) -> None:
        self._papers_dir = papers_dir.resolve()

    # --- Internal Path Resolution ---

    def get_paper_dir(self, dir_name: str) -> Path:
        """Internal: get paper directory path by dir_name.

        Use this instead of accessing papers_dir directly.
        """
        return self._papers_dir / dir_name

    # --- File Operations ---

    def read_meta(self, paper_d: Path) -> dict:
        """Read meta.json (cached)."""
        if paper_d in self._meta_cache:
            return self._meta_cache[paper_d]
        p = paper_d / "meta.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        self._meta_cache[paper_d] = data
        return data

    def write_meta(self, paper_d: Path, data: dict) -> None:
        """Write meta.json atomically (cached)."""
        p = paper_d / "meta.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        tmp.replace(p)
        self._meta_cache[paper_d] = data

    def update_meta(self, paper_d: Path, **fields) -> dict:
        """Update meta fields."""
        data = self.read_meta(paper_d)
        data.update(fields)
        self.write_meta(paper_d, data)
        return data

    def read_md(self, paper_d: Path) -> str | None:
        """Read paper.md (cached)."""
        if paper_d in self._md_cache:
            return self._md_cache[paper_d]
        md_path = paper_d / "paper.md"
        if not md_path.exists():
            return None
        content = md_path.read_text(encoding="utf-8", errors="replace")
        self._md_cache[paper_d] = content
        return content

    def iter_papers(self) -> Iterator[Path]:
        """Iterate papers with meta.json."""
        if not self._papers_dir.exists():
            return
        for d in sorted(self._papers_dir.iterdir()):
            if d.is_dir() and (d / "meta.json").exists():
                yield d

    def invalidate(self, paper_d: Path | None = None) -> None:
        """Clear cache."""
        if paper_d is None:
            self._meta_cache.clear()
            self._md_cache.clear()
        else:
            self._meta_cache.pop(paper_d, None)
            self._md_cache.pop(paper_d, None)

    # --- Data Pipe Flow: Selection with Filters ---

    def select(
        self,
        filter: QueryFilter | None = None,
    ) -> Iterator[tuple[Path, dict]]:
        """Efficiently select papers with filter (data pipe flow).

        Args:
            filter: QueryFilter for selection. None = all papers.

        Yields:
            Tuples of (paper_dir_path, metadata_dict)

        Example:
            for pdir, meta in store.select(QueryFilter(year=">2020")):
                print(pdir.name, meta.get("title"))
        """
        filter = filter or QueryFilter()
        for pdir in self.iter_papers():
            meta = self.read_meta(pdir)
            if filter.matches(meta):
                yield pdir, meta

    def select_meta(self, filter: QueryFilter | None = None) -> Iterator[dict]:
        """Select papers and yield metadata only (data pipe flow).

        Args:
            filter: QueryFilter for selection. None = all papers.

        Yields:
            Paper metadata dictionaries

        Example:
            for meta in store.select_meta(QueryFilter(author="Smith")):
                print(meta.get("title"))
        """
        for _, meta in self.select(filter):
            yield meta

    # --- Export Methods ---

    def _bibtex_escape(self, text: str) -> str:
        """Escape special LaTeX characters."""
        for ch in ("&", "%", "#", "_"):
            text = text.replace(ch, f"\\{ch}")
        return text

    def _make_cite_key(self, meta: dict) -> str:
        """Generate BibTeX citation key."""
        last = meta.get("first_author_lastname") or "Unknown"
        last = re.sub(r"[^a-zA-Z]", "", last)
        year = str(meta.get("year") or "")
        title = meta.get("title") or ""
        word = ""
        for w in title.split():
            cleaned = re.sub(r"[^a-zA-Z]", "", w)
            if len(cleaned) > 3:
                word = cleaned.capitalize()
                break
        return f"{last}{year}{word}"

    def _type_to_bibtex(self, paper_type: str) -> str:
        """Map paper_type to BibTeX entry type."""
        mapping = {
            "journal-article": "article",
            "review": "article",
            "book-chapter": "inbook",
            "book": "book",
            "proceedings-article": "inproceedings",
            "conference-paper": "inproceedings",
            "thesis": "phdthesis",
            "dissertation": "phdthesis",
            "preprint": "misc",
        }
        return mapping.get(paper_type or "", "article")

    def meta_to_bibtex(self, meta: dict) -> str:
        """Convert metadata to BibTeX entry."""
        entry_type = self._type_to_bibtex(meta.get("paper_type") or "")
        key = self._make_cite_key(meta)

        fields: list[tuple[str, str]] = []

        if meta.get("title"):
            fields.append(("title", "{" + self._bibtex_escape(meta["title"]) + "}"))
        if meta.get("authors"):
            fields.append(
                ("author", self._bibtex_escape(" and ".join(meta["authors"])))
            )
        if meta.get("year"):
            fields.append(("year", str(meta["year"])))
        if meta.get("journal"):
            fields.append(("journal", self._bibtex_escape(meta["journal"])))
        if meta.get("volume"):
            fields.append(("volume", meta["volume"]))
        if meta.get("issue"):
            fields.append(("number", meta["issue"]))
        if meta.get("pages"):
            fields.append(("pages", meta["pages"]))
        if meta.get("publisher"):
            fields.append(("publisher", self._bibtex_escape(meta["publisher"])))
        if meta.get("issn"):
            fields.append(("issn", meta["issn"]))
        if meta.get("doi"):
            fields.append(("doi", meta["doi"]))
        if meta.get("abstract"):
            fields.append(
                ("abstract", "{" + self._bibtex_escape(meta["abstract"]) + "}")
            )

        lines = [f"@{entry_type}{{{key},"]
        for name, val in fields:
            lines.append(f"  {name} = {{{val}}},")
        lines.append("}")
        return "\n".join(lines)

    def export_bibtex(
        self,
        filter: QueryFilter | None = None,
    ) -> str:
        """Export papers to BibTeX format.

        Args:
            filter: QueryFilter for selection. None = all papers.

        Returns:
            Complete BibTeX string.
        """
        entries = [self.meta_to_bibtex(meta) for meta in self.select_meta(filter)]
        return "\n\n".join(entries) + "\n" if entries else ""

    # --- Legacy Path Helpers (deprecated, use get_paper_dir) ---

    def paper_dir(self, dir_name: str) -> Path:
        """Deprecated: Use get_paper_dir() instead."""
        return self.get_paper_dir(dir_name)

    def meta_path(self, dir_name: str) -> Path:
        """Deprecated: Use get_paper_dir() / 'meta.json' instead."""
        return self.get_paper_dir(dir_name) / "meta.json"

    def md_path(self, dir_name: str) -> Path:
        """Deprecated: Use get_paper_dir() / 'paper.md' instead."""
        return self.get_paper_dir(dir_name) / "paper.md"

    # --- Audit Pipeline ---

    def audit(
        self,
        *,
        rules: list[Callable[[Path, dict], list[Issue]]] | None = None,
        min_severity: str | None = None,
    ) -> list[Issue]:
        """Run audit pipeline on all papers.

        Args:
            rules: Custom audit rules. None = use DEFAULT_RULES.
            min_severity: Minimum severity to collect ("error", "warning", "info").
                None = collect all. "error" = only errors, "warning" = warnings+errors.

        Returns:
            List of Issue objects sorted by severity.
        """
        rules = rules or DEFAULT_RULES

        # Build severity filter for efficient collection
        severity_levels = {"error": 0, "warning": 1, "info": 2}
        min_level = severity_levels.get(min_severity, -1) if min_severity else -1

        issues: list[Issue] = []
        doi_map: dict[str, list[str]] = {}

        for pdir in self.iter_papers():
            pid = pdir.name
            try:
                data = self.read_meta(pdir)
            except Exception as e:
                if min_level <= 0:  # error level
                    issues.append(
                        Issue(pid, "error", "invalid_json", f"JSON parse failed: {e}")
                    )
                continue

            for rule in rules:
                # Collect issues and filter by severity
                rule_issues = rule(pdir, data)
                for issue in rule_issues:
                    issue_level = severity_levels.get(issue.severity, 9)
                    if issue_level >= min_level:
                        issues.append(issue)

            # Only track DOI for duplicate checking if we might need it
            if min_level <= 0:
                doi = (data.get("doi") or "").strip().lower()
                if doi:
                    doi_map.setdefault(doi, []).append(pid)

        # Check for duplicates (only if collecting errors)
        if min_level <= 0:
            for doi, pids in doi_map.items():
                if len(pids) > 1:
                    for pid in pids:
                        others = [p for p in pids if p != pid]
                        issues.append(
                            Issue(
                                pid,
                                "error",
                                "duplicate_doi",
                                f"DOI: {doi} (also: {', '.join(others)})",
                            )
                        )

        issues.sort(key=lambda x: (severity_levels.get(x.severity, 9), x.paper_id))
        return issues


# ============================================================================
#  Utility Functions
# ============================================================================


def generate_uuid() -> str:
    return str(uuid.uuid4())


def best_citation(meta: dict) -> int:
    cc = meta.get("citation_count")
    if not cc or not isinstance(cc, dict):
        return 0
    return int(max((v for v in cc.values() if isinstance(v, (int, float))), default=0))


def parse_year_range(year: str) -> YearRange:
    """Parse year filter: 2023, 2020-2024, 2020-, -2024."""
    year = year.strip()
    if "-" in year:
        start, end = year.split("-", 1)
        return YearRange(int(start) if start else None, int(end) if end else None)
    y = int(year)
    return YearRange(y, y)


__all__ = [
    "PaperMetadata",
    "PaperStore",
    "QueryFilter",
    "Issue",
    "YearRange",
    "DEFAULT_RULES",
    "format_audit",
    "generate_uuid",
    "best_citation",
    "parse_year_range",
    # Audit rules
    "_rule_missing_fields",
    "_rule_file_pairing",
    "_rule_title_match",
    "_rule_filename_format",
]
