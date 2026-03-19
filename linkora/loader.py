"""
loader.py — Layered Content Loading + TOC/Conclusion Extraction
===============================================================

L1: title/authors/year/journal/doi  ← JSON fields
L2: abstract                       ← JSON fields
L3: conclusion                     ← JSON fields (requires enrich_l3)
L4: full markdown                  ← Read .md file

Architecture:
  - StrategyRegistry: Key-based pipeline resolution (prompt + strategy)
  - LLMRunner: LLM execution with retry
  - ContentExtractor: Pure functions
  - PaperEnricher: Class-based interface

Usage:
    from linkora.loader import PaperEnricher
    enricher = PaperEnricher(papers_dir)
    enricher.enrich_toc(paper_id, config)
    enricher.enrich_conclusion(paper_id, config)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Callable

from linkora.config import Config
from linkora.llm import LLMRunner, LLMRequest, PromptTemplate
from linkora.log import get_logger

_log = get_logger(__name__)


# ============================================================================
#  Strategy Keys (Enum for type safety)
# ============================================================================


class StrategyKey(Enum):
    """Strategy keys for extraction pipeline."""

    TOC = auto()
    CONCLUSION_SELECT = auto()
    CONCLUSION_FALLBACK = auto()
    CONCLUSION_VALIDATE = auto()


# ============================================================================
# Prompt definitions
_TOC_PROMPT = PromptTemplate(
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
{{"toc": [{{"line": <N>, "level": <1|2|3>, "title": "<title>"}}, ...]}}""",
)

_CONCLUSION_SELECT_PROMPT = PromptTemplate(
    system="You are an academic paper analyzer.",
    user_template="""Below are all section headers (with line numbers) from an academic paper markdown file.
Identify the header that marks the START of the conclusion section
(may be named 'Conclusion', 'Conclusions', 'Concluding Remarks', 'Summary', etc.).

{headers}

Return JSON only: {{"line": <line_number>, "header": "<header_text>"}}
If no conclusion section exists, return: {{"line": null, "header": null}}""",
)

_CONCLUSION_FALLBACK_PROMPT = PromptTemplate(
    system="You are an academic paper analyzer.",
    user_template="""Find the conclusion section in this academic paper (markdown format).
Return the 1-indexed line number where the conclusion STARTS and where it ENDS
(last line before References/Appendix/end of file).

{sample}

Return JSON only: {{"start_line": <N>, "end_line": <N>}}
If no conclusion exists: {{"start_line": null, "end_line": null}}""",
)

_CONCLUSION_VALIDATE_PROMPT = PromptTemplate(
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

Return JSON only: {{"conclusion": "<cleaned text or null>", "reason": "<one sentence>"}}""",
)


# ============================================================================
#  Prompt and Strategy Dictionaries (Dictionary Dispatch)
# ============================================================================


# Prompt templates by strategy key
_PROMPTS: dict[StrategyKey, PromptTemplate] = {
    StrategyKey.TOC: _TOC_PROMPT,
    StrategyKey.CONCLUSION_SELECT: _CONCLUSION_SELECT_PROMPT,
    StrategyKey.CONCLUSION_FALLBACK: _CONCLUSION_FALLBACK_PROMPT,
    StrategyKey.CONCLUSION_VALIDATE: _CONCLUSION_VALIDATE_PROMPT,
}


# String to enum mapping
_STRATEGY_MAP: dict[str, StrategyKey] = {
    "toc": StrategyKey.TOC,
    "conclusion_select": StrategyKey.CONCLUSION_SELECT,
    "conclusion_fallback": StrategyKey.CONCLUSION_FALLBACK,
    "conclusion_validate": StrategyKey.CONCLUSION_VALIDATE,
}


class StrategyRegistry:
    """Registry that resolves entire pipeline by strategy key.

    Uses dictionary dispatch instead of if/elif chains per AGENT.md guidelines.
    """

    @staticmethod
    def get_prompt(key: str) -> PromptTemplate:
        """Get prompt template by key (dict dispatch)."""
        strategy = _STRATEGY_MAP.get(key)
        if strategy is None:
            raise ValueError(f"Unknown strategy: {key}")
        return _PROMPTS[strategy]

    @staticmethod
    def prepare(key: str, lines: list[str], meta: dict) -> str:
        """Prepare prompt data by key (dict dispatch)."""
        strategy = _STRATEGY_MAP.get(key)
        if strategy is None:
            return ""

        # Dictionary dispatch for prepare
        return _PREPARE_FNS[strategy](lines, meta)

    @staticmethod
    def parse(key: str, raw: str) -> dict:
        """Parse LLM response by key."""
        text = raw.strip()
        text = re.sub(r"^```\w*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
            try:
                result = json.loads(fixed)
            except json.JSONDecodeError:
                result = {}

        # All non-toc strategies return result as-is
        if key != "toc":
            return result
        return {"toc": result.get("toc", [])}

    @staticmethod
    def process(key: str, parsed: dict, lines: list[str]) -> str | None:
        """Process parsed result by key (dict dispatch)."""
        strategy = _STRATEGY_MAP.get(key)
        if strategy is None:
            return None
        return _PROCESS_FNS[strategy](parsed, lines)


# ============================================================================
#  Helper Functions for Dictionary Dispatch
# ============================================================================


def _prepare_headers(lines: list[str], meta: dict) -> str:
    """Prepare headers string from lines."""
    headers = ContentExtractor.extract_headers(lines)
    return "\n".join(
        f"Line {h['line']}: {'#' * h['level']} {h['text']}" for h in headers
    )


def _prepare_sample(lines: list[str], meta: dict) -> str:
    """Prepare sample lines for fallback."""
    return ContentExtractor.sample_lines(lines)


def _prepare_validate(lines: list[str], meta: dict) -> str:
    """Prepare text for validation."""
    return meta.get("_text_to_validate", "")


# Prepare dispatch dictionary
_PREPARE_FNS: dict[StrategyKey, Callable[[list[str], dict], str]] = {
    StrategyKey.TOC: _prepare_headers,
    StrategyKey.CONCLUSION_SELECT: _prepare_headers,
    StrategyKey.CONCLUSION_FALLBACK: _prepare_sample,
    StrategyKey.CONCLUSION_VALIDATE: _prepare_validate,
}


def _process_toc(parsed: dict, lines: list[str]) -> str | None:
    """Process TOC result."""
    toc = parsed.get("toc", [])
    if not toc:
        return None
    return json.dumps(toc)


def _process_conclusion_select(parsed: dict, lines: list[str]) -> str | None:
    """Process conclusion selection result."""
    start_line = parsed.get("line")
    if not start_line:
        return None
    headers = ContentExtractor.extract_headers(lines)
    end_line = ContentExtractor.find_next_section_line(headers, start_line)
    return ContentExtractor.slice_lines(lines, start_line, end_line)


def _process_conclusion_fallback(parsed: dict, lines: list[str]) -> str | None:
    """Process conclusion fallback result."""
    start_line = parsed.get("start_line")
    end_line = parsed.get("end_line")
    if not start_line:
        return None
    return ContentExtractor.slice_lines(lines, start_line, end_line)


def _process_conclusion_validate(parsed: dict, lines: list[str]) -> str | None:
    """Process conclusion validation result."""
    conclusion = parsed.get("conclusion")
    if not conclusion or len(conclusion.strip()) < 50:
        return None
    return conclusion.strip()


# Process dispatch dictionary
_PROCESS_FNS: dict[StrategyKey, Callable[[dict, list[str]], str | None]] = {
    StrategyKey.TOC: _process_toc,
    StrategyKey.CONCLUSION_SELECT: _process_conclusion_select,
    StrategyKey.CONCLUSION_FALLBACK: _process_conclusion_fallback,
    StrategyKey.CONCLUSION_VALIDATE: _process_conclusion_validate,
}


# ============================================================================
# Content Extractor: Pure Functions
# ============================================================================


class ContentExtractor:
    """Pure content extraction functions."""

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

    @staticmethod
    def extract_headers(lines: list[str]) -> list[dict]:
        """Extract all # headers with line numbers (1-indexed)."""
        headers = []
        for i, line in enumerate(lines, start=1):
            m = ContentExtractor._HEADER_RE.match(line.rstrip())
            if m:
                headers.append(
                    {
                        "line": i,
                        "level": len(m.group(1)),
                        "text": m.group(2).strip(),
                    }
                )
        return headers

    @staticmethod
    def is_real_section(title: str) -> bool:
        """Check if title is a real section (not running header)."""
        return bool(ContentExtractor._REAL_SECTION_RE.match(title.strip()))

    @staticmethod
    def filter_real_sections(headers: list[dict]) -> list[dict]:
        """Filter to only real section headers."""
        return [h for h in headers if ContentExtractor.is_real_section(h["text"])]

    @staticmethod
    def slice_lines(lines: list[str], start: int, end: int | None) -> str:
        """Slice lines by 1-indexed inclusive range."""
        s = max(0, start - 1)
        e = end if end is not None else len(lines)
        return "\n".join(lines[s:e]).strip()

    @staticmethod
    def find_conclusion_entry(toc: list[dict]) -> dict | None:
        """Find conclusion entry in TOC."""
        for entry in toc:
            if ContentExtractor._CONCLUSION_KEYWORDS.search(entry.get("title", "")):
                return entry
        return None

    @staticmethod
    def find_next_section_line(headers: list[dict], after_line: int) -> int | None:
        """Find next real section after given line."""
        for h in ContentExtractor.filter_real_sections(headers):
            if h["line"] > after_line:
                return h["line"] - 1
        return None

    @staticmethod
    def sample_lines(lines: list[str], head: int = 100, tail: int = 200) -> str:
        """Sample lines for fallback path (first head + last tail)."""
        n = len(lines)
        if n <= head + tail:
            return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))

        head_str = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines[:head]))
        tail_start = max(head, n - tail)
        tail_str = "\n".join(
            f"{tail_start + i + 1}: {line}" for i, line in enumerate(lines[tail_start:])
        )
        return f"[Lines 1–{head}]\n{head_str}\n\n...[middle]...\n\n[Lines {tail_start + 1}–{n}]\n{tail_str}"


# ============================================================================
# Paper Enricher
# ============================================================================


class PaperEnricher:
    """Orchestrates TOC and conclusion extraction.

    Data pipe flow:
        1. Initialize with config and runner (dependencies)
        2. Call enrich_toc/enrich_conclusion with paper_id
    """

    def __init__(
        self,
        papers_dir: Path,
        config: Config,
        runner: LLMRunner,
    ) -> None:
        """Initialize with papers directory, config, and runner."""
        from linkora.papers import PaperStore

        self._store = PaperStore(papers_dir)
        self._papers_dir = papers_dir
        self._config = config
        self._runner = runner

    def _execute(
        self,
        strategy_key: str,
        lines: list[str],
        meta: dict,
        *,
        timeout: int | None = None,
    ) -> tuple[str | None, str]:
        """Execute strategy by key with unified retry."""
        # Prepare prompt data
        prompt_data = StrategyRegistry.prepare(strategy_key, lines, meta)

        # Get prompt template
        prompt_template = StrategyRegistry.get_prompt(strategy_key)
        prompt = prompt_template.render(
            **{"headers": prompt_data, "sample": prompt_data, "text": prompt_data}
        )

        # Create LLMRequest with injected config
        request = LLMRequest(
            prompt=prompt,
            config=self._config.llm,
            system=prompt_template.system,
            json_mode=True,
            timeout=timeout,
            max_retries=2,
            purpose=f"loader.{strategy_key}",
        )

        # Execute with injected runner
        result = self._runner.execute(request)
        raw = result.content if result else None

        if not raw:
            return None, f"{strategy_key}-no-response"

        # Parse
        parsed = StrategyRegistry.parse(strategy_key, raw)

        # Process
        processed = StrategyRegistry.process(strategy_key, parsed, lines)
        if processed:
            return processed, strategy_key

        return None, f"{strategy_key}-process-failed"

    def enrich_toc(
        self,
        paper_id: str,
        *,
        force: bool = False,
    ) -> bool:
        """Enrich TOC for a paper.

        Args:
            paper_id: Paper ID
            force: Force re-extraction even if TOC exists

        Returns:
            True if TOC extracted successfully
        """
        # Use store's paper_dir method instead of standalone function
        paper_d = self._store.paper_dir(paper_id)
        if not paper_d.exists():
            _log.error(f"Paper directory not found: {paper_d}")
            return False

        try:
            meta = self._store.read_meta(paper_d)
        except Exception as e:
            _log.error(f"Failed to read meta: {e}")
            return False

        if meta.get("toc") and not force:
            _log.debug("existing TOC (%d entries), skipping", len(meta["toc"]))
            return True

        md = self._store.read_md(paper_d)
        if not md:
            _log.error("No markdown content")
            return False

        lines = md.splitlines()

        # Use injected runner via _execute
        result, method = self._execute("toc", lines, meta)
        if not result:
            _log.error(f"TOC extraction failed: {method}")
            return False

        try:
            toc = json.loads(result)
        except json.JSONDecodeError:
            toc = result

        if not toc:
            _log.error("LLM returned empty TOC")
            return False

        _log.debug("LLM kept %d real headers", len(toc))

        meta["toc"] = toc
        meta["toc_extracted_at"] = datetime.now().isoformat(timespec="seconds")
        self._store.write_meta(paper_d, meta)
        _log.debug("TOC written to JSON")
        return True

    def enrich_conclusion(
        self,
        paper_id: str,
        *,
        force: bool = False,
    ) -> bool:
        """Enrich conclusion for a paper.

        Args:
            paper_id: Paper ID
            force: Force re-extraction even if conclusion exists

        Returns:
            True if conclusion extracted successfully
        """
        # Use store's paper_dir method
        paper_d = self._store.paper_dir(paper_id)
        if not paper_d.exists():
            _log.error(f"Paper directory not found: {paper_d}")
            return False

        try:
            meta = self._store.read_meta(paper_d)
        except Exception as e:
            _log.error(f"Failed to read meta: {e}")
            return False

        if meta.get("l3_conclusion") and not force:
            _log.debug(
                "existing L3 (method: %s), skipping",
                meta.get("l3_extraction_method", "?"),
            )
            return True

        md = self._store.read_md(paper_d)
        if not md:
            _log.error("No markdown content")
            return False

        lines = md.splitlines()

        # Try strategies in order: TOC-based → select from headers → fallback
        extract_strategies = [
            ("toc_based", self._extract_toc_based),
            ("select_from_headers", self._extract_select_from_headers),
            ("fallback", self._extract_fallback),
        ]

        for strategy_name, extract_fn in extract_strategies:
            extracted, method = extract_fn(lines, meta)
            if not extracted:
                continue

            # Validate using injected runner
            validated, val_method = self._validate(extracted)
            if validated:
                meta["l3_conclusion"] = validated
                meta["l3_extraction_method"] = f"{method}+{val_method}"
                meta["l3_extracted_at"] = datetime.now().isoformat(timespec="seconds")
                self._store.write_meta(paper_d, meta)
                _log.debug(
                    "L3 written (method: %s, %d chars)",
                    meta["l3_extraction_method"],
                    len(validated),
                )
                return True

        _log.error("all paths failed to extract conclusion")
        return False

    def _extract_toc_based(
        self,
        lines: list[str],
        meta: dict,
    ) -> tuple[str | None, str]:
        """Extract conclusion from existing TOC."""
        toc = meta.get("toc")
        if not toc:
            return None, "toc-missing"

        conclusion_entry = ContentExtractor.find_conclusion_entry(toc)
        if not conclusion_entry:
            return None, "toc-no-conclusion"

        start_line = conclusion_entry["line"]
        headers = ContentExtractor.extract_headers(lines)
        end_line = ContentExtractor.find_next_section_line(headers, start_line)

        extracted = ContentExtractor.slice_lines(lines, start_line, end_line)
        _log.debug(
            "[TOC] extracted lines %d-%s, %d chars",
            start_line,
            end_line or "EOF",
            len(extracted),
        )
        return extracted, "toc"

    def _extract_select_from_headers(
        self,
        lines: list[str],
        meta: dict,
    ) -> tuple[str | None, str]:
        """Extract conclusion by selecting from headers."""
        headers = ContentExtractor.extract_headers(lines)
        if not headers:
            return None, "no-headers"

        _log.debug("[Select] found %d headers", len(headers))
        return self._execute("conclusion_select", lines, meta)

    def _extract_fallback(
        self,
        lines: list[str],
        meta: dict,
    ) -> tuple[str | None, str]:
        """Extract conclusion using fallback (direct line numbers)."""
        _log.debug("[Fallback] switching to fallback")
        return self._execute("conclusion_fallback", lines, meta)

    def _validate(
        self,
        text: str,
    ) -> tuple[str | None, str]:
        """Validate and clean conclusion text."""
        if len(text.strip()) < 100:
            return None, "text-too-short"

        meta = {"_text_to_validate": text}
        return self._execute("conclusion_validate", [], meta, timeout=30)
