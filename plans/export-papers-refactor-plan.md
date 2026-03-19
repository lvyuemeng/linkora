# Export & Papers Refactoring Plan

> Refactor to merge filters.py into papers.py, export into PaperStore, use context injection.
> Based on AGENT.md philosophy.

---

## 1. Issues Identified

### 1.1 papers.py - Redundant Path Helpers + Need Filters

| Location | Current | Issue |
|----------|---------|-------|
| Lines 233-242 | Standalone functions | Redundant with PaperStore methods |
| Missing | PaperFilter | Need from filters.py |

### 1.2 filters.py - Should Merge into papers.py

Per user request: **Merge filters.py into papers.py**

### 1.3 export.py - Should Merge into PaperStore

Per feedback: **Remove export module**, merge into PaperStore

### 1.4 config.py - Type Error

| Location | Issue |
|----------|-------|
| Line 291-312 | `resolve()` returns different types but annotated as `dict` |

---

## 2. Refactoring Plan

### Phase 1: Fix config.py Type Error

Use separate typed sub-functions:

```python
# linkora/config.py - Fix using separate typed sub-functions

def _resolve_string(value: str, env: dict[str, str]) -> str:
    """Resolve environment variables in a string."""
    pattern = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")
    def replacer(match):
        var_name = match.group(1)
        fallback = match.group(2)
        return env.get(var_name) or os.environ.get(var_name, "") or fallback or ""
    return pattern.sub(replacer, value)


def _resolve_dict(data: dict, env: dict[str, str]) -> dict:
    """Resolve environment variables in a dict."""
    return {k: _resolve_value(v, env) for k, v in data.items()}


def _resolve_list(items: list, env: dict[str, str]) -> list:
    """Resolve environment variables in a list."""
    return [_resolve_value(item, env) for item in items]


def _resolve_value(obj: str | dict | list, env: dict[str, str]) -> str | dict | list:
    """Resolve environment variables in any value."""
    if isinstance(obj, str):
        return _resolve_string(obj, env)
    if isinstance(obj, dict):
        return _resolve_dict(obj, env)
    if isinstance(obj, list):
        return _resolve_list(obj, env)
    return obj


def _resolve_env_vars(data: dict, env: dict[str, str]) -> dict:
    """Resolve ${VAR} and ${VAR:-fallback} in data."""
    return _resolve_dict(data, env)
```

### Phase 2: Merge filters.py into papers.py

Combine `PaperFilter` Protocol and `PaperFilterParams` from filters.py into papers.py:

```python
# linkora/papers.py - Combined with filters

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Callable, Protocol

from linkora.log import get_logger
from linkora.audit import Issue, YearRange, DEFAULT_RULES

_log = get_logger(__name__)


# ============================================================================
#  Data Structures
# ============================================================================


@dataclass
class PaperMetadata:
    """Paper metadata - complete record of academic paper."""
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
#  Filter Protocol & Parameters (merged from filters.py)
# ============================================================================


class PaperFilter(Protocol):
    """Protocol for paper filters."""

    def matches(self, meta: dict) -> bool:
        """Check if paper metadata matches filter."""
        ...


@dataclass(frozen=True)
class PaperFilterParams:
    """Immutable filter parameters for paper selection."""

    year: str | None = None
    journal: str | None = None
    paper_type: str | None = None
    author: str | None = None

    def matches(self, meta: dict) -> bool:
        """Check if paper metadata matches filter."""
        # Year filter (from filters.py)
        if self.year:
            if self.year.startswith(">"):
                min_year = int(self.year[1:])
                py = meta.get("year")
                if not isinstance(py, int) or py <= min_year:
                    return False
            elif self.year.startswith("<"):
                max_year = int(self.year[1:])
                py = meta.get("year")
                if not isinstance(py, int) or py >= max_year:
                    return False
            elif "-" in self.year:
                parts = self.year.split("-")
                if len(parts) == 2:
                    start, end = int(parts[0]), int(parts[1])
                    py = meta.get("year")
                    if not isinstance(py, int) or not (start <= py <= end):
                        return False
            else:
                target_year = int(self.year)
                py = meta.get("year")
                if not isinstance(py, int) or py != target_year:
                    return False

        # Journal filter
        if self.journal:
            journal = meta.get("journal")
            if not journal or not isinstance(journal, str):
                return False
            if self.journal.lower() not in journal.lower():
                return False

        # Paper type filter
        if self.paper_type:
            ptype = meta.get("paper_type")
            if not ptype or not isinstance(ptype, str):
                return False
            if self.paper_type.lower() != ptype.lower():
                return False

        # Author filter
        if self.author:
            authors = meta.get("authors")
            if not authors or not isinstance(authors, list):
                return False
            author_lower = self.author.lower()
            if not any(
                isinstance(a, str) and author_lower in a.lower() for a in authors
            ):
                return False

        return True


# ============================================================================
#  PaperStore
# ============================================================================


class PaperStore:
    """Paper storage with in-memory caching.

    Provides unified interface for paper operations:
    - Cached read/write of meta.json and paper.md
    - Audit with configurable rules
    - Lazy iteration with filters
    - Export to BibTeX
    """

    _papers_dir: Path  # Private - use papers_dir property
    _meta_cache: dict[Path, dict] = field(default_factory=dict, repr=False)
    _md_cache: dict[Path, str] = field(default_factory=dict, repr=False)

    def __init__(self, papers_dir: Path) -> None:
        self._papers_dir = papers_dir.resolve()

    @property
    def papers_dir(self) -> Path:
        """Get papers directory (read-only)."""
        return self._papers_dir

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

    # --- Selection with Filters ---

    def select(
        self,
        filter: PaperFilterParams | None = None,
    ) -> Iterator[tuple[Path, dict]]:
        """Efficiently select papers with filter.

        Uses lazy iteration with early filtering.
        """
        filter = filter or PaperFilterParams()
        for pdir in self.iter_papers():
            meta = self.read_meta(pdir)
            if filter.matches(meta):
                yield pdir, meta

    def select_meta(self, filter: PaperFilterParams | None = None) -> Iterator[dict]:
        """Select papers and yield metadata only."""
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
            fields.append(("author", self._bibtex_escape(" and ".join(meta["authors"]))))
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
            fields.append(("abstract", "{" + self._bibtex_escape(meta["abstract"]) + "}"))

        lines = [f"@{entry_type}{{{key},"]
        for name, val in fields:
            lines.append(f"  {name} = {{{val}}},")
        lines.append("}")
        return "\n".join(lines)

    def export_bibtex(
        self,
        filter: PaperFilterParams | None = None,
    ) -> str:
        """Export papers to BibTeX format.

        Args:
            filter: PaperFilterParams for selection. None = all papers.

        Returns:
            Complete BibTeX string.
        """
        entries = [self.meta_to_bibtex(meta) for meta in self.select_meta(filter)]
        return "\n\n".join(entries) + "\n" if entries else ""

    # --- Audit Pipeline ---

    def audit(
        self,
        *,
        rules: list[Callable[[Path, dict], list[Issue]]] | None = None,
    ) -> list[Issue]:
        """Run audit pipeline on all papers."""
        rules = rules or DEFAULT_RULES
        issues: list[Issue] = []
        doi_map: dict[str, list[str]] = {}

        for pdir in self.iter_papers():
            pid = pdir.name
            try:
                data = self.read_meta(pdir)
            except Exception as e:
                issues.append(
                    Issue(pid, "error", "invalid_json", f"JSON parse failed: {e}")
                )
                continue

            for rule in rules:
                issues.extend(rule(pdir, data))

            doi = (data.get("doi") or "").strip().lower()
            if doi:
                doi_map.setdefault(doi, []).append(pid)

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

        severity_order = {"error": 0, "warning": 1, "info": 2}
        issues.sort(key=lambda x: (severity_order.get(x.severity, 9), x.paper_id))
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
    "PaperFilter",
    "PaperFilterParams",
    "Issue",
    "YearRange",
    "generate_uuid",
    "best_citation",
    "parse_year_range",
]
```

### Phase 3: Remove Redundant Code

1. **Delete `linkora/filters.py`** - merged into papers.py
2. **Delete `linkora/export.py`** - merged into PaperStore

### Phase 4: CLI with Context Injection

```python
# linkora/cli/context.py - Add paper_store method

from dataclasses import dataclass, field
from pathlib import Path

from linkora.papers import PaperStore


@dataclass
class AppContext:
    """Application context with lazy initialization."""
    config: "Config"
    _http_client: Any = field(default=None, repr=False)
    _llm_runner: Any = field(default=None, repr=False)
    _paper_store: PaperStore | None = field(default=None, repr=False)

    def paper_store(self) -> PaperStore:
        """Get or create PaperStore with context injection."""
        if self._paper_store is None:
            self._paper_store = PaperStore(self.config.papers_dir)
        return self._paper_store

    def close(self) -> None:
        """Close all resources."""
        self._http_client = None
        self._llm_runner = None
        self._paper_store = None
```

```python
# linkora/cli/commands.py - Export command with context injection

def cmd_export(args, ctx) -> None:
    """Export papers to BibTeX format."""
    store = ctx.paper_store()

    # Create filter from args
    filter = PaperFilterParams(
        year=getattr(args, "year", None),
        journal=getattr(args, "journal", None),
        paper_type=getattr(args, "type", None),
        author=getattr(args, "author", None),
    )

    bibtex = store.export_bibtex(filter)

    output_path: str | None = getattr(args, "output", None)
    if output_path:
        Path(output_path).write_text(bibtex, encoding="utf-8")
        ui(f"Exported to {output_path}")
    else:
        print(bibtex)
```

---

## 3. Implementation Order

```
1. Fix config.py type error
2. Merge filters.py into papers.py
3. Add export methods to PaperStore
4. Remove redundant path helper functions from papers.py
5. Delete export.py (merged into PaperStore)
6. Delete filters.py (merged into papers.py)
7. Update CLI context to use paper_store()
8. Update CLI commands to use context injection
9. Run ruff format and check
10. Test export functionality
```

---

## 4. Files to Modify/Delete

| File | Action |
|------|--------|
| `linkora/config.py` | Fix type with separate typed sub-functions |
| `linkora/papers.py` | Merge PaperFilter, PaperFilterParams from filters.py; add export methods |
| `linkora/filters.py` | **DELETE** - merged into papers.py |
| `linkora/export.py` | **DELETE** - merged into PaperStore |
| `linkora/cli/context.py` | Add paper_store() method |
| `linkora/cli/commands.py` | Update to use context injection |

---

## 5. Key Design Points (AGENT.md Compliant)

1. **Merge filters.py into papers.py** - Single source of truth
2. **No exposed papers_dir** - Private `_papers_dir` with read-only property
3. **Context injection** - CLI uses `ctx.paper_store()` instead of direct instantiation
4. **Efficient selection** - Lazy iteration with early filtering
5. **Merge export into PaperStore** - Single source of truth
6. **English-only comments** - Code comments in English

---

## 6. Verification

```bash
# Run type check
uv run ty check linkora/config.py
uv run ty check linkora/papers.py

# Run format
uv run ruff format linkora/config.py
uv run ruff format linkora/papers.py

# Run check
uv run ruff check linkora/config.py
uv run ruff check linkora/papers.py
```
