"""
loader.py — Layered content loading and TOC/conclusion extraction.

Extraction layers
─────────────────
  L1: title / authors / year / journal / doi  — JSON fields
  L2: abstract                                — JSON fields
  L3: conclusion                              — JSON fields (requires enrich)
  L4: full markdown                           — paper.md file

Architecture
────────────
  StrategyRegistry   — key-based prompt + pipeline resolution
  ContentExtractor   — pure helper functions (no I/O)
  PaperEnricher      — orchestrator; receives dependencies via constructor

Usage
─────
    from linkora.loader import PaperEnricher

    enricher = PaperEnricher(
        papers_dir=ctx.workspace.papers_dir,
        config=ctx.config,
        runner=ctx.llm_runner(),
    )
    enricher.enrich_toc(paper_id)
    enricher.enrich_conclusion(paper_id)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Callable

from linkora.config import AppConfig
from linkora.llm import LLMRequest, LLMRunner, PromptTemplate
from linkora.log import get_logger

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Strategy keys
# ---------------------------------------------------------------------------


class StrategyKey(Enum):
    TOC = auto()
    CONCLUSION_SELECT = auto()
    CONCLUSION_FALLBACK = auto()
    CONCLUSION_VALIDATE = auto()


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_TOC_PROMPT = PromptTemplate(
    system="You are an academic paper analyzer.",
    user_template="""The following are ALL lines starting with '#' extracted from an academic paper
markdown file (converted from PDF by MinerU). Some are real section headers;
others are NOISE: author running headers, journal name headers, repeated paper
titles, or publisher metadata.

KEEP as real headers (needed as section boundary markers):
- Numbered/lettered sections and subsections
- Introduction, Abstract, Conclusion, Conclusions, Concluding Remarks, Summary
- References, Bibliography, Appendix (any variant)
- Post-matter: Acknowledgments, Funding, CRediT authorship contribution statement,
  Declaration of competing interest, Conflict of interest, Data availability,
  Author contributions, Author ORCIDs, Declaration of interests

Assign level: 1=top-level, 2=subsection (e.g. 2.1), 3=sub-subsection (e.g. 2.1.1).

Headers:
{headers}

Return JSON only:
{{"toc": [{{"line": <N>, "level": <1|2|3>, "title": "<title>"}}, ...]}}""",
)

_CONCLUSION_SELECT_PROMPT = PromptTemplate(
    system="You are an academic paper analyzer.",
    user_template="""Below are all section headers (with line numbers) from an academic paper.
Identify the header that marks the START of the conclusion section
(may be 'Conclusion', 'Conclusions', 'Concluding Remarks', 'Summary', etc.).

{headers}

Return JSON only: {{"line": <line_number>, "header": "<header_text>"}}
If no conclusion section exists: {{"line": null, "header": null}}""",
)

_CONCLUSION_FALLBACK_PROMPT = PromptTemplate(
    system="You are an academic paper analyzer.",
    user_template="""Find the conclusion section in this academic paper (markdown format).
Return 1-indexed line numbers where the conclusion STARTS and ENDS
(last line before References/Appendix/end of file).

{sample}

Return JSON only: {{"start_line": <N>, "end_line": <N>}}
If no conclusion exists: {{"start_line": null, "end_line": null}}""",
)

_CONCLUSION_VALIDATE_PROMPT = PromptTemplate(
    system="You are an academic paper analyzer.",
    user_template="""The following text was extracted as the conclusion section of an academic paper.
Tasks:
1. Check it contains actual conclusion content (summary of findings, contributions, future work).
2. If yes, return a CLEANED version:
   - Remove the section header line
   - Remove in-text running headers
   - Remove everything AFTER the conclusion ends (Acknowledgments, Funding, etc.)
   - Keep only the conclusion paragraphs — do NOT truncate mid-sentence.
3. If it contains NO conclusion content, set conclusion to null.

{text}

Return JSON only: {{"conclusion": "<cleaned text or null>", "reason": "<one sentence>"}}""",
)


# ---------------------------------------------------------------------------
# Strategy dispatch tables
# ---------------------------------------------------------------------------

_STRATEGY_MAP: dict[str, StrategyKey] = {
    "toc": StrategyKey.TOC,
    "conclusion_select": StrategyKey.CONCLUSION_SELECT,
    "conclusion_fallback": StrategyKey.CONCLUSION_FALLBACK,
    "conclusion_validate": StrategyKey.CONCLUSION_VALIDATE,
}

_PROMPTS: dict[StrategyKey, PromptTemplate] = {
    StrategyKey.TOC: _TOC_PROMPT,
    StrategyKey.CONCLUSION_SELECT: _CONCLUSION_SELECT_PROMPT,
    StrategyKey.CONCLUSION_FALLBACK: _CONCLUSION_FALLBACK_PROMPT,
    StrategyKey.CONCLUSION_VALIDATE: _CONCLUSION_VALIDATE_PROMPT,
}


# ---------------------------------------------------------------------------
# Prepare functions  (lines + meta → prompt data string)
# ---------------------------------------------------------------------------


def _prepare_headers(lines: list[str], meta: dict) -> str:
    headers = ContentExtractor.extract_headers(lines)
    return "\n".join(
        f"Line {h['line']}: {'#' * h['level']} {h['text']}" for h in headers
    )


def _prepare_sample(lines: list[str], meta: dict) -> str:
    return ContentExtractor.sample_lines(lines)


def _prepare_validate(lines: list[str], meta: dict) -> str:
    return meta.get("_text_to_validate", "")


_PREPARE_FNS: dict[StrategyKey, Callable[[list[str], dict], str]] = {
    StrategyKey.TOC: _prepare_headers,
    StrategyKey.CONCLUSION_SELECT: _prepare_headers,
    StrategyKey.CONCLUSION_FALLBACK: _prepare_sample,
    StrategyKey.CONCLUSION_VALIDATE: _prepare_validate,
}


# ---------------------------------------------------------------------------
# Process functions  (parsed dict + lines → result string | None)
# ---------------------------------------------------------------------------


def _process_toc(parsed: dict, lines: list[str]) -> str | None:
    toc = parsed.get("toc", [])
    return json.dumps(toc) if toc else None


def _process_conclusion_select(parsed: dict, lines: list[str]) -> str | None:
    start_line = parsed.get("line")
    if not start_line:
        return None
    headers = ContentExtractor.extract_headers(lines)
    end_line = ContentExtractor.find_next_section_line(headers, start_line)
    return ContentExtractor.slice_lines(lines, start_line, end_line)


def _process_conclusion_fallback(parsed: dict, lines: list[str]) -> str | None:
    start_line = parsed.get("start_line")
    end_line = parsed.get("end_line")
    return (
        ContentExtractor.slice_lines(lines, start_line, end_line)
        if start_line
        else None
    )


def _process_conclusion_validate(parsed: dict, lines: list[str]) -> str | None:
    conclusion = parsed.get("conclusion")
    return conclusion.strip() if conclusion and len(conclusion.strip()) >= 50 else None


_PROCESS_FNS: dict[StrategyKey, Callable[[dict, list[str]], str | None]] = {
    StrategyKey.TOC: _process_toc,
    StrategyKey.CONCLUSION_SELECT: _process_conclusion_select,
    StrategyKey.CONCLUSION_FALLBACK: _process_conclusion_fallback,
    StrategyKey.CONCLUSION_VALIDATE: _process_conclusion_validate,
}


# ---------------------------------------------------------------------------
# StrategyRegistry
# ---------------------------------------------------------------------------


class StrategyRegistry:
    """Resolves the full prompt+process pipeline for a given strategy key."""

    @staticmethod
    def get_prompt(key: str) -> PromptTemplate:
        strategy = _STRATEGY_MAP.get(key)
        if strategy is None:
            raise ValueError(f"Unknown strategy key: '{key}'")
        return _PROMPTS[strategy]

    @staticmethod
    def prepare(key: str, lines: list[str], meta: dict) -> str:
        strategy = _STRATEGY_MAP.get(key)
        return _PREPARE_FNS[strategy](lines, meta) if strategy else ""

    @staticmethod
    def parse(key: str, raw: str) -> dict:
        text = re.sub(r"^```\w*\s*", "", raw.strip())
        text = re.sub(r"\s*```$", "", text)
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # Attempt to fix unescaped backslashes.
            try:
                result = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text))
            except json.JSONDecodeError:
                result = {}
        if key != "toc":
            return result
        return {"toc": result.get("toc", [])}

    @staticmethod
    def process(key: str, parsed: dict, lines: list[str]) -> str | None:
        strategy = _STRATEGY_MAP.get(key)
        return _PROCESS_FNS[strategy](parsed, lines) if strategy else None


# ---------------------------------------------------------------------------
# ContentExtractor  (pure helper functions)
# ---------------------------------------------------------------------------


class ContentExtractor:
    _HEADER_RE = re.compile(r"^(#{1,4})\s+(.+)")
    _REAL_SECTION_RE = re.compile(
        r"^(?:"
        r"\d[\d.]*[\s.]|"
        r"[IVX]+[\s.)]|"
        r"[A-F][\s.)]|"
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
        headers = []
        for i, line in enumerate(lines, start=1):
            m = ContentExtractor._HEADER_RE.match(line.rstrip())
            if m:
                headers.append(
                    {"line": i, "level": len(m.group(1)), "text": m.group(2).strip()}
                )
        return headers

    @staticmethod
    def is_real_section(title: str) -> bool:
        return bool(ContentExtractor._REAL_SECTION_RE.match(title.strip()))

    @staticmethod
    def filter_real_sections(headers: list[dict]) -> list[dict]:
        return [h for h in headers if ContentExtractor.is_real_section(h["text"])]

    @staticmethod
    def slice_lines(lines: list[str], start: int, end: int | None) -> str:
        s = max(0, start - 1)
        e = end if end is not None else len(lines)
        return "\n".join(lines[s:e]).strip()

    @staticmethod
    def find_conclusion_entry(toc: list[dict]) -> dict | None:
        for entry in toc:
            if ContentExtractor._CONCLUSION_KEYWORDS.search(entry.get("title", "")):
                return entry
        return None

    @staticmethod
    def find_next_section_line(headers: list[dict], after_line: int) -> int | None:
        for h in ContentExtractor.filter_real_sections(headers):
            if h["line"] > after_line:
                return h["line"] - 1
        return None

    @staticmethod
    def sample_lines(lines: list[str], head: int = 100, tail: int = 200) -> str:
        n = len(lines)
        if n <= head + tail:
            return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))
        head_str = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines[:head]))
        tail_start = max(head, n - tail)
        tail_str = "\n".join(
            f"{tail_start + i + 1}: {line}" for i, line in enumerate(lines[tail_start:])
        )
        return (
            f"[Lines 1–{head}]\n{head_str}\n\n"
            f"...[middle omitted]...\n\n"
            f"[Lines {tail_start + 1}–{n}]\n{tail_str}"
        )


# ---------------------------------------------------------------------------
# PaperEnricher
# ---------------------------------------------------------------------------


class PaperEnricher:
    """
    Orchestrates TOC and conclusion extraction for workspace papers.

    Dependencies are injected via the constructor so the enricher is
    testable without live LLM calls or a real filesystem.

    Parameters
    ----------
    papers_dir:
        ``WorkspacePaths.papers_dir`` for the active workspace.
    config:
        Application configuration (``AppContext.config``).
    runner:
        Initialised ``LLMRunner`` (``AppContext.llm_runner()``).
    """

    def __init__(self, papers_dir: Path, config: AppConfig, runner: LLMRunner) -> None:
        from linkora.papers import PaperStore

        self._store = PaperStore(papers_dir)
        self._config = config
        self._runner = runner

    # ------------------------------------------------------------------
    # Internal execution primitive
    # ------------------------------------------------------------------

    def _execute(
        self,
        strategy_key: str,
        lines: list[str],
        meta: dict,
        *,
        timeout: int | None = None,
    ) -> tuple[str | None, str]:
        """
        Run one strategy step end-to-end:
          prepare → render prompt → LLM → parse → process
        """
        prompt_data = StrategyRegistry.prepare(strategy_key, lines, meta)
        template = StrategyRegistry.get_prompt(strategy_key)

        # All three render keys (headers / sample / text) receive the same
        # prepared data; each template only consumes the key it needs.
        prompt = template.render(
            headers=prompt_data, sample=prompt_data, text=prompt_data
        )

        request = LLMRequest(
            prompt=prompt,
            config=self._config.llm,
            system=template.system,
            json_mode=True,
            timeout=timeout,
            max_retries=2,
            purpose=f"loader.{strategy_key}",
        )

        result = self._runner.execute(request)
        if not result or not result.content:
            return None, f"{strategy_key}-no-response"

        parsed = StrategyRegistry.parse(strategy_key, result.content)
        processed = StrategyRegistry.process(strategy_key, parsed, lines)
        return (
            processed,
            strategy_key if processed else f"{strategy_key}-process-failed",
        )

    # ------------------------------------------------------------------
    # Public enrichment methods
    # ------------------------------------------------------------------

    def enrich_toc(self, paper_id: str, *, force: bool = False) -> bool:
        """
        Extract and store the table of contents for *paper_id*.

        Returns True on success.
        """
        paper_d = self._store.paper_dir(paper_id)
        if not paper_d.exists():
            _log.error("Paper directory not found: %s", paper_d)
            return False

        try:
            meta = self._store.read_meta(paper_d)
        except Exception as exc:
            _log.error("Failed to read meta for %s: %s", paper_id, exc)
            return False

        if meta.get("toc") and not force:
            _log.debug("TOC already exists (%d entries), skipping", len(meta["toc"]))
            return True

        md = self._store.read_md(paper_d)
        if not md:
            _log.error("No markdown content for %s", paper_id)
            return False

        result, method = self._execute("toc", md.splitlines(), meta)
        if not result:
            _log.error("TOC extraction failed (%s) for %s", method, paper_id)
            return False

        try:
            toc = json.loads(result)
        except json.JSONDecodeError:
            toc = result

        if not toc:
            _log.error("LLM returned empty TOC for %s", paper_id)
            return False

        meta["toc"] = toc
        meta["toc_extracted_at"] = datetime.now().isoformat(timespec="seconds")
        self._store.write_meta(paper_d, meta)
        _log.debug("TOC written (%d entries) for %s", len(toc), paper_id)
        return True

    def enrich_conclusion(self, paper_id: str, *, force: bool = False) -> bool:
        """
        Extract and store the conclusion for *paper_id*.

        Returns True on success.
        """
        paper_d = self._store.paper_dir(paper_id)
        if not paper_d.exists():
            _log.error("Paper directory not found: %s", paper_d)
            return False

        try:
            meta = self._store.read_meta(paper_d)
        except Exception as exc:
            _log.error("Failed to read meta for %s: %s", paper_id, exc)
            return False

        if meta.get("l3_conclusion") and not force:
            _log.debug(
                "Conclusion exists (method: %s), skipping",
                meta.get("l3_extraction_method", "?"),
            )
            return True

        md = self._store.read_md(paper_d)
        if not md:
            _log.error("No markdown content for %s", paper_id)
            return False

        lines = md.splitlines()

        # Try three strategies in order of increasing cost.
        strategies = [
            ("toc_based", self._extract_toc_based),
            ("select_from_headers", self._extract_select_from_headers),
            ("fallback", self._extract_fallback),
        ]

        for _, extract_fn in strategies:
            extracted, method = extract_fn(lines, meta)
            if not extracted:
                continue

            validated, val_method = self._validate(extracted)
            if not validated:
                continue

            meta["l3_conclusion"] = validated
            meta["l3_extraction_method"] = f"{method}+{val_method}"
            meta["l3_extracted_at"] = datetime.now().isoformat(timespec="seconds")
            self._store.write_meta(paper_d, meta)
            _log.debug(
                "Conclusion written (method: %s, %d chars) for %s",
                meta["l3_extraction_method"],
                len(validated),
                paper_id,
            )
            return True

        _log.error("All conclusion strategies failed for %s", paper_id)
        return False

    # ------------------------------------------------------------------
    # Extraction strategies  (private)
    # ------------------------------------------------------------------

    def _extract_toc_based(
        self, lines: list[str], meta: dict
    ) -> tuple[str | None, str]:
        toc = meta.get("toc")
        if not toc:
            return None, "toc-missing"

        entry = ContentExtractor.find_conclusion_entry(toc)
        if not entry:
            return None, "toc-no-conclusion"

        start_line = entry["line"]
        headers = ContentExtractor.extract_headers(lines)
        end_line = ContentExtractor.find_next_section_line(headers, start_line)

        extracted = ContentExtractor.slice_lines(lines, start_line, end_line)
        _log.debug(
            "[TOC] lines %d-%s, %d chars",
            start_line,
            end_line or "EOF",
            len(extracted),
        )
        return extracted, "toc"

    def _extract_select_from_headers(
        self, lines: list[str], meta: dict
    ) -> tuple[str | None, str]:
        headers = ContentExtractor.extract_headers(lines)
        if not headers:
            return None, "no-headers"
        _log.debug("[Select] %d headers found", len(headers))
        return self._execute("conclusion_select", lines, meta)

    def _extract_fallback(self, lines: list[str], meta: dict) -> tuple[str | None, str]:
        _log.debug("[Fallback] attempting direct line-number extraction")
        return self._execute("conclusion_fallback", lines, meta)

    def _validate(self, text: str) -> tuple[str | None, str]:
        if len(text.strip()) < 100:
            return None, "text-too-short"
        return self._execute(
            "conclusion_validate", [], {"_text_to_validate": text}, timeout=30
        )
