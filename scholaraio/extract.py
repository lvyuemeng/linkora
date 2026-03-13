"""
extract.py — Metadata Extraction from Paper Markdown
===================================================

Provides four implementations (from MinerU markdown extract title/authors/year/doi/journal):

  RegexExtractor    — Regex-based extraction (default)
  LLMExtractor      — LLM API extraction (OpenAI-compatible)
  FallbackExtractor — Regex first, fallback to LLM (auto mode)
  RobustExtractor   — Regex + LLM dual-run, LLM corrects OCR errors (robust mode)

Usage:
    from scholaraio.extract import get_extractor

    extractor = get_extractor(config)
    meta = extractor.extract(Path("paper.md"))
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

_log = logging.getLogger(__name__)

from scholaraio.config import Config, LLMConfig
from scholaraio.papers import PaperMetadata


# ============================================================================
#  Protocol
# ============================================================================


@runtime_checkable
class MetadataExtractor(Protocol):
    """Metadata extractor protocol - all extractors must implement this interface."""

    def extract(self, filepath: Path) -> "PaperMetadata":
        """Extract paper metadata from markdown file.

        Args:
            filepath: Path to MinerU output .md file.

        Returns:
            Filled PaperMetadata instance.
        """
        ...


# ============================================================================
#  Regex extractor (wraps existing metadata.py logic, zero changes there)
# ============================================================================


class RegexExtractor:
    """Pure regex metadata extractor.

    Wraps regex extraction logic from metadata module, no LLM calls.
    Fastest, suitable for papers with good OCR quality.
    """

    def extract(self, filepath: Path) -> "PaperMetadata":
        from scholaraio.ingest.metadata import extract_metadata_from_markdown

        return extract_metadata_from_markdown(filepath)


# ============================================================================
#  LLM extractor (OpenAI-compatible API)
# ============================================================================

_EXTRACT_PROMPT = """\
从以下学术论文页面提取元数据，以 JSON 格式返回，字段如下：
{{
  "title": "论文完整标题，找不到填 null",
  "authors": ["姓名1", "姓名2", ...],
  "year": 2024,
  "doi": "10.xxx/xxx（不含 https://doi.org/，找不到填 null）",
  "journal": "期刊或会议名称，找不到填 null"
}}

注意：
- 期刊扫描页（如 Nature、Science）可能包含多篇文章片段。请识别有完整结构（标题 + 作者 + 正文）的主文章，忽略仅出现片段的其他文章
- 如果文中出现多个 DOI（来自不同文章），说明 DOI 不可信，doi 字段填 null
- authors 找不到时填空列表 []
- year 必须是整数或 null
- 只返回 JSON，不要任何解释文字

--- 论文内容 ---
{header}"""


def _clean_llm_str(val) -> str:
    """Clean LLM output - sometimes returns string 'null'/'None' instead of JSON null."""
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("null", "none", "n/a", ""):
        return ""
    return s


class LLMExtractor:
    """Pure LLM metadata extractor (OpenAI-compatible API).

    Sends markdown header (first 80 lines) to LLM, returns structured metadata.
    Falls back to regex on API failure.

    Args:
        llm_config: LLM backend config.
        api_key: API key, reads from llm_config.api_key if empty.
    """

    def __init__(self, llm_config: "LLMConfig", api_key: str = ""):
        self._config = llm_config
        self._api_key = api_key or llm_config.api_key

    def extract(self, filepath: Path) -> "PaperMetadata":
        from scholaraio.ingest.metadata import (
            PaperMetadata,
            _extract_from_filename,
            _extract_lastname,
        )

        text = filepath.read_text(encoding="utf-8", errors="replace")
        header = text[:50000]

        try:
            raw_json = self._call_api(header)
            data = json.loads(raw_json)
        except Exception as e:
            _log.debug("[LLM] extraction failed: %s, falling back to regex", e)
            from scholaraio.ingest.metadata import extract_metadata_from_markdown

            return extract_metadata_from_markdown(filepath)

        meta = PaperMetadata(source_file=filepath.name)
        meta.title = _clean_llm_str(data.get("title"))
        meta.authors = [a for a in (data.get("authors") or []) if a]
        meta.year = data.get("year") if isinstance(data.get("year"), int) else None
        meta.doi = _clean_llm_str(data.get("doi"))
        meta.journal = _clean_llm_str(data.get("journal"))

        if meta.authors:
            meta.first_author = meta.authors[0]
            meta.first_author_lastname = _extract_lastname(meta.first_author)

        # Filename fallback for any missing fields
        fb = _extract_from_filename(filepath)
        if not meta.title:
            meta.title = fb.title
        if not meta.year:
            meta.year = fb.year
        if not meta.first_author_lastname:
            meta.first_author_lastname = fb.first_author_lastname
        if not meta.first_author:
            meta.first_author = fb.first_author

        return meta

    def _call_api(self, header_text: str) -> str:
        """POST to OpenAI-compatible chat completions endpoint."""
        from scholaraio.llm import LLMRunner, LLMRequest

        runner = LLMRunner(self._config, api_key=self._api_key)
        request = LLMRequest(
            prompt=_EXTRACT_PROMPT.format(header=header_text),
            config=self._config,
            purpose="extract.llm",
        )
        result = runner.execute(request)
        return result.content


# ============================================================================
#  Fallback extractor (regex → LLM if title missing)
# ============================================================================


class FallbackExtractor:
    """Regex-first, LLM-fallback metadata extractor (auto mode).

    Runs regex first; if key fields missing (title empty, or author AND year
    both empty), calls LLM to fill in.

    Args:
        llm_config: LLM backend config.
        api_key: API key.

    Raises:
        RuntimeError: Title missing and no API key configured.
    """

    def __init__(self, llm_config: "LLMConfig", api_key: str):
        self._regex = RegexExtractor()
        self._llm_config = llm_config
        self._api_key = api_key

    def extract(self, filepath: Path) -> "PaperMetadata":
        meta = self._regex.extract(filepath)

        needs_llm = not meta.title or (not meta.first_author and not meta.year)
        if not needs_llm:
            return meta

        reason = "title empty" if not meta.title else "author and year both empty"
        _log.debug("[extractor] regex incomplete (%s), trying LLM", reason)
        if not self._api_key:
            if meta.title:
                # title present but author/year missing: degrade to regex result
                _log.debug("[extractor] no LLM API key, using regex result")
                return meta
            raise RuntimeError(
                "regex 提取 title 失败，需要 LLM 兜底，但未配置 LLM API key。\n"
                "请在 config.local.yaml 中设置 llm.api_key，"
                "或设置环境变量 SCHOLARAIO_LLM_API_KEY / DEEPSEEK_API_KEY。"
            )
        return LLMExtractor(self._llm_config, api_key=self._api_key).extract(filepath)


# ============================================================================
#  Robust extractor (regex + LLM always)
# ============================================================================

_ROBUST_PROMPT = """\
以下是从一篇学术论文 PDF（经 OCR 转换为 markdown）中用正则提取的元数据，可能有 OCR 错误或缺失。
请对照论文原文内容，校正并补全元数据，以 JSON 格式返回。

正则提取结果：
  title:   {regex_title}
  authors: {regex_authors}
  year:    {regex_year}
  doi:     {regex_doi}
  journal: {regex_journal}

返回格式：
{{
  "title": "校正后的完整标题（修复 OCR 错误如连字、断字、乱码）",
  "authors": ["姓名1", "姓名2", ...],
  "year": 2024,
  "doi": "10.xxx/xxx（不含 https://doi.org/，找不到填 null）",
  "journal": "期刊或会议名称，找不到填 null"
}}

注意：
- 优先信任论文原文，正则结果仅作参考
- **学位论文处理**：如果检测到这是学位论文（博士/硕士论文、dissertation/thesis），请：
  1. 根据正文主体（非封面/摘要）判断论文的主要写作语言
  2. title 和 authors 使用主要语言版本（例如中文论文用中文标题和中文姓名，英文论文用英文）
  3. 学位论文通常有中英文双封面，不要因为正则提取到了英文封面就用英文——以正文语言为准
- **多篇文章识别**：期刊扫描页（如 Nature、Science）的 PDF 可能包含多篇文章的片段。
  请根据以下标准识别主文章：找到有完整结构（标题 + 作者 + 正文主体 + 结论/参考文献）的研究论文，
  忽略仅出现了尾部/参考文献/摘要片段的其他文章
- 忽略期刊栏目标题（如 PERSPECTIVES, EDITORIAL, NEWS, COMMENTARY, LETTERS, REVIEW 等），这些不是论文标题
- **PDF 解析错误修复**：输入的 markdown 由 PDF 解析器自动生成，可能存在以下问题，请结合上下文修正：
  - OCR 字符错误：ln→In, rn→m, l→I, 0→O 等
  - 标题/作者被截断或断行（尤其是封面页表格中的长标题，可能被拆成多行导致不完整）
  - 连字/断字未合并
  - 标题截断是常见问题：封面上的标题可能只有前半句。请务必与正文中出现的完整标题交叉验证（如摘要、引言首段、页眉等处），确保返回的是完整标题
- authors 找不到时填空列表 []
- year 必须是整数或 null
- 只返回 JSON，不要任何解释文字

--- 论文内容 ---
{header}"""


class RobustExtractor:
    """Regex + LLM dual-run metadata extractor (robust mode).

    Always runs regex first, then sends regex results + markdown to LLM
    to correct OCR errors and fill missing fields. One LLM call per paper.
    Falls back to regex result on LLM failure.

    Args:
        llm_config: LLM backend config.
        api_key: API key.
    """

    def __init__(self, llm_config: "LLMConfig", api_key: str):
        self._regex = RegexExtractor()
        self._llm_config = llm_config
        self._api_key = api_key

    def extract(self, filepath: Path) -> "PaperMetadata":
        from scholaraio.ingest.metadata import (
            PaperMetadata,
            _extract_from_filename,
            _extract_lastname,
        )

        # Step 1: regex
        regex_meta = self._regex.extract(filepath)

        # Step 2: scan full text for distinct DOIs (detect multi-paper PDFs)
        text = filepath.read_text(encoding="utf-8", errors="replace")
        all_dois = set(re.findall(r"10\.\d{4,}/[^\s)]+", text))
        multi_doi = len(all_dois) > 1

        # Step 3: LLM with regex results + paper content (up to 50k chars)
        header = text[:50000]

        prompt = _ROBUST_PROMPT.format(
            regex_title=regex_meta.title or "(未提取到)",
            regex_authors=", ".join(regex_meta.authors)
            if regex_meta.authors
            else "(未提取到)",
            regex_year=regex_meta.year or "(未提取到)",
            regex_doi=regex_meta.doi or "(未提取到)",
            regex_journal=regex_meta.journal or "(未提取到)",
            header=header,
        )

        try:
            raw_json = self._call_api(prompt)
            data = json.loads(raw_json)
        except Exception as e:
            _log.debug("[robust] LLM correction failed: %s, using regex result", e)
            return regex_meta

        # Build metadata from LLM response (with null-string cleanup)
        meta = PaperMetadata(source_file=filepath.name)
        meta.title = _clean_llm_str(data.get("title")) or regex_meta.title or ""
        meta.authors = [
            a for a in (data.get("authors") or []) if a
        ] or regex_meta.authors
        llm_year = data.get("year")
        meta.year = (llm_year if isinstance(llm_year, int) else None) or regex_meta.year
        # DOI: multi-DOI or hallucination guard
        if multi_doi:
            _log.debug(
                "[robust] found %d different DOIs in fulltext, discarding for title search",
                len(all_dois),
            )
            meta.doi = ""
        else:
            llm_doi = _clean_llm_str(data.get("doi")) or ""
            # If LLM produced a DOI that doesn't exist in the text and regex
            # didn't find it either, it's likely a hallucination — discard
            if llm_doi and not regex_meta.doi and llm_doi not in text:
                _log.debug(
                    "[robust] LLM DOI not found in source text, suspected hallucination, discarding"
                )
                meta.doi = ""
            else:
                meta.doi = llm_doi or regex_meta.doi or ""
        meta.journal = _clean_llm_str(data.get("journal")) or regex_meta.journal or ""

        if meta.authors:
            meta.first_author = meta.authors[0]
            meta.first_author_lastname = _extract_lastname(meta.first_author)

        # Filename fallback for anything still missing
        fb = _extract_from_filename(filepath)
        if not meta.title:
            meta.title = fb.title
        if not meta.year:
            meta.year = fb.year
        if not meta.first_author_lastname:
            meta.first_author_lastname = fb.first_author_lastname
        if not meta.first_author:
            meta.first_author = fb.first_author

        return meta

    def _call_api(self, prompt: str) -> str:
        from scholaraio.llm import LLMRunner, LLMRequest

        runner = LLMRunner(self._llm_config, api_key=self._api_key)
        request = LLMRequest(
            prompt=prompt,
            config=self._llm_config,
            purpose="extract.robust",
        )
        result = runner.execute(request)
        return result.content


# ============================================================================
#  Factory
# ============================================================================


def get_extractor(config: "Config") -> MetadataExtractor:
    """Get metadata extractor based on config.

    Args:
        config: Global config, reads from config.ingest.extractor for mode.

    Returns:
        MetadataExtractor implementation instance.

    Raises:
        RuntimeError: robust/llm mode without API key.

    Modes:
        - regex: Pure regex, no LLM (fastest)
        - auto: Regex first, LLM fallback for missing key fields
        - robust: Regex + LLM always, LLM corrects OCR errors
        - llm: Pure LLM, no regex
    """
    mode = config.ingest.extractor

    if mode == "llm":
        api_key = config.api_key("llm")
        if not api_key:
            _log.warning(
                "[LLM] no API key found; set SCHOLARAIO_LLM_API_KEY or llm.api_key in config.local.yaml"
            )
        return LLMExtractor(config.llm, api_key=api_key)

    if mode == "robust":
        api_key = config.api_key("llm")
        if not api_key:
            raise RuntimeError(
                "robust 模式需要 LLM API key。\n"
                "请在 config.local.yaml 中设置 llm.api_key，"
                "或设置环境变量 SCHOLARAIO_LLM_API_KEY / DEEPSEEK_API_KEY。"
            )
        return RobustExtractor(config.llm, api_key=api_key)

    if mode == "auto":
        return FallbackExtractor(config.llm, api_key=config.api_key("llm"))

    return RegexExtractor()
