"""
papers.py — ScholarAIO paper directory utilities

Single source for paper storage, caching, and audit.
"""

from __future__ import annotations

import json
import re
import uuid
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Callable

from scholaraio.log import get_logger
from scholaraio.audit import Issue, YearRange

_log = get_logger(__name__)

# ============================================================================
#  Data Structures (from ingest/metadata/_models.py)
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
#  Utilities
# ============================================================================


# Last name extraction patterns
_LASTNAME_PREFIX_RE = re.compile(
    r"^(?:Prof|Prof\.|Dr|Dr\.|Mr|Mr\.|Mrs|Mrs\.|Ms|Ms\.)\s+",
    re.IGNORECASE,
)
_LASTNAME_JP_RE = re.compile(r"^[\u3040-\u309f\u30a0-\u30ff]+")  # Hiragana/Katakana
_LASTNAME_CN_RE = re.compile(r"^[\u4e00-\u9fff]+")  # CJK


def _extract_lastname(full_name: str) -> str:
    """Extract last name (surname) from full author name.

    Handles:
    - Western: "John Smith" -> "Smith"
    - Western with prefix: "Prof. John Smith" -> "Smith"
    - Chinese: "Smith John" (given, family) -> "Smith" (assumes Western order)
    - Japanese: "山田" (family only) -> "山田"
    - Chinese: "张 三" -> "张"

    Args:
        full_name: Full author name.

    Returns:
        Last name (surname).
    """
    if not full_name:
        return ""

    # Remove common prefixes
    name = _LASTNAME_PREFIX_RE.sub("", full_name).strip()
    if not name:
        return ""

    # Check for CJK names
    # Japanese: hiragana/katakana only = family name (usually)
    if _LASTNAME_JP_RE.match(name):
        return name

    # Chinese: first CJK block is family name
    m = _LASTNAME_CN_RE.match(name)
    if m:
        return m.group(0)

    # Western: last word is last name
    parts = name.split()
    if len(parts) == 1:
        return parts[0]

    # Common "Family Given" order (most Western): last part
    # But some Chinese Western-order names: "John Smith" -> "Smith"
    # Heuristic: if last name looks like Western surname (capitalized, no CJK)
    last = parts[-1]
    if last and last[0].isupper():
        return last

    return parts[0] if parts else ""





@dataclass
class PaperStore:
    """Paper storage with in-memory caching.

    Provides unified interface for paper operations:
    - Cached read/write of meta.json and paper.md
    - Audit with configurable rules
    - Lazy iteration
    """

    papers_dir: Path
    _meta_cache: dict[Path, dict] = field(default_factory=dict, repr=False)
    _md_cache: dict[Path, str] = field(default_factory=dict, repr=False)

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
        if not self.papers_dir.exists():
            return
        for d in sorted(self.papers_dir.iterdir()):
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

    # --- Audit Pipeline ---

    def audit(
        self,
        *,
        rules: list[Callable[[Path, dict], list[Issue]]] | None = None,
    ) -> list[Issue]:
        """Run audit pipeline on all papers.

        Args:
            rules: Custom rule functions. If None, uses default rules.

        Returns:
            Issues sorted by severity.
        """
        rules = rules or _default_rules
        issues: list[Issue] = []
        doi_map: dict[str, list[str]] = {}

        for pdir in self.iter_papers():
            pid = pdir.name

            # Load data (use cache)
            try:
                data = self.read_meta(pdir)
            except Exception as e:
                issues.append(
                    Issue(pid, "error", "invalid_json", f"JSON parse failed: {e}")
                )
                continue

            # Run all rules
            for rule in rules:
                issues.extend(rule(pdir, data))

            # DOI tracking for duplicate check
            doi = (data.get("doi") or "").strip().lower()
            if doi:
                doi_map.setdefault(doi, []).append(pid)

        # DOI duplicates
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

        # Sort: error > warning > info
        severity_order = {"error": 0, "warning": 1, "info": 2}
        issues.sort(key=lambda x: (severity_order.get(x.severity, 9), x.paper_id))
        return issues


def _rule_missing_fields(store: PaperStore, pdir: Path, data: dict) -> list[Issue]:
    """Check missing required fields."""
    pid = pdir.name
    required = ["doi", "abstract", "year", "authors", "journal", "title"]
    issues = []
    for field_name in required:
        if not data.get(field_name):
            severity = "error" if field_name == "title" else "warning"
            issues.append(
                Issue(pid, severity, f"missing_{field_name}", f"Missing {field_name}")
            )
    return issues


def _rule_file_pairing(store: PaperStore, pdir: Path, data: dict) -> list[Issue]:
    """Check meta.json / paper.md pairing."""
    pid = pdir.name
    issues = []
    md_file = pdir / "paper.md"
    if not md_file.exists():
        return [Issue(pid, "error", "missing_md", "Missing paper.md")]

    # Check content length
    content = store.read_md(pdir)
    if content and len(content.strip()) < 200:
        issues.append(
            Issue(
                pid,
                "warning",
                "short_md",
                f"paper.md too short ({len(content.strip())} chars)",
            )
        )
    return issues


def _rule_title_match(store: PaperStore, pdir: Path, data: dict) -> list[Issue]:
    """Check JSON title vs MD H1 consistency."""
    pid = pdir.name
    json_title = (data.get("title") or "").strip().lower()
    if not json_title:
        return []

    content = store.read_md(pdir)
    if not content:
        return []

    h1_match = re.search(r"^#\s+(.+)", content, re.MULTILINE)
    if not h1_match:
        return []

    md_title = h1_match.group(1).strip().lower()
    json_words = set(re.findall(r"\w{4,}", json_title))
    md_words = set(re.findall(r"\w{4,}", md_title))
    if json_words and md_words:
        overlap = len(json_words & md_words) / max(len(json_words), 1)
        if overlap < 0.3:
            return [Issue(pid, "warning", "title_mismatch", "JSON vs MD H1 mismatch")]
    return []


def _rule_filename_format(store: PaperStore, pdir: Path, data: dict) -> list[Issue]:
    """Check directory name format."""
    pid = pdir.name
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


_default_rules = [
    _rule_missing_fields,
    _rule_file_pairing,
    _rule_title_match,
    _rule_filename_format,
]


# =============================================================================
#  Path Helpers
# =============================================================================


def paper_dir(papers_dir: Path, dir_name: str) -> Path:
    return papers_dir / dir_name


def meta_path(papers_dir: Path, dir_name: str) -> Path:
    return papers_dir / dir_name / "meta.json"


def md_path(papers_dir: Path, dir_name: str) -> Path:
    return papers_dir / dir_name / "paper.md"


def generate_uuid() -> str:
    return str(uuid.uuid4())


def best_citation(meta: dict) -> int:
    cc = meta.get("citation_count")
    if not cc or not isinstance(cc, dict):
        return 0
    return max((v for v in cc.values() if isinstance(v, (int, float))), default=0)


def parse_year_range(year: str) -> YearRange:
    """Parse year filter: 2023, 2020-2024, 2020-, -2024."""
    year = year.strip()
    if "-" in year:
        start, end = year.split("-", 1)
        return YearRange(int(start) if start else None, int(end) if end else None)
    y = int(year)
    return YearRange(y, y)


# =============================================================================
#  Filter Helpers
# =============================================================================





# =============================================================================
#  Deprecated Functions (Use PaperStore Instead)
# =============================================================================


def iter_paper_dirs(papers_dir: Path) -> Iterator[Path]:
    """Iterate paper directories with meta.json.

    DEPRECATED: Use PaperStore(papers_dir).iter_papers() instead.
    """
    warnings.warn(
        "iter_paper_dirs is deprecated. Use PaperStore(papers_dir).iter_papers() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    if not papers_dir.exists():
        return
    for d in sorted(papers_dir.iterdir()):
        if d.is_dir() and (d / "meta.json").exists():
            yield d


def read_meta(paper_d: Path) -> dict:
    """Read meta.json (standalone function).

    DEPRECATED: Use PaperStore(papers_dir).read_meta(paper_d) instead.
    """
    warnings.warn(
        "read_meta is deprecated. Use PaperStore(papers_dir).read_meta(paper_d) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    p = paper_d / "meta.json"
    return json.loads(p.read_text(encoding="utf-8"))
