"""
PDF to Markdown converter using MinerU service.

This module provides PDF to Markdown conversion via local MinerU API or cloud API.
Supports single file conversion and batch processing.
"""

from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tenacity import retry, stop_after_attempt, wait_exponential

from scholaraio.http import HTTPClient
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

# Parse result states
STATE_FAILED = "failed"
STATE_DONE = "done"
STATE_RUNNING = "running"


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

    http_client: HTTPClient
    base_url: str = DEFAULT_API_URL
    timeout: int = API_TIMEOUT

    @property
    def name(self) -> str:
        return "local"

    def check_health(self) -> bool:
        """Check if local MinerU service is available."""
        try:
            resp = self.http_client.get(f"{self.base_url}/docs", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _build_form_data(self, opts: ParseOptions) -> dict:
        """Build multipart form data for PDF parsing."""
        return {
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
            "lang_list": (None, opts.lang),
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def call(self, pdf_path: Path, opts: ParseOptions) -> dict:
        """Call local MinerU API to parse PDF."""
        url = f"{self.base_url}{PARSE_ENDPOINT}"
        form_data = self._build_form_data(opts)

        with open(pdf_path, "rb") as f:
            files = {"files": (pdf_path.name, f, "application/pdf")}
            resp = self.http_client.post(
                url,
                files={**files, **form_data},
                timeout=self.timeout,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.data}")

        return resp.json()


@dataclass(frozen=True)
class CloudClient:
    """MinerU cloud API client."""

    api_key: str
    http_client: HTTPClient
    base_url: str = CLOUD_API_URL
    timeout: int = API_TIMEOUT

    @property
    def name(self) -> str:
        return "cloud"

    def check_health(self) -> bool:
        """Check cloud API availability."""
        try:
            resp = self.http_client.get(
                f"{self.base_url}/health",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def call(self, pdf_path: Path, opts: ParseOptions) -> dict:
        """Call cloud API to parse PDF (upload -> poll -> download)."""
        # Step 1: get signed upload URL
        upload_url = self._get_upload_url(pdf_path, opts)
        if not upload_url:
            raise RuntimeError("No upload URL returned")

        # Step 2: upload PDF
        self._upload_pdf(pdf_path, upload_url)

        # Step 3: poll for result
        batch_id = self._extract_batch_id(upload_url)
        return self._poll_for_result(batch_id, opts)

    def _get_upload_url(self, pdf_path: Path, opts: ParseOptions) -> str | None:
        """Get signed upload URL from cloud API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict = {
            "files": [{"name": pdf_path.name, "data_id": pdf_path.stem}],
            "model_version": opts.backend,
            "enable_formula": opts.formula_enable,
            "enable_table": opts.table_enable,
            "language": opts.lang,
        }
        if opts.parse_method == "ocr":
            payload["is_ocr"] = True

        resp = self.http_client.post(
            f"{self.base_url}/file-urls/batch",
            json=payload,
            headers=headers,
            timeout=30,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Upload request failed: HTTP {resp.status_code}")

        resp_data = resp.json()
        if resp_data.get("code") != 0:
            raise RuntimeError(f"API error: {resp_data.get('msg')}")

        file_urls = resp_data.get("data", {}).get("file_urls", [])
        if not file_urls:
            return None

        first_url = file_urls[0]
        return first_url if isinstance(first_url, str) else first_url.get("url")

    def _upload_pdf(self, pdf_path: Path, upload_url: str) -> None:
        """Upload PDF to signed URL."""
        with open(pdf_path, "rb") as f:
            resp = self.http_client.put(upload_url, data=f.read(), timeout=120)

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Upload failed: HTTP {resp.status_code}")

    def _extract_batch_id(self, upload_url: str) -> str:
        """Extract batch_id from upload URL."""
        # URL format: https://xxx/batch/xxx?signature=xxx
        parts = upload_url.split("/")
        for part in parts:
            if part.startswith("batch_"):
                return part
        # Fallback: use last segment
        return parts[-1].split("?")[0]

    def _poll_for_result(self, batch_id: str, opts: ParseOptions) -> dict:
        """Poll for parsing result until done or timeout."""
        poll_headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.time() + CLOUD_TIMEOUT

        while time.time() < deadline:
            time.sleep(CLOUD_POLL_INTERVAL)

            # Early return if result ready
            item = self._check_poll_result(batch_id, poll_headers)
            if item is None:
                continue

            state = item.get("state", "")
            if state == STATE_FAILED:
                raise RuntimeError(f"Cloud parse failed: {item.get('err_msg')}")

            if state == STATE_DONE:
                return self._download_result(item, opts)

            # STATE_RUNNING
            extracted = item.get("extracted_pages", "?")
            total = item.get("total_pages", "?")
            _log.debug("cloud parsing... %s/%s pages", extracted, total)

        raise RuntimeError(f"Cloud parse timeout ({CLOUD_TIMEOUT}s)")

    def _check_poll_result(self, batch_id: str, headers: dict) -> dict | None:
        """Check polling result - returns item or None."""
        try:
            resp = self.http_client.get(
                f"{self.base_url}/extract-results/batch/{batch_id}",
                headers=headers,
                timeout=30,
            )
        except Exception:
            return None

        if resp.status_code != 200:
            return None

        try:
            poll_data = resp.json()
        except Exception:
            return None

        if poll_data.get("code") != 0:
            return None

        results = poll_data.get("data", {}).get("extract_result", [])
        return results[0] if results else None

    def _download_result(self, item: dict, opts: ParseOptions) -> dict:
        """Download and extract markdown from cloud result."""
        # Try direct md_content first
        if md := item.get("md_content"):
            if isinstance(md, str) and md.strip():
                return {"md_content": md}

        # Try full_zip_url
        if zip_url := item.get("full_zip_url"):
            if content := self._download_zip_content(zip_url):
                return {"md_content": content}

        # Try md_url
        if md_url := item.get("md_url"):
            if content := self._download_md_content(md_url):
                return {"md_content": content}

        raise RuntimeError("No markdown content in cloud result")

    def _download_zip_content(self, zip_url: str) -> str | None:
        """Download and extract markdown from ZIP file."""
        try:
            resp = self.http_client.get(zip_url, timeout=120)
            if resp.status_code != 200:
                return None

            data = resp.data
            if isinstance(data, bytes):
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    for name in zf.namelist():
                        if name.endswith(".md"):
                            return zf.read(name).decode("utf-8")
        except Exception as e:
            _log.debug("failed to download/extract zip: %s", e)
        return None

    def _download_md_content(self, md_url: str) -> str | None:
        """Download markdown from URL."""
        try:
            resp = self.http_client.get(md_url, timeout=60)
            if resp.status_code == 200:
                data = resp.data
                return data if isinstance(data, str) else None
        except Exception as e:
            _log.debug("failed to download md: %s", e)
        return None


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
            for entry in results.values():
                if isinstance(entry, dict) and (md := entry.get("md_content")):
                    if isinstance(md, str) and md.strip():
                        return md

        # Fallback: direct md_content at top level
        for key in ("md_content", "md", "markdown", "content"):
            if (value := data.get(key)) and isinstance(value, str) and value.strip():
                return value

        return None

    def _extract_field(self, data: dict, field_name: str) -> dict | None:
        """Extract a named field from API response."""
        if not isinstance(data, dict):
            return None

        results = data.get("results")
        if isinstance(results, dict):
            for entry in results.values():
                if isinstance(entry, dict) and field_name in entry:
                    return entry[field_name]

        return data.get(field_name)

    def _fmt_size(self, nbytes: int) -> str:
        """Format byte count as human-readable string."""
        if nbytes < 1024:
            return f"{nbytes} B"
        if nbytes < 1024 * 1024:
            return f"{nbytes / 1024:.1f} KB"
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
            keys = (
                list(api_response.response.keys())
                if isinstance(api_response.response, dict)
                else type(api_response.response).__name__
            )
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

        # Create output directory
        try:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(extracted.content, encoding="utf-8")
        except Exception as e:
            return ParseError(
                pdf_path=extracted.pdf_path,
                stage="save",
                error=str(e),
            )

        md_size = md_path.stat().st_size

        return ParseResult(
            pdf_path=extracted.pdf_path,
            md_path=md_path,
            md_size=md_size,
            elapsed=0.0,  # TODO: track total time
        )

    # Full pipeline: Stage 1 -> Stage 4
    def parse(
        self, pdf_path: Path, opts: ParseOptions | None = None
    ) -> ParseResult | ParseError:
        """Full pipeline: PDF -> Markdown file."""
        opts = opts or ParseOptions()
        pdf_input = PDFInput(pdf_path=pdf_path, opts=opts)

        # Stage 1 -> Stage 2
        api_result = self.call_api(pdf_input)
        if isinstance(api_result, ParseError):
            return api_result

        # Stage 2 -> Stage 3
        extract_result = self.extract(api_result)
        if isinstance(extract_result, ParseError):
            return extract_result

        # Stage 3 -> Stage 4
        return self.save(extract_result)
