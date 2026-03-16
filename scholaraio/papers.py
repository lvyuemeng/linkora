"""
papers.py — ScholarAIO paper directory utilities

Single source for paper storage, caching, and audit.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Callable

from scholaraio.log import get_logger
from scholaraio.audit import Issue, YearRange, DEFAULT_RULES

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
        rules = rules or DEFAULT_RULES
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
    return int(max((v for v in cc.values() if isinstance(v, (int, float))), default=0))


def parse_year_range(year: str) -> YearRange:
    """Parse year filter: 2023, 2020-2024, 2020-, -2024."""
    year = year.strip()
    if "-" in year:
        start, end = year.split("-", 1)
        return YearRange(int(start) if start else None, int(end) if end else None)
    y = int(year)
    return YearRange(y, y)


# =============================================================================
# Backward-Compatible Functions (for legacy imports)
# =============================================================================


def iter_paper_dirs(papers_dir: Path) -> Iterator[Path]:
    """Iterate paper directories (backward compatibility)."""
    store = PaperStore(papers_dir)
    return store.iter_papers()


def read_meta(paper_d: Path) -> dict:
    """Read meta.json (backward compatibility)."""
    papers_dir = paper_d.parent.parent
    store = PaperStore(papers_dir)
    return store.read_meta(paper_d)


def write_meta(paper_d: Path, data: dict) -> None:
    """Write meta.json (backward compatibility)."""
    papers_dir = paper_d.parent.parent
    store = PaperStore(papers_dir)
    return store.write_meta(paper_d, data)