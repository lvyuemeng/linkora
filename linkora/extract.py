"""
extract.py — Metadata extraction from paper markdown.

Provides a functional pipeline with multiple extraction strategies:

  regex only    — Fast, no external calls, handles well-formatted PDFs
  llm           — LLM-only extraction (best for poorly OCR'd documents)
  auto          — Regex first; falls back to LLM when key fields are missing
  robust        — Regex + LLM dual-run; LLM corrects OCR errors using regex output

Usage
─────
    from linkora.extract import extract, ExtractionInput

    # Via AppConfig (uses config.ingest.extractor to select strategy)
    output = extract(ExtractionInput.from_file(path), config)

    # Direct pipeline construction
    pipeline = create_pipeline(mode="robust", llm_config=..., http_client=..., api_key=...)
    output = pipeline(ExtractionInput.from_file(path))
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from linkora.config import AppConfig
from linkora.http import HTTPClient, RequestsClient
from linkora.llm import (
    LLMConfig as LLMConfigType,
    LLMRequest,
    LLMRunner,
    PromptTemplate,
)
from linkora.log import get_logger
from linkora.papers import PaperMetadata

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Author name helpers
# ---------------------------------------------------------------------------

_LASTNAME_PREFIX_RE = re.compile(
    r"^(?:Prof|Prof\.|Dr|Dr\.|Mr|Mr\.|Mrs|Mrs\.|Ms|Ms\.)\s+",
    re.IGNORECASE,
)
_LASTNAME_JP_RE = re.compile(r"^[\u3040-\u309f\u30a0-\u30ff]+")
_LASTNAME_CN_RE = re.compile(r"^[\u4e00-\u9fff]+")


def _extract_lastname(full_name: str) -> str:
    """
    Extract the surname from a full author name.

    Handles Western names, names with honorific prefixes, CJK names
    (Japanese hiragana/katakana, Chinese CJK block).
    """
    if not full_name:
        return ""

    name = _LASTNAME_PREFIX_RE.sub("", full_name).strip()
    if not name:
        return ""

    # Japanese: hiragana/katakana-only block → treat whole token as family name.
    if _LASTNAME_JP_RE.match(name):
        return name

    # Chinese: leading CJK characters are the family name.
    m = _LASTNAME_CN_RE.match(name)
    if m:
        return m.group(0)

    # Western: last word is the surname.
    parts = name.split()
    if len(parts) == 1:
        return parts[0]
    last = parts[-1]
    return last if (last and last[0].isupper()) else parts[0]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionInput:
    """Immutable input bundle for the extraction pipeline."""

    source_name: str
    raw_text: str
    header: str
    file_hash: str = ""

    @classmethod
    def from_file(cls, filepath: Path, header_size: int = 50_000) -> "ExtractionInput":
        text = filepath.read_text(encoding="utf-8", errors="replace")
        return cls(
            source_name=filepath.name,
            raw_text=text,
            header=text[:header_size],
            file_hash=hashlib.md5(text.encode()).hexdigest(),
        )

    @classmethod
    def from_text(
        cls, name: str, text: str, header_size: int = 50_000
    ) -> "ExtractionInput":
        return cls(
            source_name=name,
            raw_text=text,
            header=text[:header_size],
            file_hash=hashlib.md5(text.encode()).hexdigest(),
        )


@dataclass(frozen=True)
class ExtractionContext:
    """Immutable accumulator passed through the pipeline stages."""

    input: ExtractionInput
    regex_meta: Optional[PaperMetadata] = None
    llm_meta: Optional[PaperMetadata] = None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractionOutput:
    """Final pipeline output with provenance metadata."""

    metadata: PaperMetadata
    method: str
    confidence: float
    fallback_used: bool


@dataclass(frozen=True)
class ExtractorConfig:
    """Strategy selection flags — plain data, no string dispatch."""

    use_llm: bool = False
    fallback: bool = False
    robust: bool = False


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class Extractor(Protocol):
    @property
    def name(self) -> str: ...
    def extract(self, input: ExtractionInput) -> ExtractionOutput: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def extractor_config_from_string(mode: str) -> ExtractorConfig:
    return ExtractorConfig(
        use_llm=mode == "llm",
        fallback=mode == "auto",
        robust=mode == "robust",
    )


def _clean_llm_str(val: str | None) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("null", "none", "n/a", "") else s


# ---------------------------------------------------------------------------
# Regex stage
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_AUTHORS_RE = re.compile(r"(?:Authors?|作者)[:：]\s*(.+?)(?:\n|$)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DOI_RE = re.compile(r"10\.\d{4,}/[^\s\]>]+")
_JOURNAL_RE = re.compile(r"(?:Journal|期刊|会议)[:：]\s*(.+?)(?:\n|$)", re.IGNORECASE)


def extract_regex(ctx: ExtractionContext) -> ExtractionContext:
    """Stage 1 — regex extraction (pure function)."""
    text = ctx.input.raw_text
    meta = PaperMetadata(source_file=ctx.input.source_name)

    m = _TITLE_RE.search(text)
    if m:
        meta.title = m.group(1).strip()

    m = _AUTHORS_RE.search(text)
    if m:
        meta.authors = [
            a.strip() for a in re.split(r"[;,，；]", m.group(1)) if a.strip()
        ]

    m = _YEAR_RE.search(text)
    if m:
        meta.year = int(m.group())

    m = _DOI_RE.search(text)
    if m:
        meta.doi = m.group(0)

    m = _JOURNAL_RE.search(text)
    if m:
        meta.journal = m.group(1).strip()

    if meta.authors:
        meta.first_author = meta.authors[0]
        meta.first_author_lastname = _extract_lastname(meta.first_author)

    return ExtractionContext(
        input=ctx.input,
        regex_meta=meta,
        llm_meta=ctx.llm_meta,
        errors=ctx.errors,
    )


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = PromptTemplate(
    system="You are a scientific paper metadata extractor.",
    user_template="""Extract metadata from the following academic paper page. Return as JSON:
{{
  "title": "Full paper title, or null if not found",
  "authors": ["Author1", "Author2", ...],
  "year": 2024,
  "doi": "10.xxx/xxx (without https://doi.org/), or null if not found",
  "journal": "Journal or conference name, or null if not found"
}}

Notes:
- If multiple DOIs appear from different articles, set doi to null.
- If authors not found, return [].
- year must be integer or null.
- Return only JSON, no explanation.

--- Paper Content ---
{header}""",
)

_ROBUST_PROMPT = PromptTemplate(
    system="You are a scientific paper metadata corrector.",
    user_template="""Regex-extracted metadata (may have OCR errors):
  title:   {regex_title}
  authors: {regex_authors}
  year:    {regex_year}
  doi:     {regex_doi}
  journal: {regex_journal}

Correct using the original text. Return as JSON:
{{
  "title": "Corrected title",
  "authors": ["Author1", ...],
  "year": 2024,
  "doi": "10.xxx/xxx",
  "journal": "Journal name"
}}

Notes:
- Fix common OCR errors (ln→In, rn→m, l→I, 0→O).
- Title truncation is common; cross-validate with abstract/introduction.
- Return only JSON.

--- Paper Content ---
{header}""",
)


# ---------------------------------------------------------------------------
# LLM stages
# ---------------------------------------------------------------------------


def extract_llm(
    ctx: ExtractionContext,
    llm_config: LLMConfigType,
    http_client: HTTPClient,
    api_key: str,
) -> ExtractionContext:
    """Stage 2 — LLM extraction (pure function with explicit dependencies)."""
    runner = LLMRunner(config=llm_config, http_client=http_client, api_key=api_key)
    request = LLMRequest(
        prompt=_EXTRACT_PROMPT.render(header=ctx.input.header),
        config=llm_config,
        purpose="extract.llm",
        json_mode=True,
    )
    result = runner.execute(request)
    data = json.loads(result.content)

    meta = PaperMetadata(source_file=ctx.input.source_name)
    meta.title = _clean_llm_str(data.get("title"))
    meta.authors = [a for a in (data.get("authors") or []) if a]
    meta.year = data.get("year") if isinstance(data.get("year"), int) else None
    meta.doi = _clean_llm_str(data.get("doi"))
    meta.journal = _clean_llm_str(data.get("journal"))

    if meta.authors:
        meta.first_author = meta.authors[0]
        meta.first_author_lastname = _extract_lastname(meta.first_author)

    return ExtractionContext(
        input=ctx.input,
        regex_meta=ctx.regex_meta,
        llm_meta=meta,
        errors=ctx.errors,
    )


def extract_llm_robust(
    ctx: ExtractionContext,
    llm_config: LLMConfigType,
    http_client: HTTPClient,
    api_key: str,
) -> ExtractionContext:
    """Stage 2 (robust) — LLM with regex context (pure function)."""
    regex = ctx.regex_meta or PaperMetadata(source_file=ctx.input.source_name)

    runner = LLMRunner(config=llm_config, http_client=http_client, api_key=api_key)
    request = LLMRequest(
        prompt=_ROBUST_PROMPT.render(
            regex_title=regex.title or "(not extracted)",
            regex_authors=", ".join(regex.authors)
            if regex.authors
            else "(not extracted)",
            regex_year=str(regex.year) if regex.year else "(not extracted)",
            regex_doi=regex.doi or "(not extracted)",
            regex_journal=regex.journal or "(not extracted)",
            header=ctx.input.header,
        ),
        config=llm_config,
        purpose="extract.robust",
        json_mode=True,
    )
    result = runner.execute(request)
    data = json.loads(result.content)

    meta = PaperMetadata(source_file=ctx.input.source_name)
    meta.title = _clean_llm_str(data.get("title"))
    meta.authors = [a for a in (data.get("authors") or []) if a]
    meta.year = data.get("year") if isinstance(data.get("year"), int) else None
    meta.journal = _clean_llm_str(data.get("journal"))

    # DOI validation: distrust LLM when multiple DOIs exist in the document.
    all_dois = set(_DOI_RE.findall(ctx.input.raw_text))
    llm_doi = _clean_llm_str(data.get("doi"))
    if len(all_dois) > 1:
        meta.doi = ""
    elif llm_doi and not regex.doi and llm_doi not in ctx.input.raw_text:
        meta.doi = ""
    else:
        meta.doi = llm_doi or regex.doi or ""

    if meta.authors:
        meta.first_author = meta.authors[0]
        meta.first_author_lastname = _extract_lastname(meta.first_author)

    return ExtractionContext(
        input=ctx.input,
        regex_meta=ctx.regex_meta,
        llm_meta=meta,
        errors=ctx.errors,
    )


# ---------------------------------------------------------------------------
# Merge stage
# ---------------------------------------------------------------------------


def merge_to_output(ctx: ExtractionContext) -> ExtractionOutput:
    """Final stage — merge context to output, applying filename fallbacks."""
    if ctx.llm_meta:
        meta, method, confidence = ctx.llm_meta, "llm", 0.9
    elif ctx.regex_meta:
        meta, method, confidence = ctx.regex_meta, "regex", 0.8
    else:
        meta = PaperMetadata(source_file=ctx.input.source_name)
        method, confidence = "empty", 0.0

    fallback_used = False
    stem = ctx.input.source_name
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem

    year_m = re.search(r"(19|20)\d{2}", stem)
    author_m = re.search(r"^([A-Z][a-z]+)", stem)

    if not meta.title and stem:
        cleaned = re.sub(r"(19|20)\d{2}", "", stem).strip("_- ")
        if author_m:
            cleaned = cleaned.replace(author_m.group(1), "").strip("_- ")
        if cleaned:
            meta.title = cleaned
            fallback_used = True

    if not meta.year and year_m:
        meta.year = int(year_m.group())
        fallback_used = True

    if not meta.first_author and author_m:
        author = author_m.group(1)
        meta.first_author = author
        meta.first_author_lastname = _extract_lastname(author)
        fallback_used = True

    return ExtractionOutput(
        metadata=meta,
        method=method,
        confidence=confidence,
        fallback_used=fallback_used,
    )


# ---------------------------------------------------------------------------
# Pipeline factory
# ---------------------------------------------------------------------------


def create_pipeline(
    mode: str,
    llm_config: LLMConfigType | None = None,
    http_client: HTTPClient | None = None,
    api_key: str = "",
):
    """
    Return an ``ExtractionInput → ExtractionOutput`` callable.

    Mode is one of: ``"regex"`` (default), ``"llm"``, ``"auto"``, ``"robust"``.
    """
    cfg = extractor_config_from_string(mode)
    has_llm = bool(api_key and llm_config and http_client)

    if cfg.robust:

        def _robust(inp: ExtractionInput) -> ExtractionOutput:
            ctx = ExtractionContext(input=inp)
            ctx = extract_regex(ctx)
            if has_llm:
                try:
                    ctx = extract_llm_robust(ctx, llm_config, http_client, api_key)  # type: ignore[arg-type]
                except Exception as exc:
                    _log.warning("Robust LLM stage failed: %s", exc)
            return merge_to_output(ctx)

        return _robust

    if cfg.fallback:

        def _auto(inp: ExtractionInput) -> ExtractionOutput:
            ctx = ExtractionContext(input=inp)
            ctx = extract_regex(ctx)
            rm = ctx.regex_meta
            needs_llm = not rm or not rm.title or (not rm.first_author and not rm.year)
            if needs_llm and has_llm:
                try:
                    ctx = extract_llm(ctx, llm_config, http_client, api_key)  # type: ignore[arg-type]
                except Exception as exc:
                    _log.warning("Auto LLM fallback failed: %s", exc)
            return merge_to_output(ctx)

        return _auto

    if cfg.use_llm:

        def _llm_only(inp: ExtractionInput) -> ExtractionOutput:
            ctx = ExtractionContext(input=inp)
            if has_llm:
                try:
                    ctx = extract_llm(ctx, llm_config, http_client, api_key)  # type: ignore[arg-type]
                except Exception as exc:
                    _log.warning("LLM extraction failed: %s", exc)
            return merge_to_output(ctx)

        return _llm_only

    def _regex_only(inp: ExtractionInput) -> ExtractionOutput:
        return merge_to_output(extract_regex(ExtractionContext(input=inp)))

    return _regex_only


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def extract(input: ExtractionInput, config: AppConfig) -> ExtractionOutput:
    """
    Extract metadata from a paper — main entry point.

    Uses ``config.ingest.extractor`` to select the strategy.
    Creates a short-lived HTTP client; callers that already have one
    should use ``create_pipeline`` directly.
    """
    _log.debug("Extracting: %s", input.source_name)

    http_client = RequestsClient()
    pipeline = create_pipeline(
        mode=config.ingest.extractor,
        llm_config=config.llm,
        http_client=http_client,
        api_key=config.resolve_llm_api_key(),
    )
    output = pipeline(input)

    _log.debug(
        "Extraction: method=%s confidence=%.2f", output.method, output.confidence
    )
    return output


def extract_file(filepath: str | Path, config: AppConfig) -> ExtractionOutput:
    """Convenience wrapper: extract from a file path."""
    return extract(ExtractionInput.from_file(Path(filepath)), config)
