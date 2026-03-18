"""
llm.py — LLM Execution Layer
=============================

Unified LLM execution with retry logic.
Uses data class + flow pattern (no convenience function).

Usage:
    from linkora.llm import LLMRunner, LLMRequest, LLMConfig

    # Data initiation
    config = LLMConfig(model="deepseek-chat", api_key="sk-...")
    request = LLMRequest(prompt="your prompt", config=config)

    # Consuming flow
    runner = LLMRunner(config)
    result = runner.execute(request)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from linkora.config import LLMConfig
from linkora.http import HTTPClient
from linkora.log import get_logger

_log = get_logger(__name__)


# ============================================================================
#  Protocols (Interface-Based Design)
# ============================================================================


class LLMClient(Protocol):
    """Protocol for LLM client implementations."""

    @property
    def name(self) -> str:
        """Client name."""
        ...

    def complete(self, request: LLMRequest) -> LLMResult:
        """Execute LLM request and return result."""
        ...


# ============================================================================
#  Data Structures (Data Initiation)
# ============================================================================


@dataclass(frozen=True)
class HTTPHeaders:
    """HTTP headers configuration."""

    authorization: str
    content_type: str = "application/json"

    def to_dict(self) -> dict[str, str]:
        return {
            "Authorization": self.authorization,
            "Content-Type": self.content_type,
        }


class LLMPayloadDict(TypedDict):
    """TypedDict for LLM API payload."""

    model: str
    messages: list[dict[str, str]]
    temperature: int
    max_tokens: int
    response_format: dict[str, str] | None


@dataclass(frozen=True)
class LLMPayload:
    """LLM request payload structure."""

    model: str
    messages: list[dict[str, str]]
    temperature: int = 0
    max_tokens: int = 8000
    response_format: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API calls."""
        result: dict[str, Any] = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.response_format is not None:
            result["response_format"] = self.response_format
        return result


@dataclass(frozen=True)
class LLMRequest:
    """Immutable LLM request data."""

    prompt: str
    config: LLMConfig
    system: str | None = None
    json_mode: bool = True
    max_tokens: int = 8000
    timeout: int | None = None
    max_retries: int = 3
    purpose: str = ""


@dataclass(frozen=True)
class LLMResult:
    """LLM call result."""

    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_total: int = 0
    model: str = ""
    duration_s: float = 0.0


# ============================================================================
#  Prompt Templates Registry (extract from extract.py)
# ============================================================================


@dataclass(frozen=True)
class PromptTemplate:
    """Immutable prompt template."""

    system: str
    user_template: str

    def render(self, **kwargs: str) -> str:
        return self.user_template.format(**kwargs)


# ============================================================================
#  LLM Runner (Consuming Flow)
# ============================================================================


class LLMRunner:
    """LLM runner - consumes LLMRequest and produces LLMResult."""

    def __init__(
        self,
        config: LLMConfig,
        http_client: HTTPClient,
        api_key: str = "",
    ):
        self._llm_cfg = config
        self._api_key = api_key or config.resolve_api_key()

        if not self._api_key:
            raise RuntimeError("No LLM API key configured.")

        self._http_client = http_client

    @property
    def name(self) -> str:
        return "llm-runner"

    def execute(self, request: LLMRequest) -> LLMResult:
        """Execute LLM request with retry logic.

        Args:
            request: LLMRequest with prompt and config.

        Returns:
            LLMResult containing response and metrics.
        """
        url = self._llm_cfg.base_url.rstrip("/") + "/v1/chat/completions"

        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        response_format: dict[str, str] | None = None
        if request.json_mode:
            response_format = {"type": "json_object"}

        payload = LLMPayload(
            model=self._llm_cfg.model,
            messages=messages,
            max_tokens=request.max_tokens,
            response_format=response_format,
        )

        headers = HTTPHeaders(
            authorization=f"Bearer {self._api_key}",
        )

        timeout = request.timeout or self._llm_cfg.timeout
        last_error: Exception | None = None

        for attempt in range(request.max_retries):
            try:
                return self._make_request(
                    url, payload, headers, timeout, request.purpose
                )
            except Exception as e:
                last_error = e
                _log.debug(
                    "LLM call failed (attempt %d/%d): %s",
                    attempt + 1,
                    request.max_retries,
                    e,
                )
                if attempt < request.max_retries - 1:
                    time.sleep(2**attempt)  # Exponential backoff

        raise RuntimeError(
            f"LLM call failed after {request.max_retries} attempts: {last_error}"
        )

    def _make_request(
        self,
        url: str,
        payload: LLMPayload,
        headers: HTTPHeaders,
        timeout: int,
        purpose: str = "",
    ) -> LLMResult:
        """Make a single LLM request."""
        import json

        t0 = time.monotonic()
        status = "ok"
        tokens_in = tokens_out = tokens_total = 0
        model_name = self._llm_cfg.model
        content = ""

        try:
            resp = self._http_client.post(
                url=url,
                json=payload.to_dict(),
                headers=headers.to_dict(),
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as e:
                snippet = json.dumps(data, ensure_ascii=False)[:300]
                raise ValueError(
                    f"Unexpected API response structure: {e}\n{snippet}"
                ) from e

            usage = data.get("usage") or {}
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            tokens_total = usage.get("total_tokens", 0)
            model_name = data.get("model", self._llm_cfg.model)

        except Exception:
            status = "error"
            raise
        finally:
            duration = round(time.monotonic() - t0, 3)
            _log.debug(
                "LLM [%s] %d tokens (in=%d out=%d) %.1fs [%s]",
                purpose or "unnamed",
                tokens_total,
                tokens_in,
                tokens_out,
                duration,
                status,
            )

        return LLMResult(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_total=tokens_total,
            model=model_name,
            duration_s=duration,
        )
