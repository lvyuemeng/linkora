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
    from scholaraio.loader import PaperEnricher
    enricher = PaperEnricher(papers_dir)
    enricher.enrich_toc(paper_id, config)
    enricher.enrich_conclusion(paper_id, config)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from scholaraio.llm import LLMRunner, LLMRequest, PromptTemplate
from scholaraio.log import get_logger

if TYPE_CHECKING:
    from scholaraio.config import Config

_log = get_logger(__name__)

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


class StrategyRegistry:
    """Registry that resolves entire pipeline by strategy key."""

    @staticmethod
    def get_prompt(key: str) -> PromptTemplate:
        """Get prompt template by key."""
        prompts = {
            "toc": _TOC_PROMPT,
            "conclusion_select": _CONCLUSION_SELECT_PROMPT,
            "conclusion_fallback": _CONCLUSION_FALLBACK_PROMPT,
            "conclusion_validate": _CONCLUSION_VALIDATE_PROMPT,
        }
        if key not in prompts:
            raise ValueError(f"Unknown strategy: {key}")
        return prompts[key]

    @staticmethod
    def prepare(key: str, lines: list[str], meta: dict) -> str:
        """Prepare prompt data by key."""
        if key == "toc":
            headers = ContentExtractor.extract_headers(lines)
            return "\n".join(
                f"Line {h['line']}: {'#' * h['level']} {h['text']}" for h in headers
            )
        elif key == "conclusion_select":
            headers = ContentExtractor.extract_headers(lines)
            return "\n".join(
                f"Line {h['line']}: {'#' * h['level']} {h['text']}" for h in headers
            )
        elif key == "conclusion_fallback":
            return ContentExtractor.sample_lines(lines)
        elif key == "conclusion_validate":
            return meta.get("_text_to_validate", "")
        return ""

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

        if key == "toc":
            return {"toc": result.get("toc", [])}
        elif key == "conclusion_select":
            return result
        elif key == "conclusion_fallback":
            return result
        elif key == "conclusion_validate":
            return result
        return {}

    @staticmethod
    def process(key: str, parsed: dict, lines: list[str]) -> str | None:
        """Process parsed result by key."""
        if key == "toc":
            toc = parsed.get("toc", [])
            if not toc:
                return None
            return json.dumps(toc)

        elif key == "conclusion_select":
            start_line = parsed.get("line")
            if not start_line:
                return None
            headers = ContentExtractor.extract_headers(lines)
            end_line = ContentExtractor.find_next_section_line(headers, start_line)
            return ContentExtractor.slice_lines(lines, start_line, end_line)

        elif key == "conclusion_fallback":
            start_line = parsed.get("start_line")
            end_line = parsed.get("end_line")
            if not start_line:
                return None
            return ContentExtractor.slice_lines(lines, start_line, end_line)

        elif key == "conclusion_validate":
            conclusion = parsed.get("conclusion")
            if not conclusion or len(conclusion.strip()) < 50:
                return None
            return conclusion.strip()

        return None


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
    """Orchestrates TOC and conclusion extraction."""

    def __init__(self, papers_dir: Path) -> None:
        """Initialize with papers directory."""
        from scholaraio.papers import PaperStore

        self._store = PaperStore(papers_dir)
        self._papers_dir = papers_dir

    def _get_runner(self, config: Config):
        """Get LLM runner for config."""
        from scholaraio.http import RequestsClient
        from scholaraio.llm import LLMRunner as LLMRunnerImpl

        api_key = config.llm.resolve_api_key()
        http_client = RequestsClient()
        return LLMRunnerImpl(config.llm, http_client, api_key)

    def _execute(
        self,
        strategy_key: str,
        lines: list[str],
        meta: dict,
        runner,
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

        # Execute with retry
        raw, reason = runner.execute(prompt, max_retries=2, timeout=timeout)
        if not raw:
            return None, f"{strategy_key}-{reason}"

        # Parse
        parsed = StrategyRegistry.parse(strategy_key, raw)

        # Process
        result = StrategyRegistry.process(strategy_key, parsed, lines)
        if result:
            return result, strategy_key

        return None, f"{strategy_key}-process-failed"

    def enrich_toc(
        self,
        paper_id: str,
        config: Config,
        *,
        force: bool = False,
    ) -> bool:
        """Enrich TOC for a paper."""
        from scholaraio.papers import paper_dir

        paper_d = paper_dir(self._papers_dir, paper_id)
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
        runner = self._get_runner(config)

        result, method = self._execute("toc", lines, meta, runner)
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
        config: Config,
        *,
        force: bool = False,
    ) -> bool:
        """Enrich conclusion for a paper."""
        from scholaraio.papers import paper_dir

        paper_d = paper_dir(self._papers_dir, paper_id)
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
        runner = self._get_runner(config)

        # Try strategies in order: TOC-based → select from headers → fallback
        extract_strategies = [
            ("toc_based", self._extract_toc_based),
            ("select_from_headers", self._extract_select_from_headers),
            ("fallback", self._extract_fallback),
        ]

        for strategy_name, extract_fn in extract_strategies:
            extracted, method = extract_fn(lines, meta, runner)
            if not extracted:
                continue

            # Validate
            validated, val_method = self._validate(extracted, runner)
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
        runner: LLMRunner,
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
        runner,
    ) -> tuple[str | None, str]:
        """Extract conclusion by selecting from headers."""
        headers = ContentExtractor.extract_headers(lines)
        if not headers:
            return None, "no-headers"

        _log.debug("[Select] found %d headers", len(headers))
        return self._execute("conclusion_select", lines, meta, runner)

    def _extract_fallback(
        self,
        lines: list[str],
        meta: dict,
        runner,
    ) -> tuple[str | None, str]:
        """Extract conclusion using fallback (direct line numbers)."""
        _log.debug("[Fallback] switching to fallback")
        return self._execute("conclusion_fallback", lines, meta, runner)

    def _validate(
        self,
        text: str,
        runner,
    ) -> tuple[str | None, str]:
        """Validate and clean conclusion text."""
        if len(text.strip()) < 100:
            return None, "text-too-short"

        meta = {"_text_to_validate": text}
        return self._execute("conclusion_validate", [], meta, runner, timeout=30)


# ============================================================================
# Update Callers: CLI, MCP Server, Pipeline
# ============================================================================

# Note: The following files need to be updated to use PaperEnricher:
# - scholaraio/cli.py (cmd_enrich_toc, cmd_enrich_l3)
# - scholaraio/mcp_server.py (enrich_toc, enrich_l3)
# - scholaraio/ingest/pipeline.py
#
# Replace:
#   from scholaraio.loader import enrich_toc, enrich_l3
#   enrich_toc(json_path, md_path, config)
#
# With:
#   from scholaraio.loader import PaperEnricher
#   enricher = PaperEnricher(papers_dir)
#   enricher.enrich_toc(paper_id, config)
