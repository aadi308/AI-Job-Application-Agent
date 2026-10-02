import json
import logging
import random
import time
from typing import Callable, Optional

from app.llm.base import LLMProvider
from app.llm.exceptions import AllProvidersFailedError, RETRYABLE_EXCEPTIONS
from app.llm.schemas import EvaluationSource, RoutedResult, RoutingAttempt, TaskComplexity

log = logging.getLogger("app.llm.router")


def _failure_message(attempts: list[RoutingAttempt]) -> str:
    details = []
    for attempt in attempts:
        if not attempt.succeeded and attempt.error:
            details.append(f"{attempt.provider}/{attempt.model}: {attempt.error}")
    if not details:
        return "All providers in the routing chain failed or were rejected"
    # Provider exceptions are already sanitized at the provider boundary. Keep this
    # concise enough for the dashboard and audit record.
    return "All providers failed — " + "; ".join(details[-3:])[:700]


class LLMRouter:
    """Routine request -> Groq routine model -> (low confidence) -> Groq strong model ->
    (still failing) -> OpenRouter fallback -> (still failing) -> AllProvidersFailedError.

    Strong-complexity requests (detailed ATS evaluation, resume tailoring) skip straight to
    the Groq strong model — no point spending a routine-model call on a task that always
    needs the strong one.
    """

    def __init__(
        self,
        groq: Optional[LLMProvider],
        openrouter: Optional[LLMProvider],
        routine_model: str,
        strong_model: str,
        fallback_model: str,
        enable_fallback: bool = True,
        routine_confidence_threshold: float = 0.85,
        max_retries: int = 3,
    ):
        self.groq = groq
        self.openrouter = openrouter
        self.routine_model = routine_model
        self.strong_model = strong_model
        self.fallback_model = fallback_model
        self.enable_fallback = enable_fallback
        self.routine_confidence_threshold = routine_confidence_threshold
        self.max_retries = max_retries

    def _call_with_retry(
        self,
        provider: LLMProvider,
        model: str,
        messages: list[dict],
        max_completion_tokens: int,
        temperature: float,
        response_schema: Optional[dict],
        attempts: list[RoutingAttempt],
    ):
        last_err: Exception | None = None
        for attempt_num in range(self.max_retries):
            start = time.monotonic()
            try:
                result = provider.generate(
                    messages, model, max_completion_tokens, temperature, response_schema
                )
                attempts.append(
                    RoutingAttempt(
                        provider=provider.name,
                        model=model,
                        succeeded=True,
                        latency_ms=result.latency_ms,
                        retry_count=attempt_num,
                    )
                )
                return result
            except RETRYABLE_EXCEPTIONS as e:
                last_err = e
                latency_ms = (time.monotonic() - start) * 1000
                attempts.append(
                    RoutingAttempt(
                        provider=provider.name,
                        model=model,
                        succeeded=False,
                        error=str(e)[:200],
                        latency_ms=latency_ms,
                        retry_count=attempt_num,
                    )
                )
                if attempt_num < self.max_retries - 1:
                    delay = min(2**attempt_num, 8) + random.uniform(0, 0.5)
                    retry_after = getattr(e, "retry_after", None)
                    if retry_after:
                        delay = max(delay, retry_after)
                    log.warning(
                        "llm_retry provider=%s model=%s attempt=%d delay=%.1f reason=%s",
                        provider.name, model, attempt_num, delay, type(e).__name__,
                    )
                    time.sleep(delay)
            except Exception as e:
                # Non-retryable (auth, context-length, schema, ...) — fail this provider
                # immediately rather than burning retries on something that can't self-resolve.
                attempts.append(
                    RoutingAttempt(
                        provider=provider.name, model=model, succeeded=False,
                        error=str(e)[:200], retry_count=attempt_num,
                    )
                )
                raise
        raise last_err

    def generate(
        self,
        messages: list[dict],
        complexity: TaskComplexity,
        max_completion_tokens: int,
        temperature: float,
        response_schema: Optional[dict] = None,
        confidence_extractor: Optional[Callable[[dict], Optional[float]]] = None,
    ) -> RoutedResult:
        attempts: list[RoutingAttempt] = []
        original_provider = "groq" if self.groq else "openrouter"

        chain: list[tuple[LLMProvider, str, EvaluationSource]] = []
        if self.groq:
            if complexity == "routine":
                chain.append((self.groq, self.routine_model, "REAL_PRIMARY"))
                chain.append((self.groq, self.strong_model, "REAL_ESCALATED"))
            else:
                chain.append((self.groq, self.strong_model, "REAL_PRIMARY"))
        if self.groq and self.enable_fallback and self.openrouter:
            fallback_source: EvaluationSource = "REAL_FALLBACK" if self.groq else "REAL_PRIMARY"
            chain.append((self.openrouter, self.fallback_model, fallback_source))
        elif not self.groq and self.openrouter:
            # OpenRouter-only mode: this is the primary provider, not a fallback.
            chain.append((self.openrouter, self.fallback_model, "REAL_PRIMARY"))

        if not chain:
            raise AllProvidersFailedError("No providers configured", attempts=[])

        for provider, model, source in chain:
            try:
                result = self._call_with_retry(
                    provider, model, messages, max_completion_tokens, temperature,
                    response_schema, attempts,
                )
            except Exception:
                continue  # try the next link in the chain

            if response_schema is not None:
                try:
                    parsed = json.loads(result.content)
                except json.JSONDecodeError:
                    attempts.append(
                        RoutingAttempt(
                            provider=provider.name, model=model, succeeded=False,
                            error="invalid JSON in response",
                        )
                    )
                    continue

                confidence = confidence_extractor(parsed) if confidence_extractor else None
                result.confidence = confidence

                is_routine_primary = source == "REAL_PRIMARY" and complexity == "routine"
                if is_routine_primary and confidence is not None and confidence < self.routine_confidence_threshold:
                    log.info(
                        "llm_escalate provider=%s model=%s confidence=%.2f threshold=%.2f",
                        provider.name, model, confidence, self.routine_confidence_threshold,
                    )
                    continue  # escalate to the next link (strong model)

            return RoutedResult(
                result=result,
                evaluation_source=source,
                fallback_used=(source == "REAL_FALLBACK"),
                original_provider=original_provider,
                final_provider=provider.name,
                attempts=attempts,
            )

        raise AllProvidersFailedError(
            _failure_message(attempts),
            attempts=[a.model_dump() for a in attempts],
        )
