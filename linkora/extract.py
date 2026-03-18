"""
extract.py — Metadata Extraction from Paper Markdown

Provides extraction pipeline with multiple implementations:

  RegexExtractor    — Regex-based extraction (default)
  LLMExtractor      — LLM API extraction (OpenAI-compatible)
  AutoExtractor     — Regex first, fallback to LLM
  RobustExtractor   — Regex + LLM dual-run, LLM corrects OCR errors

Usage:
    from linkora.extract import extract, create_extractor

    # Option 1: Via config
    output = extract(input, config)

    # Option 2: Direct
    extractor = create_extractor(
        config=ExtractorConfig(robust=True),
        llm_config=config.llm,
        http_client=RequestsClient(),
        api_key="sk-..."
    )
    output = extractor.extract(input)
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Optional

from linkora.config import Config
from linkora.http import HTTPClient, RequestsClient
from linkora.llm import (
    LLMRunner,
    LLMRequest,
    LLMConfig as LLMConfigType,
    PromptTemplate,
)
from linkora.log import get_logger
from linkora.papers import PaperMetadata

_log = get_logger(__name__)

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


# ============================================================================
#  Data Types
# ============================================================================


@dataclass(frozen=True)
class ExtractionInput:
    """Immutable input for metadata extraction.

    Attributes:
        source_name: Original filename
        raw_text: Full markdown content
        header: First N chars for LLM
        file_hash: MD5 hash for caching
    """

    source_name: str
    raw_text: str
    header: str
    file_hash: str = ""

    @classmethod
    def from_file(cls, filepath: Path, header_size: int = 50000) -> ExtractionInput:
        text = filepath.read_text(encoding="utf-8", errors="replace")
        return cls(
            source_name=filepath.name,
            raw_text=text,
            header=text[:header_size],
            file_hash=hashlib.md5(text.encode()).hexdigest(),
        )

    @classmethod
    def from_text(
        cls, name: str, text: str, header_size: int = 50000
    ) -> ExtractionInput:
        return cls(
            source_name=name,
            raw_text=text,
            header=text[:header_size],
            file_hash=hashlib.md5(text.encode()).hexdigest(),
        )


@dataclass(frozen=True)
class ExtractionContext:
    """Immutable context passed through extraction pipeline.

    Attributes:
        input: ExtractionInput
        regex_meta: Metadata from regex (if run)
        llm_meta: Metadata from LLM (if run)
        errors: List of errors encountered
    """

    input: ExtractionInput
    regex_meta: Optional[PaperMetadata] = None
    llm_meta: Optional[PaperMetadata] = None
    errors: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.errors is None:
            object.__setattr__(self, "errors", [])


@dataclass(frozen=True)
class ExtractionOutput:
    """Immutable output with confidence metadata."""

    metadata: PaperMetadata
    method: str
    confidence: float
    fallback_used: bool


@dataclass(frozen=True)
class ExtractorConfig:
    """Data object for extractor selection - no string dispatch."""

    use_llm: bool = False
    fallback: bool = False
    robust: bool = False


# ============================================================================
#  Protocol
# ============================================================================


class Extractor(Protocol):
    """Protocol for metadata extractors."""

    @property
    def name(self) -> str: ...

    def extract(self, input: ExtractionInput) -> ExtractionOutput: ...


# ============================================================================
#  Pure Functions
# ============================================================================


def extractor_config_from_string(mode: str) -> ExtractorConfig:
    """Create config from mode string."""
    return ExtractorConfig(
        use_llm=mode == "llm", fallback=mode == "auto", robust=mode == "robust"
    )


def _clean_llm_str(val: str | None) -> str:
    """Clean LLM output."""
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("null", "none", "n/a", ""):
        return ""
    return s


# ============================================================================
#  Pipeline Stages (Pure Functions)
# ============================================================================


# Regex patterns
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_AUTHORS_RE = re.compile(r"(?:Authors?|作者)[:：]\s*(.+?)(?:\n|$)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DOI_RE = re.compile(r"10\.\d{4,}/[^\s\]>]+")
_JOURNAL_RE = re.compile(r"(?:Journal|期刊|会议)[:：]\s*(.+?)(?:\n|$)", re.IGNORECASE)


def extract_regex(ctx: ExtractionContext) -> ExtractionContext:
    """Stage 1: Regex extraction - pure function.

    Args:
        ctx: ExtractionContext with input

    Returns:
        Updated context with regex_meta
    """
    text = ctx.input.raw_text
    meta = PaperMetadata(source_file=ctx.input.source_name)

    # Title from first H1
    title_match = _TITLE_RE.search(text)
    if title_match:
        meta.title = title_match.group(1).strip()

    # Authors
    authors_match = _AUTHORS_RE.search(text)
    if authors_match:
        authors_str = authors_match.group(1)
        authors = re.split(r"[;,，；]", authors_str)
        meta.authors = [a.strip() for a in authors if a.strip()]

    # Year
    year_match = _YEAR_RE.search(text)
    if year_match:
        meta.year = int(year_match.group())

    # DOI
    doi_match = _DOI_RE.search(text)
    if doi_match:
        meta.doi = doi_match.group(0)

    # Journal
    journal_match = _JOURNAL_RE.search(text)
    if journal_match:
        meta.journal = journal_match.group(1).strip()

    # Set first author
    if meta.authors:
        meta.first_author = meta.authors[0]
        meta.first_author_lastname = _extract_lastname(meta.first_author)

    # Return updated context
    return ExtractionContext(
        input=ctx.input, regex_meta=meta, llm_meta=ctx.llm_meta, errors=ctx.errors
    )


# LLM prompts (English)
_EXTRACT_PROMPT = PromptTemplate(
    system="You are a scientific paper metadata extractor.",
    user_template="""Extract metadata from the following academic paper page. Return as JSON with fields:
{{
  "title": "Full paper title, or null if not found",
  "authors": ["Author1", "Author2", ...],
  "year": 2024,
  "doi": "10.xxx/xxx (without https://doi.org/), or null if not found",
  "journal": "Journal or conference name, or null if not found"
}}

Notes:
- Journal scans (Nature, Science) may contain multiple article fragments. Identify the main article with complete structure (title + authors + body)
- If multiple DOIs appear from different articles, DOI is not trustworthy - set to null
- If authors not found, return empty list []
- year must be integer or null
- Return only JSON, no explanations

--- Paper Content ---
{header}""",
)


_ROBUST_PROMPT = PromptTemplate(
    system="You are a scientific paper metadata corrector.",
    user_template="""The following metadata was extracted using regex from an OCR-converted academic paper. There may be OCR errors or missing fields. Please correct and complete using the original text.

Regex extracted:
  title:   {regex_title}
  authors: {regex_authors}
  year:    {regex_year}
  doi:     {regex_doi}
  journal: {regex_journal}

Return as JSON:
{{
  "title": "Corrected complete title",
  "authors": ["Author1", "Author2", ...],
  "year": 2024,
  "doi": "10.xxx/xxx",
  "journal": "Journal name"
}}

Notes:
- Trust the original paper text over regex results
- Fix OCR errors (ln→In, rn→m, l→I, 0→O, etc.)
- Title truncation is common on cover pages. Cross-validate with full text (abstract, introduction, header) for complete title
- Return only JSON

--- Paper Content ---
{header}""",
)


def extract_llm(
    ctx: ExtractionContext,
    llm_config: LLMConfigType,
    http_client: HTTPClient,
    api_key: str,
) -> ExtractionContext:
    """Stage 2: LLM extraction - pure function with DI.

    Args:
        ctx: ExtractionContext with input
        llm_config: LLM configuration
        http_client: HTTP client (Protocol)
        api_key: API key

    Returns:
        Updated context with llm_meta
    """
    # Build prompt
    prompt = _EXTRACT_PROMPT.render(header=ctx.input.header)

    # Call LLM
    runner = LLMRunner(config=llm_config, http_client=http_client, api_key=api_key)

    request = LLMRequest(
        prompt=prompt, config=llm_config, purpose="extract.llm", json_mode=True
    )

    result = runner.execute(request)

    # Parse response
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
        input=ctx.input, regex_meta=ctx.regex_meta, llm_meta=meta, errors=ctx.errors
    )


def extract_llm_robust(
    ctx: ExtractionContext,
    llm_config: LLMConfigType,
    http_client: HTTPClient,
    api_key: str,
) -> ExtractionContext:
    """Stage 2 (robust): LLM with regex results - pure function with DI."""
    # Build prompt with regex results
    regex = ctx.regex_meta

    # Handle case where regex hasn't run
    if regex is None:
        regex = PaperMetadata(source_file=ctx.input.source_name)

    prompt = _ROBUST_PROMPT.render(
        regex_title=regex.title or "(not extracted)",
        regex_authors=", ".join(regex.authors) if regex.authors else "(not extracted)",
        regex_year=str(regex.year) if regex.year else "(not extracted)",
        regex_doi=regex.doi or "(not extracted)",
        regex_journal=regex.journal or "(not extracted)",
        header=ctx.input.header,
    )

    runner = LLMRunner(config=llm_config, http_client=http_client, api_key=api_key)

    request = LLMRequest(
        prompt=prompt, config=llm_config, purpose="extract.robust", json_mode=True
    )

    result = runner.execute(request)
    data = json.loads(result.content)

    meta = PaperMetadata(source_file=ctx.input.source_name)
    meta.title = _clean_llm_str(data.get("title"))
    meta.authors = [a for a in (data.get("authors") or []) if a]
    meta.year = data.get("year") if isinstance(data.get("year"), int) else None

    # DOI validation
    text = ctx.input.raw_text
    all_dois = set(_DOI_RE.findall(text))
    multi_doi = len(all_dois) > 1

    llm_doi = _clean_llm_str(data.get("doi"))
    if multi_doi:
        meta.doi = ""
    elif llm_doi and regex and not regex.doi and llm_doi not in text:
        meta.doi = ""
    else:
        meta.doi = llm_doi or (regex.doi if regex else "")

    meta.journal = _clean_llm_str(data.get("journal"))

    if meta.authors:
        meta.first_author = meta.authors[0]
        meta.first_author_lastname = _extract_lastname(meta.first_author)

    return ExtractionContext(
        input=ctx.input, regex_meta=ctx.regex_meta, llm_meta=meta, errors=ctx.errors
    )


def merge_to_output(ctx: ExtractionContext) -> ExtractionOutput:
    """Final stage: Merge context to output - pure function.

    Encapsulates filename fallback in pipeline.
    """
    # Determine final metadata based on mode
    if ctx.llm_meta:
        meta = ctx.llm_meta
        method = "llm"
        confidence = 0.9
    elif ctx.regex_meta:
        meta = ctx.regex_meta
        method = "regex"
        confidence = 0.8
    else:
        meta = PaperMetadata(source_file=ctx.input.source_name)
        method = "empty"
        confidence = 0.0

    # Filename fallback - encapsulated in pipeline
    fallback_used = False
    name = ctx.input.source_name

    # Extract from filename for fallback only
    name_stem = name.split(".")[0] if "." in name else name
    year_match = re.search(r"(19|20)\d{2}", name_stem)
    author_match = re.search(r"^([A-Z][a-z]+)", name_stem)

    if not meta.title and name_stem:
        # Use filename stem as title fallback
        cleaned = re.sub(r"(19|20)\d{2}", "", name_stem).strip("_- ")
        if author_match:
            cleaned = cleaned.replace(author_match.group(1), "").strip("_- ")
        if cleaned:
            meta.title = cleaned
            fallback_used = True

    if not meta.year and year_match:
        meta.year = int(year_match.group())
        fallback_used = True

    if not meta.first_author and author_match:
        author = author_match.group(1)
        meta.first_author = author
        meta.first_author_lastname = _extract_lastname(author)
        fallback_used = True

    return ExtractionOutput(
        metadata=meta, method=method, confidence=confidence, fallback_used=fallback_used
    )


# ============================================================================
#  Pipeline Factory
# ============================================================================


def create_pipeline(
    mode: str,
    llm_config: LLMConfigType | None = None,
    http_client: HTTPClient | None = None,
    api_key: str = "",
):
    """Create extraction pipeline - function composition.

    Returns a function: ExtractionInput -> ExtractionOutput
    """
    config = extractor_config_from_string(mode)

    if config.robust:

        def pipeline(input: ExtractionInput) -> ExtractionOutput:
            ctx = ExtractionContext(input=input)
            ctx = extract_regex(ctx)
            if api_key and llm_config and http_client:
                try:
                    ctx = extract_llm_robust(ctx, llm_config, http_client, api_key)
                except Exception as e:
                    ctx.errors.append(str(e))
            return merge_to_output(ctx)

        return pipeline

    if config.fallback:

        def pipeline_fallback(input: ExtractionInput) -> ExtractionOutput:
            ctx = ExtractionContext(input=input)
            ctx = extract_regex(ctx)

            # Check if we need LLM fallback
            regex_meta = ctx.regex_meta
            needs_llm = (
                regex_meta is None
                or not regex_meta.title
                or (not regex_meta.first_author and not regex_meta.year)
            )

            if needs_llm and api_key and llm_config and http_client:
                try:
                    ctx = extract_llm(ctx, llm_config, http_client, api_key)
                except Exception as e:
                    ctx.errors.append(str(e))

            return merge_to_output(ctx)

        return pipeline_fallback

    if config.use_llm:

        def pipeline_llm(input: ExtractionInput) -> ExtractionOutput:
            ctx = ExtractionContext(input=input)
            if api_key and llm_config and http_client:
                try:
                    ctx = extract_llm(ctx, llm_config, http_client, api_key)
                except Exception as e:
                    ctx.errors.append(str(e))
            return merge_to_output(ctx)

        return pipeline_llm

    # Default: regex only
    def pipeline_regex(input: ExtractionInput) -> ExtractionOutput:
        ctx = ExtractionContext(input=input)
        ctx = extract_regex(ctx)
        return merge_to_output(ctx)

    return pipeline_regex


# ============================================================================
#  Main Entry Points
# ============================================================================


def extract(input: ExtractionInput, config: Config) -> ExtractionOutput:
    """Extract metadata - main entry point."""
    _log.debug("Starting extraction for: %s", input.source_name)

    http_client = RequestsClient()

    pipeline = create_pipeline(
        mode=config.ingest.extractor,
        llm_config=config.llm,
        http_client=http_client,
        api_key=config.resolve_llm_api_key(),
    )

    output = pipeline(input)

    _log.debug(
        "Extraction complete: method=%s, confidence=%.2f",
        output.method,
        output.confidence,
    )

    return output


def extract_file(filepath: str | Path, config: Config) -> ExtractionOutput:
    """Convenience: extract from file path."""
    input = ExtractionInput.from_file(Path(filepath))
    return extract(input, config)


# ============================================================================
#  Backward Compatibility
# ============================================================================
