"""
http.py — Shared HTTP Client Layer
===================================

General HTTP client abstraction for network operations.
Provides Protocol-based interface for testability.

Usage:
    from linkora.http import HTTPClient, RequestsClient

    client: HTTPClient = RequestsClient()
    response = client.get(url, timeout=30)
    response = client.post(url, json={...}, timeout=30)
    response = client.put(url, data=bytes, timeout=30)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class HTTPClient(Protocol):
    """Protocol for HTTP client implementations."""

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: int = 30,
    ) -> HTTPResponse:
        """Make GET request."""
        ...

    def post(
        self,
        url: str,
        json: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        headers: dict | None = None,
        timeout: int = 30,
    ) -> HTTPResponse:
        """Make POST request."""
        ...

    def put(
        self,
        url: str,
        data: bytes | None = None,
        headers: dict | None = None,
        timeout: int = 30,
    ) -> HTTPResponse:
        """Make PUT request."""
        ...


@dataclass(frozen=True)
class HTTPResponse:
    """HTTP response wrapper."""

    status_code: int
    data: dict | str | bytes
    headers: dict[str, str] | None = None

    def raise_for_status(self) -> None:
        """Raise exception for error status codes."""
        if 400 <= self.status_code < 600:
            raise RuntimeError(f"HTTP {self.status_code}: {self.data}")

    def json(self) -> dict:
        """Parse response as JSON."""
        if isinstance(self.data, dict):
            return self.data
        raise ValueError(f"Response is not JSON: {type(self.data)}")


# Default proxies to bypass system proxy for direct URLs
DEFAULT_NO_PROXIES: dict[str, str] = {"http": "", "https": ""}


@dataclass(frozen=True)
class RequestsClient:
    """HTTP client implementation using requests library."""

    proxies: dict[str, str] | None = None
    max_retries: int = 3

    def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> HTTPResponse:
        """Make HTTP request with retry."""
        import requests
        from tenacity import retry, stop_after_attempt, wait_exponential

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        )
        def _do_request():
            resp = requests.request(
                method=method,
                url=url,
                proxies=self.proxies,
                **kwargs,
            )
            return HTTPResponse(
                status_code=resp.status_code,
                data=resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else resp.text,
                headers=dict(resp.headers),
            )

        return _do_request()

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: int = 30,
    ) -> HTTPResponse:
        """Make GET request using requests library."""
        return self._request(
            "GET", url, params=params, headers=headers, timeout=timeout
        )

    def post(
        self,
        url: str,
        json: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        headers: dict | None = None,
        timeout: int = 30,
    ) -> HTTPResponse:
        """Make POST request using requests library."""
        return self._request(
            "POST",
            url,
            json=json,
            data=data,
            files=files,
            headers=headers,
            timeout=timeout,
        )

    def put(
        self,
        url: str,
        data: bytes | None = None,
        headers: dict | None = None,
        timeout: int = 30,
    ) -> HTTPResponse:
        """Make PUT request using requests library."""
        return self._request("PUT", url, data=data, headers=headers, timeout=timeout)
