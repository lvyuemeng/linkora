"""
PDF to Markdown converter using MinerU service.

This module provides PDF to Markdown conversion via local MinerU API or cloud API.
Supports single file conversion and batch processing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import requests

from scholaraio.log import get_logger

_log = get_logger(__name__)

# ============================================================================
#  Constants
# ============================================================================

DEFAULT_API_URL = "http://localhost:8000"
PARSE_ENDPOINT = "/file_parse"

VALID_BACKENDS = [
    "pipeline",
    "vlm-auto-engine",
    "vlm-http-client",
    "hybrid-auto-engine",
    "hybrid-http-client",
]

DEFAULT_BACKEND = "pipeline"
DEFAULT_LANG = "ch"
API_TIMEOUT = 600  # PDF parsing can take a long time

CLOUD_API_URL = "https://mineru.net/api/v4"
CLOUD_POLL_INTERVAL = 5  # seconds between status checks
CLOUD_TIMEOUT = 600  # max wait time for cloud parsing
CLOUD_BATCH_SIZE = 20  # max files per batch request


# ============================================================================
#  ParseOptions
# ============================================================================


@dataclass(frozen=True)
class ParseOptions:
    """Immutable options for PDF parsing."""

    backend: str = "pipeline"
    lang: str = "ch"
    parse_method: str = "auto"
    formula_enable: bool = True
    table_enable: bool = True
    start_page: int = 0
    end_page: int = 99999
    save_content_list: bool = False
    output_dir: Path | None = None
    force: bool = False
    dry_run: bool = False


# ============================================================================
#  Client Protocol (like vectors.py Embedder Protocol)
# ============================================================================


class PDFClient(Protocol):
    """Protocol for PDF parsing clients (local MinerU or cloud API)."""

    @property
    def name(self) -> str:
        """Client name identifier."""
        ...

    def check_health(self) -> bool:
        """Check if service is available."""
        ...

    def call(self, pdf_path: Path, opts: ParseOptions) -> dict:
        """Call the parsing API with the PDF.

        Args:
            pdf_path: Path to PDF file.
            opts: Parse options.

        Returns:
            Raw API response dict.
        """
        ...


# ============================================================================
#  Client Implementations
# ============================================================================


@dataclass(frozen=True)
class LocalClient:
    """Local MinerU API client."""

    base_url: str = DEFAULT_API_URL
    timeout: int = API_TIMEOUT

    @property
    def name(self) -> str:
        return "local"

    def check_health(self) -> bool:
        """Check if local MinerU service is available."""
        try:
            resp = requests.get(f"{self.base_url}/docs", timeout=5)
            return resp.status_code == 200
        except requests.ConnectionError:
            return False

    def call(self, pdf_path: Path, opts: ParseOptions) -> dict:
        """Call local MinerU API to parse PDF."""
        url = f"{self.base_url}{PARSE_ENDPOINT}"

        form_data = {
            "backend": (None, opts.backend),
            "parse_method": (None, opts.parse_method),
            "formula_enable": (None, str(opts.formula_enable).lower()),
            "table_enable": (None, str(opts.table_enable).lower()),
            "return_md": (None, "true"),
            "return_middle_json": (None, "false"),
            "return_content_list": (None, str(opts.save_content_list).lower()),
            "return_model_output": (None, "false"),
            "return_images": (None, "false"),
            "start_page_id": (None, str(opts.start_page)),
            "end_page_id": (None, str(opts.end_page)),
        }

        with open(pdf_path, "rb") as f:
            files = {
                "files": (pdf_path.name, f, "application/pdf"),
            }
            form_data["lang_list"] = (None, opts.lang)

            resp = requests.post(
                url, files={**files, **form_data}, timeout=self.timeout
            )

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        return resp.json()


@dataclass(frozen=True)
class CloudClient:
    """MinerU cloud API client."""

    api_key: str
    base_url: str = CLOUD_API_URL
    timeout: int = API_TIMEOUT

    @property
    def name(self) -> str:
        return "cloud"

    def check_health(self) -> bool:
        """Check cloud API availability."""
        try:
            resp = requests.get(
                f"{self.base_url}/health",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def call(self, pdf_path: Path, opts: ParseOptions) -> dict:
        """Call cloud API to parse PDF (upload -> poll -> download)."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Step 1: get signed upload URL
        data_id = pdf_path.stem
        payload: dict = {
            "files": [{"name": pdf_path.name, "data_id": data_id}],
            "model_version": opts.backend,
            "enable_formula": opts.formula_enable,
            "enable_table": opts.table_enable,
            "language": opts.lang,
        }
        if opts.parse_method == "ocr":
            payload["is_ocr"] = True

        resp = requests.post(
            f"{self.base_url}/file-urls/batch",
            headers=headers,
            json=payload,
            timeout=30,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Upload request failed: HTTP {resp.status_code}")

        resp_data = resp.json()
        if resp_data.get("code") != 0:
            raise RuntimeError(f"API error: {resp_data.get('msg')}")

        batch_data = resp_data.get("data", {})
        batch_id = batch_data.get("batch_id", "")
        file_urls = batch_data.get("file_urls", [])

        if not file_urls:
            raise RuntimeError("No upload URL returned")

        upload_url = (
            file_urls[0]
            if isinstance(file_urls[0], str)
            else file_urls[0].get("url", "")
        )

        # Step 2: upload PDF
        with open(pdf_path, "rb") as f:
            put_resp = requests.put(upload_url, data=f, timeout=120)
        if put_resp.status_code not in (200, 201):
            raise RuntimeError(f"Upload failed: HTTP {put_resp.status_code}")

        # Step 3: poll for result
        poll_headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.time() + CLOUD_TIMEOUT

        while time.time() < deadline:
            time.sleep(CLOUD_POLL_INTERVAL)
            try:
                poll_resp = requests.get(
                    f"{self.base_url}/extract-results/batch/{batch_id}",
                    headers=poll_headers,
                    timeout=30,
                )
            except requests.RequestException:
                continue

            if poll_resp.status_code != 200:
                continue

            try:
                poll_data = poll_resp.json()
            except ValueError:
                continue
            if poll_data.get("code") != 0:
                continue

            extract_results = poll_data.get("data", {}).get("extract_result", [])
            if not extract_results:
                continue

            item = extract_results[0]
            state = item.get("state", "")

            if state == "failed":
                raise RuntimeError(f"Cloud parse failed: {item.get('err_msg')}")

            if state == "done":
                return self._download_result(item, opts)

            if state == "running":
                extracted = item.get("extracted_pages", "?")
                total = item.get("total_pages", "?")
                _log.debug("cloud parsing... %s/%s pages", extracted, total)

        raise RuntimeError(f"Cloud parse timeout ({CLOUD_TIMEOUT}s)")

    def _download_result(self, item: dict, opts: ParseOptions) -> dict:
        """Download and extract markdown from cloud result."""
        # Try direct md_content first
        md = item.get("md_content")
        if isinstance(md, str) and md.strip():
            return {"md_content": md}

        # Try full_zip_url
        zip_url = item.get("full_zip_url")
        if zip_url:
            try:
                import io
                import zipfile

                resp = requests.get(
                    zip_url, timeout=120, proxies={"http": None, "https": None}  # type: ignore[arg-type]
                )
                if resp.status_code == 200:
                    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                        for name in zf.namelist():
                            if name.endswith(".md"):
                                return {"md_content": zf.read(name).decode("utf-8")}
            except Exception as e:
                _log.debug("failed to download/extract zip: %s", e)

        # Try md_url
        md_url = item.get("md_url")
        if md_url:
            try:
                resp = requests.get(
                    md_url, timeout=60, proxies={"http": None, "https": None}  # type: ignore[arg-type]
                )
                if resp.status_code == 200:
                    return {"md_content": resp.text}
            except Exception as e:
                _log.debug("failed to download md: %s", e)

        raise RuntimeError("No markdown content in cloud result")


# ============================================================================
#  Separated Middle States (each stage has own state, non-null fields only)
# ============================================================================


# Stage 1: Initial input
@dataclass(frozen=True)
class PDFInput:
    """Stage 1: PDF input with options."""

    pdf_path: Path
    opts: ParseOptions


# Stage 2: After API call (response)
@dataclass(frozen=True)
class APIResponse:
    """Stage 2: API response with timing."""

    pdf_path: Path
    response: dict  # raw API response
    elapsed: float  # API call time


# Stage 3: After content extraction
@dataclass(frozen=True)
class ExtractedContent:
    """Stage 3: Extracted markdown content."""

    pdf_path: Path
    content: str  # markdown content
    opts: ParseOptions  # needed for output path


# Stage 4: After file saved (final result)
@dataclass(frozen=True)
class ParseResult:
    """Stage 4: Final result - all fields non-null."""

    pdf_path: Path
    md_path: Path
    md_size: int
    elapsed: float  # total time


# Error state (any stage can fail)
@dataclass(frozen=True)
class ParseError:
    """Error state - replaces any stage on failure."""

    pdf_path: Path
    stage: str  # which stage failed
    error: str


# ============================================================================
#  PDFParser Class (with injected client)
# ============================================================================


class PDFParser:
    """PDF Parser with injectable client - no cloud/local branching inside."""

    def __init__(self, client: PDFClient):
        """Initialize PDF parser with client.

        Args:
            client: PDFClient implementation (LocalClient or CloudClient).
        """
        self._client = client

    @property
    def client_name(self) -> str:
        """Client name identifier."""
        return self._client.name

    def check_health(self) -> bool:
        """Check if parser service is available."""
        return self._client.check_health()

    def _output_path(self, pdf_path: Path, opts: ParseOptions) -> Path:
        """Compute output markdown path."""
        out_dir = opts.output_dir if opts.output_dir else pdf_path.parent
        return out_dir / (pdf_path.stem + ".md")

    def _extract_markdown(self, data: dict) -> str | None:
        """Extract markdown text from MinerU API response."""
        if not isinstance(data, dict):
            return None

        # Primary path: results -> {filename} -> md_content
        results = data.get("results")
        if isinstance(results, dict):
            for _filename, entry in results.items():
                if isinstance(entry, dict):
                    md = entry.get("md_content")
                    if isinstance(md, str) and md.strip():
                        return md

        # Fallback: direct md_content at top level
        for key in ("md_content", "md", "markdown", "content"):
            if key in data and isinstance(data[key], str) and data[key].strip():
                return data[key]

        return None

    def _extract_field(self, data: dict, field_name: str) -> dict | None:
        """Extract a named field from API response."""
        if not isinstance(data, dict):
            return None
        results = data.get("results")
        if isinstance(results, dict):
            for _filename, entry in results.items():
                if isinstance(entry, dict) and field_name in entry:
                    return entry[field_name]
        return data.get(field_name)

    def _fmt_size(self, nbytes: int) -> str:
        """Format byte count as human-readable string."""
        if nbytes < 1024:
            return f"{nbytes} B"
        elif nbytes < 1024 * 1024:
            return f"{nbytes / 1024:.1f} KB"
        else:
            return f"{nbytes / (1024 * 1024):.1f} MB"

    # Consuming: Stage 1 -> Stage 2
    def call_api(self, pdf_input: PDFInput) -> APIResponse | ParseError:
        """Consume PDFInput, produce APIResponse or error."""
        t0 = time.time()
        try:
            response = self._client.call(pdf_input.pdf_path, pdf_input.opts)
            return APIResponse(
                pdf_path=pdf_input.pdf_path,
                response=response,
                elapsed=time.time() - t0,
            )
        except Exception as e:
            return ParseError(
                pdf_path=pdf_input.pdf_path,
                stage="api",
                error=str(e),
            )

    # Consuming: Stage 2 -> Stage 3
    def extract(self, api_response: APIResponse) -> ExtractedContent | ParseError:
        """Consume APIResponse, produce ExtractedContent or error."""
        content = self._extract_markdown(api_response.response)
        if content is None:
            keys = list(api_response.response.keys()) if isinstance(
                api_response.response, dict
            ) else type(api_response.response).__name__
            return ParseError(
                pdf_path=api_response.pdf_path,
                stage="extract",
                error=f"No markdown content in response. Keys: {keys}",
            )

        return ExtractedContent(
            pdf_path=api_response.pdf_path,
            content=content,
            opts=ParseOptions(),  # Default options
        )

    # Consuming: Stage 3 -> Stage 4
    def save(self, extracted: ExtractedContent) -> ParseResult | ParseError:
        """Consume ExtractedContent, produce ParseResult or error."""
        md_path = self._output_path(extracted.pdf_path, extracted.opts)
        opts = extracted.opts

        # Create output directory
        out_dir = md_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        # Dry run
        if opts.dry_run:
            exists_tag = " (exists, would overwrite)" if md_path.exists() else ""
            _log.debug("dry-run: %s%s", md_path.name, exists_tag)
            return ParseResult(
                pdf_path=extracted.pdf_path,
                md_path=md_path,
                md_size=0,
                elapsed=0.0,
            )

        # Skip if already exists
        if md_path.exists() and not opts.force:
            _log.debug("skip (already exists): %s", md_path.name)
            return ParseResult(
                pdf_path=extracted.pdf_path,
                md_path=md_path,
                md_size=md_path.stat().st_size,
                elapsed=0.0,
            )

        # Write markdown
        md_path.write_text(extracted.content, encoding="utf-8")
        md_size = len(extracted.content.encode("utf-8"))

        _log.info("-> %s (%s)", md_path.name, self._fmt_size(md_size))

        return ParseResult(
            pdf_path=extracted.pdf_path,
            md_path=md_path,
            md_size=md_size,
            elapsed=0.0,
        )

    # Full pipeline: Stage 1 -> Stage 4
    def parse(
        self, pdf_path: Path, opts: ParseOptions | None = None
    ) -> ParseResult | ParseError:
        """Full pipeline using consuming pattern.

        Args:
            pdf_path: Path to PDF file.
            opts: Parse options (uses defaults if None).

        Returns:
            ParseResult on success, ParseError on failure.
        """
        if opts is None:
            opts = ParseOptions()

        # Stage 1 -> 2
        pdf_input = PDFInput(pdf_path=pdf_path, opts=opts)
        result = self.call_api(pdf_input)
        if isinstance(result, ParseError):
            return result

        # Stage 2 -> 3
        result = self.extract(result)
        if isinstance(result, ParseError):
            return result

        # Stage 3 -> 4
        return self.save(result)

    # Batch processing
    def parse_batch(
        self,
        pdf_paths: list[Path],
        opts: ParseOptions | None = None,
        *,
        force: bool = False,
    ) -> list[ParseResult | ParseError]:
        """Batch parse using same separated states.

        Args:
            pdf_paths: List of PDF file paths.
            opts: Parse options (uses defaults if None).
            force: Force re-parse even if output exists.

        Returns:
            List of ParseResult or ParseError for each input.
        """
        if opts is None:
            opts = ParseOptions()

        results: list[ParseResult | ParseError] = []
        for pdf_path in pdf_paths:
            # Skip existing unless force
            if not force:
                md_path = self._output_path(pdf_path, opts)
                if md_path.exists():
                    _log.debug("skip (already exists): %s", md_path.name)
                    results.append(
                        ParseResult(
                            pdf_path=pdf_path,
                            md_path=md_path,
                            md_size=md_path.stat().st_size,
                            elapsed=0.0,
                        )
                    )
                    continue

            result = self.parse(pdf_path, opts)
            results.append(result)

        return results


