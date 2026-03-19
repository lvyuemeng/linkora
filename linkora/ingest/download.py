"""ingest_download.py — PDF download utilities (improved).

Key improvements:
- Handle local PDFs directly (no download needed)
- Retry logic for transient failures
- Better timeout handling
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from linkora.http import HTTPClient
from linkora.log import get_logger
from linkora.sources.protocol import PaperCandidate

_log = get_logger(__name__)

# Configurable settings
DEFAULT_TIMEOUT = 120  # seconds (PDFs can be large)
MAX_RETRIES = 3


def get_pdf_path(
    candidate: PaperCandidate,
    papers_dir: Path,
    http_client: HTTPClient | None,
) -> Path | None:
    """Get PDF path - use local or download from URL.

    Key logic:
    - If pdf_url is a local path (file exists), use it directly
    - If pdf_url is HTTP URL, download to cache
    - Check cache before downloading

    Args:
        candidate: Paper candidate with pdf_url
        papers_dir: Papers directory for cache location
        http_client: HTTP client for downloading PDFs

    Returns:
        Path to PDF, or None if not available
    """
    pdf_url = candidate.pdf_url

    if not pdf_url:
        return None

    # Case 1: Local file path - use directly (no download needed)
    local_path = _try_local_path(pdf_url)
    if local_path and local_path.exists():
        _log.debug("Using local PDF: %s", local_path)
        return local_path

    # Case 2: Remote URL - download with caching
    if not http_client:
        return None

    # Skip non-HTTP URLs
    if not pdf_url.startswith("http://") and not pdf_url.startswith("https://"):
        return None

    cache_dir = papers_dir.parent / "cache" / "pdfs"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Check cache first
    cached = get_cached_pdf(pdf_url, cache_dir)
    if cached:
        return cached

    # Download
    return download_pdf(pdf_url, cache_dir, http_client)


def _try_local_path(url_or_path: str) -> Path | None:
    """Check if url_or_path is actually a local file path.

    Local source sets pdf_url to absolute path like C:\\... or /home/...
    """
    # Check if it's an absolute path
    if os.path.isabs(url_or_path):
        path = Path(url_or_path)
        if path.exists() and path.is_file():
            return path

    # Check if it's a relative path from workspace
    path = Path(url_or_path)
    if path.exists() and path.is_file():
        return path.resolve()

    return None


def get_cached_pdf(pdf_url: str, cache_dir: Path) -> Path | None:
    """Check if PDF is cached."""
    url_hash = hashlib.md5(pdf_url.encode()).hexdigest()[:12]
    cached_path = cache_dir / f"{url_hash}.pdf"

    if cached_path.exists():
        return cached_path
    return None


def download_pdf(
    url: str,
    target_dir: Path,
    http_client: HTTPClient,
    timeout: int = DEFAULT_TIMEOUT,
) -> Path | None:
    """Download PDF with retry logic.

    Args:
        url: PDF URL (must be HTTP/HTTPS)
        target_dir: Target directory
        http_client: HTTP client
        timeout: Download timeout in seconds

    Returns:
        Path to downloaded PDF, or None on failure
    """
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    target_path = target_dir / f"{url_hash}.pdf"

    if target_path.exists():
        return target_path

    # Retry loop
    for attempt in range(MAX_RETRIES):
        try:
            resp = http_client.get(url, timeout=timeout)
            if resp.status_code != 200:
                _log.debug("HTTP %s for %s", resp.status_code, url)
                return None

            # Handle response data
            data = resp.data
            if isinstance(data, bytes):
                target_path.write_bytes(data)
            elif isinstance(data, str):
                target_path.write_text(data)
            else:
                _log.debug("Unexpected data type: %s", type(data))
                return None

            _log.debug("Downloaded: %s", target_path.name)
            return target_path

        except Exception as e:
            _log.debug("Download attempt %s failed: %s", attempt + 1, e)
            # Clean up partial file
            if target_path.exists():
                try:
                    target_path.unlink()
                except Exception:
                    pass

            # Exponential backoff
            if attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)

    return None


__all__ = ["get_pdf_path", "get_cached_pdf", "download_pdf"]
