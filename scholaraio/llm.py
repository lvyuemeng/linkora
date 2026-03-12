"""
llm.py — LLM Execution Layer
=============================

Unified LLM execution with retry logic.
Uses data class + flow pattern (no convenience function).

Usage:
    from scholaraio.llm import LLMRunner, LLMRequest

    # Data initiation
    request = LLMRequest(prompt="your prompt", config=config)
    
    # Consuming flow
    runner = LLMRunner(config)
    result = runner.execute(request)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from scholaraio.config import Config, LLMConfig

_log = logging.getLogger(__name__)


# ============================================================================
#  Data Structures (Data Initiation)
# ============================================================================


@dataclass(frozen=True)
class LLMRequest:
    """Immutable LLM request data."""
    prompt: str
    config: "Config | LLMConfig"
    system: str | None = None
    json_mode: bool = True
    max_tokens: int = 8000
    timeout: int | None = None
    max_retries: int = 3
    purpose: str = ""


@dataclass
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

    def __init__(self, config: "Config | LLMConfig", api_key: str = ""):
        from scholaraio.config import LLMConfig, resolve_llm

        if isinstance(config, LLMConfig):
            self._llm_cfg = config
            self._api_key = api_key or config.api_key
        else:
            self._llm_cfg = config.llm
            self._api_key = api_key or resolve_llm(config)

        if not self._api_key:
            raise RuntimeError("No LLM API key configured.")

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

        payload: dict[str, str | int] = {
            "model": self._llm_cfg.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

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
        payload: dict,
        headers: dict,
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
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
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


# ============================================================================
#  Convenience Factory (optional, for simple cases)
# ============================================================================


def create_request(
    prompt: str,
    config: "Config | LLMConfig",
    *,
    system: str | None = None,
    json_mode: bool = True,
    max_tokens: int = 8000,
    timeout: int | None = None,
    max_retries: int = 3,
    purpose: str = "",
) -> LLMRequest:
    """Create LLMRequest - data initiation.

    Args:
        prompt: User message content.
        config: Full Config or LLMConfig instance.
        system: Optional system message.
        json_mode: Enable JSON response format.
        max_tokens: Max completion tokens.
        timeout: Request timeout.
        max_retries: Number of retries on failure.
        purpose: Call purpose identifier.

    Returns:
        LLMRequest instance ready for execution.
    """
    return LLMRequest(
        prompt=prompt,
        config=config,
        system=system,
        json_mode=json_mode,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        purpose=purpose,
    )
