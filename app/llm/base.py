import re
import time
from abc import ABC, abstractmethod
from typing import Optional

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    OpenAI,
)
from openai import AuthenticationError as OpenAIAuthenticationError
from openai import RateLimitError as OpenAIRateLimitError

from app.llm.exceptions import (
    AuthenticationError,
    ContextLengthError,
    EmptyResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.llm.schemas import GenerateResult

_SECRET_PATTERN = re.compile(r"(sk-|gsk_)[A-Za-z0-9_-]{10,}")


def _safe_error_text(e: Exception) -> str:
    """Never let anything key-shaped escape into an exception message or log line, even
    defensively (in case an SDK ever echoes request headers in an error body)."""
    return _SECRET_PATTERN.sub("[REDACTED]", str(e))[:300]


class LLMProvider(ABC):
    """Provider-independent interface. Business agents depend on this, never on the Groq
    or OpenAI SDK directly.

    Deliberately synchronous, not async: every existing caller in this codebase (LangGraph
    nodes, Streamlit, the FastAPI scrape endpoint, pytest) is synchronous. Introducing async
    here would mean threading it through the entire app for no real benefit yet — the
    "smallest safe integration" this project's conventions call for.
    """

    name: str

    @abstractmethod
    def generate(
        self,
        messages: list[dict],
        model: str,
        max_completion_tokens: int,
        temperature: float,
        response_schema: Optional[dict] = None,
    ) -> GenerateResult:
        """Raises a typed exception from app.llm.exceptions on any failure — never returns
        a partial/invalid result silently."""
        raise NotImplementedError


class OpenAICompatibleProvider(LLMProvider):
    """Groq and OpenRouter both expose an OpenAI-compatible /chat/completions endpoint, so
    the request/error-translation logic is identical — only the base URL, key, and display
    name differ. Concrete providers just set `name` and pass their own base_url/api_key.
    """

    # The openai SDK's own default read timeout is 600s, with its own internal retries on
    # top of that — discovered for real when a single test chaining 3 calls took 89
    # minutes instead of the normal ~90 seconds, most likely several stacked 600s windows
    # during a slow patch rather than anything actually hanging forever. That default is
    # far too long for an interactive app: it means a stalled request blocks for up to 10
    # minutes before this class's own retry/fallback logic even gets a chance to react.
    # 45s comfortably covers real observed strong-model latency (~52s worst case seen, but
    # that's rare — 45s catches genuine stalls fast while rarely tripping on legitimate
    # slow-but-working calls) and lets the router's retry/escalation actually do its job
    # within a reasonable total time budget instead of stacking multiple 600s windows.
    REQUEST_TIMEOUT_SECONDS = 45.0

    def __init__(self, name: str, api_key: str, base_url: str):
        self.name = name
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=self.REQUEST_TIMEOUT_SECONDS)

    def generate(
        self,
        messages: list[dict],
        model: str,
        max_completion_tokens: int,
        temperature: float,
        response_schema: Optional[dict] = None,
    ) -> GenerateResult:
        start = time.monotonic()
        extra: dict = {}
        if response_schema is not None:
            extra["response_format"] = {"type": "json_object"}

        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_completion_tokens,
                temperature=temperature,
                **extra,
            )
        except OpenAIAuthenticationError as e:
            raise AuthenticationError(f"{self.name} authentication failed: {_safe_error_text(e)}") from e
        except OpenAIRateLimitError as e:
            raise RateLimitError(
                f"{self.name} rate limited: {_safe_error_text(e)}",
                retry_after=_extract_retry_after(e),
            ) from e
        except APITimeoutError as e:
            raise ProviderTimeoutError(f"{self.name} timed out: {_safe_error_text(e)}") from e
        except BadRequestError as e:
            text = _safe_error_text(e)
            if "context" in text.lower() or "too long" in text.lower() or "maximum" in text.lower():
                raise ContextLengthError(f"{self.name} context length exceeded: {text}") from e
            raise ProviderUnavailableError(f"{self.name} rejected the request: {text}") from e
        except APIConnectionError as e:
            raise ProviderUnavailableError(f"{self.name} connection error: {_safe_error_text(e)}") from e
        except APIStatusError as e:
            raise ProviderUnavailableError(
                f"{self.name} error (status {e.status_code}): {_safe_error_text(e)}"
            ) from e

        latency_ms = (time.monotonic() - start) * 1000
        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise EmptyResponseError(f"{self.name} returned an empty completion")

        usage = response.usage
        return GenerateResult(
            content=content,
            provider=self.name,
            model=model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            latency_ms=latency_ms,
        )


def _extract_retry_after(e: Exception) -> Optional[float]:
    try:
        header = e.response.headers.get("retry-after")  # type: ignore[attr-defined]
        return float(header) if header else None
    except Exception:
        return None
