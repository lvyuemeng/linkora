# loader.py Redesign Plan (Single File - Final)

> Refactor `scholaraio/loader.py` into a single efficient file.
> No backward compatibility. Data pipe flow pattern.
> Aligned with `scholaraio/extract.py` patterns.

---

## 1. Issues to Fix

| Issue | Current | Fix |
|-------|---------|-----|
| Old logging | `_log = logging.getLogger(__name__)` | Use `get_logger` from `log.py` |
| TYPE_CHECKING | Lines 31-34 | Import Config directly |
| LLMRunner wrapper | `class LLMRunner` wraps `llm.LLMRunner` | Use directly |
| String dispatch | `if key == "toc"` etc. | Dictionary dispatch with Enum |
| Scattered imports | Inside methods | Move to module level |
| Backward compatibility | `PaperEnricher` alias | REMOVED |

---

## 2. Relationship with extract.py

### 2.1 Layer Separation

| Module | Layer | Extracts | Output |
|--------|-------|----------|--------|
| `extract.py` | L1/L2 | title, authors, year, doi, journal | `PaperMetadata` |
| `loader.py` (this plan) | L3/L4 | TOC, conclusion | JSON / text |

### 2.2 Code Sharing Analysis

| Component | extract.py | loader.py | Action |
|-----------|------------|-----------|--------|
| `PaperStore` | Uses | Uses | OK - shared |
| `LLMRunner` | Uses | Uses | OK - shared |
| `Regex patterns` | Different | Different | OK - separate concerns |
| `PromptTemplate` | Uses from llm.py | Uses from llm.py | OK - shared |
| Data pipe flow | Yes | Should match | Align patterns |
| Immutable types | `ExtractionInput`, `ExtractionOutput` | `MarkdownLines`, `LoadResult` | OK - separate domains |

### 2.3 Alignment with extract.py

The new loader.py design follows the same patterns as extract.py:

```python
# extract.py pattern:
ExtractionInput → extract_regex() → extract_llm() → merge_to_output() → ExtractionOutput

# loader.py new pattern (aligned):
MarkdownLines → extract_headers() → _prepare() → LLM → _parse() → _process() → LoadResult
```

---

## 3. State Leak Analysis

### 3.1 Current Dangers

| Component | Danger | Risk |
|-----------|--------|------|
| `ContentExtractor._HEADER_RE` | None | Safe - compiled regex, immutable |
| `ContentExtractor._REAL_SECTION_RE` | None | Safe - compiled regex, immutable |
| `ContentExtractor._CONCLUSION_KEYWORDS` | None | Safe - compiled regex, immutable |
| `PaperStore._meta_cache` | **HIGH** | Mutable dict - stale data across calls |
| `PaperStore._md_cache` | **HIGH** | Mutable dict - stale data across calls |
| `LLMRunner` | None | Each call is independent |
| `RequestsClient` | Low | Connection pool managed by requests lib |

### 3.2 Data Pipe Flow (Aligned with extract.py)

Current dangerous flow:
```
Input → mutable_cache → extract → mutable_dict → transform → mutable_dict → Output
                         ↓
                      LLM call (external state)
```

Safe flow pattern (matching extract.py):
```
ImmutableInput → Stage1 → ImmutableResult → Stage2 → ImmutableResult → Output
```

**Restrictions:**
1. All intermediate results are frozen dataclasses (like extract.py)
2. No mutable state passed between stages
3. Each stage is a pure function with no side effects
4. Cache must be optional and explicit

---

## 4. New Data Structures (Immutable)

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import FrozenSet


class Strategy(Enum):
    """Extraction strategy keys."""
    TOC = auto()
    CONCLUSION_SELECT = auto()
    CONCLUSION_FALLBACK = auto()
    CONCLUSION_VALIDATE = auto()


@dataclass(frozen=True)
class MarkdownLines:
    """Immutable markdown content."""
    lines: tuple[str, ...]  # tuple for immutability
    source: str              # paper_id for traceability
    
    @classmethod
    def from_str(cls, content: str, source: str) -> "MarkdownLines":
        return cls(lines=tuple(content.splitlines()), source=source)


@dataclass(frozen=True)
class Header:
    """Immutable header entry."""
    line: int
    level: int
    text: str


@dataclass(frozen=True)
class HeaderList:
    """Immutable header collection."""
    headers: tuple[Header, ...]
    source: str
    
    @classmethod
    def from_list(cls, items: list[dict], source: str) -> "HeaderList":
        return cls(
            headers=tuple(Header(i["line"], i["level"], i["text"]) for i in items),
            source=source
        )


@dataclass(frozen=True)
class ExtractionInput:
    """Immutable input for LLM extraction."""
    strategy: Strategy
    prompt_data: str
    timeout: int


@dataclass(frozen=True)
class ExtractionOutput:
    """Immutable output from LLM extraction."""
    raw_response: str
    parsed: dict
    strategy: Strategy
    success: bool
    error: str = ""


@dataclass(frozen=True)
class LoadResult:
    """Immutable result of paper loading."""
    success: bool
    paper_id: str
    content: str | None = None
    method: str = ""
    timestamp: str = ""
    error: str = ""
```

---

## 5. Module Structure (Single File)

```python
"""
loader.py — ScholarAIO Paper Content Loader
==========================================

L1: title/authors/year/journal/doi  ← JSON fields (from meta.json)
L2: abstract                       ← JSON fields
L3: conclusion                     ← JSON fields (enrichment)
L4: full markdown                  ← Read .md file

Data Pipe Flow (aligned with extract.py):
    MarkdownLines → extract_headers → HeaderList
    HeaderList → filter_real_sections → HeaderList
    HeaderList + MarkdownLines → slice_lines → str
    str → prepare_prompt → ExtractionInput
    ExtractionInput → LLM → ExtractionOutput
    ExtractionOutput → process_result → LoadResult

Usage:
    from scholaraio.loader import PaperLoader
    loader = PaperLoader(papers_dir, config)
    result = loader.load_toc(paper_id)
    result = loader.load_conclusion(paper_id)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

from scholaraio.config import Config
from scholaraio.llm import LLMRunner, LLMRequest
from scholaraio.http import RequestsClient
from scholaraio.log import get_logger
from scholaraio.papers import PaperStore

_log = get_logger(__name__)

# ============================================================================
#  Data Structures (Immutable)
# ============================================================================


class Strategy(Enum):
    """Extraction strategy keys."""
    TOC = auto()
    CONCLUSION_SELECT = auto()
    CONCLUSION_FALLBACK = auto()
    CONCLUSION_VALIDATE = auto()


@dataclass(frozen=True)
class MarkdownLines:
    """Immutable markdown content."""
    lines: tuple[str, ...]
    source: str
    
    @classmethod
    def from_str(cls, content: str, source: str) -> "MarkdownLines":
        return cls(lines=tuple(content.splitlines()), source=source)


@dataclass(frozen=True)
class Header:
    """Immutable header entry."""
    line: int
    level: int
    text: str


@dataclass(frozen=True)
class HeaderList:
    """Immutable header collection."""
    headers: tuple[Header, ...]
    source: str
    
    @classmethod
    def from_list(cls, items: list[dict], source: str) -> "HeaderList":
        return cls(
            headers=tuple(Header(i["line"], i["level"], i["text"]) for i in items),
            source=source
        )


@dataclass(frozen=True)
class LoadResult:
    """Immutable result of paper loading."""
    success: bool
    paper_id: str
    content: str | None = None
    method: str = ""
    timestamp: str = ""
    error: str = ""


# ============================================================================
#  Prompt Templates (module-level dict)
# ============================================================================


# Use PromptTemplate from llm.py
from scholaraio.llm import PromptTemplate

_PROMPTS: dict[Strategy, PromptTemplate] = {
    Strategy.TOC: PromptTemplate(
        system="You are an academic paper analyzer.",
        user_template="""The following are ALL lines starting with '#' extracted from an academic paper
markdown file (converted from PDF by MinerU). Some are real section headers;
others are NOISE to discard: author running headers (e.g. '# Smith and others'),
journal name headers (e.g. '# Journal of Fluid Mechanics'), repeated paper titles,
or publisher metadata (e.g. '# ARTICLEINFO', '# AFFILIATIONS', '# Articles You May Be Interested In').

KEEP the following as real headers (they are needed as section boundary markers):
- Numbered/lettered sections and subsections
- Introduction, Abstract, Conclusion, Conclusions, Concluding Remarks, Summary
- References, Bibliography
- Appendix (any variant)
- Post-matter sections: Acknowledgments, Acknowledgements, Funding,
CRediT authorship contribution statement, Declaration of competing interest,
Conflict of interest, Data availability, Author contributions, Author ORCIDs,
Declaration of interests

Assign level: 1=top-level, 2=subsection (e.g. '2.1'), 3=sub-subsection (e.g. '2.1.1').

Headers:
{headers}

Return JSON only:
{{"toc": [{{"line": <N>, "level": <1|2|3>, "title": "<title>"}}, ...]}}"""
    ),
    Strategy.CONCLUSION_SELECT: PromptTemplate(
        system="You are an academic paper analyzer.",
        user_template="""Below are all section headers (with line numbers) from an academic paper markdown file.
Identify the header that marks the START of the conclusion section
(may be named 'Conclusion', 'Conclusions', 'Concluding Remarks', 'Summary', etc.).

{headers}

Return JSON only: {{"line": <line_number>, "header": "<header_text>"}}
If no conclusion section exists, return: {{"line": null, "header": null}}"""
    ),
    Strategy.CONCLUSION_FALLBACK: PromptTemplate(
        system="You are an academic paper analyzer.",
        user_template="""Find the conclusion section in this academic paper (markdown format).
Return the 1-indexed line number where the conclusion STARTS and where it ENDS
(last line before References/Appendix/end of file).

{sample}

Return JSON only: {{"start_line": <N>, "end_line": <N>}}
If no conclusion exists: {{"start_line": null, "end_line": null}}"""
    ),
    Strategy.CONCLUSION_VALIDATE: PromptTemplate(
        system="You are an academic paper analyzer.",
        user_template="""The following text was extracted as the conclusion section of an academic paper.
Your tasks:
1. Check if it contains actual conclusion content (summary of findings, contributions, or future work).
2. If yes, return a CLEANED version:
   - Remove the section header line (e.g. '# 6. Conclusion', '# Concluding Remarks')
   - Remove any in-text running headers
   - Remove everything AFTER the conclusion ends: Acknowledgments, Funding, CRediT, etc.
   - Keep only the actual conclusion/summary paragraphs. Do NOT truncate mid-sentence.
3. If it contains NO conclusion content at all, set conclusion to null.

{text}

Return JSON only: {{"conclusion": "<cleaned text or null>", "reason": "<one sentence>"}}"""
    ),
}


# ============================================================================
#  Stage 1: Markdown Extraction (Pure Functions)
# ============================================================================


# Module-level compiled regex (immutable, safe)
_HEADER_RE = re.compile(r"^(#{1,4})\s+(.+)")
_REAL_SECTION_RE = re.compile(
    r"^(?:"
    r"\d[\d.]*[\s.]|"  # Arabic: 1, 1.1, 2., etc.
    r"[IVX]+[\s.)]|"  # Roman: I., II., IV.
    r"[A-F][\s.)]|"  # Letter: A., B.
    r"(?:abstract|introduction|method|result|discussion|"
    r"conclusion|concluding|summary|reference|bibliography|"
    r"appendix|acknowledge|funding|credit|declaration|"
    r"data\s+avail|author\s+contrib|conflict)\b"
    r")",
    re.IGNORECASE,
)
_CONCLUSION_KEYWORDS = re.compile(
    r"\b(conclusion|conclusions|concluding|summary|closing)\b", re.IGNORECASE
)


def extract_headers(lines: MarkdownLines) -> HeaderList:
    """Extract all # headers (Stage 1a)."""
    headers = []
    for i, line in enumerate(lines.lines, start=1):
        m = _HEADER_RE.match(line.rstrip())
        if m:
            headers.append({"line": i, "level": len(m.group(1)), "text": m.group(2).strip()})
    return HeaderList.from_list(headers, lines.source)


def is_real_section(title: str) -> bool:
    """Check if title is a real section."""
    return bool(_REAL_SECTION_RE.match(title.strip()))


def filter_real_sections(headers: HeaderList) -> HeaderList:
    """Filter to real sections only (Stage 1b)."""
    filtered = [h for h in headers.headers if is_real_section(h.text)]
    return HeaderList(headers=tuple(filtered), source=headers.source)


def find_conclusion_entry(headers: HeaderList) -> Header | None:
    """Find conclusion entry in headers."""
    for h in headers.headers:
        if _CONCLUSION_KEYWORDS.search(h.text):
            return h
    return None


def find_next_section_line(headers: HeaderList, after_line: int) -> int | None:
    """Find next real section after given line."""
    for h in headers.headers:
        if h.line > after_line:
            return h.line - 1
    return None


def slice_lines(lines: MarkdownLines, start: int, end: int | None = None) -> str:
    """Slice lines by 1-indexed inclusive range (Stage 1c)."""
    s = max(0, start - 1)
    e = end if end is not None else len(lines.lines)
    return "\n".join(lines.lines[s:e]).strip()


def sample_lines(lines: MarkdownLines, head: int = 100, tail: int = 200) -> str:
    """Sample lines for fallback (Stage 1d)."""
    n = len(lines.lines)
    if n <= head + tail:
        return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines.lines))
    head_str = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines.lines[:head]))
    tail_start = max(head, n - tail)
    tail_str = "\n".join(f"{tail_start + i + 1}: {line}" for i, line in enumerate(lines.lines[tail_start:]))
    return f"[Lines 1–{head}]\n{head_str}\n\n...[middle]...\n\n[Lines {tail_start + 1}–{n}]\n{tail_str}"


# ============================================================================
#  Stage 2: Pipeline Functions (Dictionary Dispatch)
# ============================================================================


def _prepare(strategy: Strategy, lines: MarkdownLines, meta: dict) -> str:
    """Prepare prompt data by strategy (Stage 2a)."""
    if strategy in (Strategy.TOC, Strategy.CONCLUSION_SELECT):
        headers = extract_headers(lines)
        return "\n".join(f"Line {h.line}: {'#' * h.level} {h.text}" for h in headers.headers)
    elif strategy == Strategy.CONCLUSION_FALLBACK:
        return sample_lines(lines)
    elif strategy == Strategy.CONCLUSION_VALIDATE:
        return meta.get("_text_to_validate", "")
    return ""


def _parse(strategy: Strategy, raw: str) -> dict:
    """Parse LLM response by strategy (Stage 2b)."""
    text = raw.strip()
    text = re.sub(r"^```\w*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return {}


def _process(strategy: Strategy, parsed: dict, lines: MarkdownLines) -> str | None:
    """Process parsed result by strategy (Stage 2c)."""
    if strategy == Strategy.TOC:
        toc = parsed.get("toc", [])
        return json.dumps(toc) if toc else None
    elif strategy == Strategy.CONCLUSION_SELECT:
        start_line = parsed.get("line")
        if not start_line:
            return None
        headers = extract_headers(lines)
        end_line = find_next_section_line(headers, start_line)
        return slice_lines(lines, start_line, end_line)
    elif strategy == Strategy.CONCLUSION_FALLBACK:
        start_line = parsed.get("start_line")
        end_line = parsed.get("end_line")
        if not start_line:
            return None
        return slice_lines(lines, start_line, end_line)
    elif strategy == Strategy.CONCLUSION_VALIDATE:
        conclusion = parsed.get("conclusion")
        if not conclusion or len(conclusion.strip()) < 50:
            return None
        return conclusion.strip()
    return None


# ============================================================================
#  Stage 3: Paper Loader (Main Class)
# ============================================================================


class PaperLoader:
    """Paper content loader with L1-L4 layered loading.
    
    Data Pipe Flow (aligned with extract.py):
        1. Read markdown → MarkdownLines (immutable)
        2. Extract headers → HeaderList (immutable)
        3. Prepare prompt → str
        4. Call LLM → str
        5. Parse → dict
        6. Process → str
        7. Write meta → LoadResult (immutable)
    """

    def __init__(self, papers_dir: Path, config: Config) -> None:
        self._store = PaperStore(papers_dir)
        self._config = config
        self._http = RequestsClient()

    @property
    def _runner(self) -> LLMRunner:
        """Lazy LLM runner."""
        if not hasattr(self, "_llm_runner"):
            api_key = self._config.resolve_llm_api_key()
            object.__setattr__(
                self, "_llm_runner",
                LLMRunner(self._config.llm, http_client=self._http, api_key=api_key)
            )
        return self._llm_runner

    def _execute(
        self,
        strategy: Strategy,
        lines: MarkdownLines,
        meta: dict,
        timeout: int | None = None,
    ) -> tuple[str | None, str]:
        """Execute strategy pipeline (Stage 3a)."""
        prompt_data = _prepare(strategy, lines, meta)
        template = _PROMPTS[strategy]
        prompt = template.render(headers=prompt_data, sample=prompt_data, text=prompt_data)

        request = LLMRequest(
            prompt=prompt,
            config=self._config,
            timeout=timeout,
            purpose="loader"
        )
        
        raw, reason = self._runner.execute(request, max_retries=2)
        if not raw:
            return None, f"{strategy.name}-{reason}"

        parsed = _parse(strategy, raw)
        result = _process(strategy, parsed, lines)
        if result:
            return result, strategy.name
        return None, f"{strategy.name}-process-failed"

    def load_toc(self, paper_id: str, *, force: bool = False) -> LoadResult:
        """Load TOC for a paper (L3 enrichment)."""
        paper_d = self._store.paper_dir(paper_id)
        if not paper_d.exists():
            return LoadResult(success=False, paper_id=paper_id, error=f"Paper dir not found: {paper_d}")

        try:
            meta = self._store.read_meta(paper_d)
        except Exception as e:
            return LoadResult(success=False, paper_id=paper_id, error=f"Read meta failed: {e}")

        if meta.get("toc") and not force:
            _log.debug("existing TOC (%d entries), skipping", len(meta["toc"]))
            return LoadResult(success=True, paper_id=paper_id, method="existing")

        md = self._store.read_md(paper_d)
        if not md:
            return LoadResult(success=False, paper_id=paper_id, error="No markdown content")

        # Stage: Create immutable lines
        lines = MarkdownLines.from_str(md, paper_id)
        
        # Stage: Execute pipeline
        result, method = self._execute(Strategy.TOC, lines, meta, timeout=120)
        if not result:
            return LoadResult(success=False, paper_id=paper_id, error=f"TOC failed: {method}")

        try:
            toc = json.loads(result)
        except json.JSONDecodeError:
            toc = result

        if not toc:
            return LoadResult(success=False, paper_id=paper_id, error="LLM returned empty TOC")

        meta["toc"] = toc
        meta["toc_extracted_at"] = datetime.now().isoformat(timespec="seconds")
        self._store.write_meta(paper_d, meta)
        
        return LoadResult(
            success=True,
            paper_id=paper_id,
            content=result,
            method=method,
            timestamp=meta["toc_extracted_at"]
        )

    def load_conclusion(self, paper_id: str, *, force: bool = False) -> LoadResult:
        """Load conclusion for a paper (L3 enrichment)."""
        paper_d = self._store.paper_dir(paper_id)
        if not paper_d.exists():
            return LoadResult(success=False, paper_id=paper_id, error=f"Paper dir not found: {paper_d}")

        try:
            meta = self._store.read_meta(paper_d)
        except Exception as e:
            return LoadResult(success=False, paper_id=paper_id, error=f"Read meta failed: {e}")

        if meta.get("l3_conclusion") and not force:
            _log.debug("existing L3 (method: %s), skipping", meta.get("l3_extraction_method", "?"))
            return LoadResult(success=True, paper_id=paper_id, method=meta.get("l3_extraction_method", "existing"))

        md = self._store.read_md(paper_d)
        if not md:
            return LoadResult(success=False, paper_id=paper_id, error="No markdown content")

        lines = MarkdownLines.from_str(md, paper_id)

        # Try strategies in order
        strategies = [
            ("toc_based", self._extract_toc_based),
            ("select", lambda l, m: self._execute(Strategy.CONCLUSION_SELECT, l, m, timeout=90)),
            ("fallback", lambda l, m: self._execute(Strategy.CONCLUSION_FALLBACK, l, m, timeout=90)),
        ]

        for name, extract_fn in strategies:
            extracted, method = extract_fn(lines, meta)
            if not extracted:
                continue

            # Validate
            validated, val_method = self._execute(
                Strategy.CONCLUSION_VALIDATE, 
                MarkdownLines.from_str(extracted, paper_id),
                {"_text_to_validate": extracted},
                timeout=30
            )
            if validated:
                meta["l3_conclusion"] = validated
                meta["l3_extraction_method"] = f"{method}+{val_method}"
                meta["l3_extracted_at"] = datetime.now().isoformat(timespec="seconds")
                self._store.write_meta(paper_d, meta)
                
                return LoadResult(
                    success=True,
                    paper_id=paper_id,
                    content=validated,
                    method=meta["l3_extraction_method"],
                    timestamp=meta["l3_extracted_at"]
                )

        return LoadResult(success=False, paper_id=paper_id, error="all strategies failed")

    def _extract_toc_based(self, lines: MarkdownLines, meta: dict) -> tuple[str | None, str]:
        """Extract from existing TOC."""
        toc = meta.get("toc")
        if not toc:
            return None, "toc-missing"

        entry = find_conclusion_entry(extract_headers(lines))
        if not entry:
            return None, "toc-no-conclusion"

        start_line = entry.line
        headers = extract_headers(lines)
        end_line = find_next_section_line(headers, start_line)
        extracted = slice_lines(lines, start_line, end_line)
        
        _log.debug("[TOC] lines %d-%s, %d chars", start_line, end_line or "EOF", len(extracted))
        return extracted, "toc"


__all__ = ["PaperLoader", "Strategy", "LoadResult", "MarkdownLines", "HeaderList"]
