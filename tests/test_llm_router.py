import os
from datetime import datetime, timezone

import pytest

from app.llm.audit import get_latest_evaluation, is_production_eligible, record_evaluation
from app.llm.base import LLMProvider, OpenAICompatibleProvider
from app.llm.config import build_router
from app.llm.exceptions import AllProvidersFailedError, MissingAPIKeyError, RateLimitError
from app.llm.groq_provider import GroqProvider
from app.llm.logging_utils import redact
from app.llm.router import LLMRouter
from app.llm.schemas import GenerateResult


class FakeProvider(LLMProvider):
    """A scripted provider: each call pops the next item from `responses` — either a
    string (returned as content) or an Exception (raised)."""

    def __init__(self, name: str, responses: list):
        self.name = name
        self._responses = list(responses)
        self.calls: list[str] = []  # models called, in order

    def generate(self, messages, model, max_completion_tokens, temperature, response_schema=None):
        self.calls.append(model)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return GenerateResult(content=item, provider=self.name, model=model, latency_ms=1.0)


def _router(groq_responses=None, openrouter_responses=None, **kwargs) -> LLMRouter:
    groq = FakeProvider("groq", groq_responses) if groq_responses is not None else None
    openrouter = FakeProvider("openrouter", openrouter_responses or ["fallback content"])
    return LLMRouter(
        groq=groq,
        openrouter=openrouter,
        routine_model="routine-model",
        strong_model="strong-model",
        fallback_model="fallback-model",
        max_retries=kwargs.pop("max_retries", 1),
        **kwargs,
    )


def test_routine_request_routes_to_routine_model():
    router = _router(groq_responses=["hi"])
    result = router.generate(messages=[], complexity="routine", max_completion_tokens=100, temperature=0.1)
    assert result.result.model == "routine-model"
    assert result.evaluation_source == "REAL_PRIMARY"
    assert result.fallback_used is False


def test_strong_request_routes_directly_to_strong_model_skipping_routine():
    router = _router(groq_responses=["hi"])
    result = router.generate(messages=[], complexity="strong", max_completion_tokens=100, temperature=0.1)
    assert result.result.model == "strong-model"
    assert result.result.model != "routine-model"


def test_low_confidence_routine_result_escalates_to_strong_model():
    router = _router(
        groq_responses=['{"confidence": 0.1}', '{"confidence": 0.95}'],
        routine_confidence_threshold=0.85,
    )
    result = router.generate(
        messages=[], complexity="routine", max_completion_tokens=100, temperature=0.1,
        response_schema={}, confidence_extractor=lambda p: p.get("confidence"),
    )
    assert result.evaluation_source == "REAL_ESCALATED"
    assert result.result.model == "strong-model"
    assert result.result.confidence == 0.95


def test_rate_limit_triggers_openrouter_fallback():
    router = _router(
        groq_responses=[RateLimitError("rate limited"), RateLimitError("rate limited")],
        openrouter_responses=["fallback worked"],
    )
    result = router.generate(messages=[], complexity="routine", max_completion_tokens=100, temperature=0.1)
    assert result.evaluation_source == "REAL_FALLBACK"
    assert result.fallback_used is True
    assert result.result.content == "fallback worked"


def test_invalid_json_triggers_fallback():
    router = _router(
        groq_responses=["not valid json {{{", "not valid json either"],
        openrouter_responses=['{"ok": true}'],
    )
    result = router.generate(
        messages=[], complexity="routine", max_completion_tokens=100, temperature=0.1, response_schema={},
    )
    assert result.evaluation_source == "REAL_FALLBACK"
    assert result.result.content == '{"ok": true}'


def test_all_providers_failing_raises_and_does_not_fabricate_a_result():
    router = _router(
        groq_responses=[RateLimitError("down"), RateLimitError("down")],
        openrouter_responses=[RateLimitError("also down")],
    )
    with pytest.raises(AllProvidersFailedError) as exc_info:
        router.generate(messages=[], complexity="routine", max_completion_tokens=100, temperature=0.1)
    assert len(exc_info.value.attempts) > 0


def test_openrouter_only_mode_when_groq_not_configured():
    router = _router(groq_responses=None, openrouter_responses=["openrouter response"])
    result = router.generate(messages=[], complexity="strong", max_completion_tokens=100, temperature=0.1)
    assert result.final_provider == "openrouter"
    assert result.evaluation_source == "REAL_PRIMARY"  # not FALLBACK when it's the only provider


def test_provider_client_uses_a_short_explicit_timeout_not_the_sdk_default():
    """Regression guard: the openai SDK's own default read timeout is 600s (10 minutes),
    discovered for real when a single chained-call test took 89 minutes instead of ~90
    seconds during a slow patch — a stalled request blocked for that long before this
    class's own retry/fallback logic ever got a chance to react. If a future edit drops
    the explicit timeout, this should fail loudly rather than silently reintroducing a
    10-minute stall potential."""
    provider = GroqProvider(api_key="dummy-key-for-construction-only")
    assert isinstance(provider, OpenAICompatibleProvider)
    actual_timeout = provider._client.timeout
    # A plain float applies uniformly; a structured Timeout object has a separate .read.
    read_timeout = actual_timeout if isinstance(actual_timeout, (int, float)) else actual_timeout.read
    assert read_timeout <= 60, (
        f"expected a short read timeout, got {read_timeout}s — this is how a stalled "
        "request ends up blocking for 10 minutes instead of retrying/falling back"
    )


def test_no_provider_keys_produces_clear_startup_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError, match="GROQ_API_KEY or OPENROUTER_API_KEY"):
        build_router()


def test_groq_only_configuration_does_not_require_openrouter(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "dummy-groq-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "groq")
    monkeypatch.setenv("LLM_ENABLE_FALLBACK", "true")

    router = build_router()

    assert router.groq is not None
    assert router.openrouter is None
    assert router.enable_fallback is False


def test_openrouter_primary_still_requires_its_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "dummy-groq-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "openrouter")

    with pytest.raises(MissingAPIKeyError, match="LLM_PRIMARY_PROVIDER=openrouter"):
        build_router()


def test_swapped_groq_key_in_openrouter_variable_is_explained(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "gsk_example_key_not_real_123456789")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError, match="appears to contain a Groq key"):
        build_router()


def test_all_provider_error_includes_safe_attempt_reason():
    router = _router(
        groq_responses=[RateLimitError("quota exhausted")],
        openrouter_responses=[RateLimitError("fallback quota exhausted")],
        max_retries=1,
    )

    with pytest.raises(AllProvidersFailedError, match="quota exhausted"):
        router.generate(
            messages=[], complexity="strong", max_completion_tokens=10, temperature=0.1
        )


def test_redact_strips_api_keys_and_pii():
    text = "key sk-abc123456789012345 or gsk_xyz987654321098765 for a@b.com and 555-123-4567"
    cleaned = redact(text)
    assert "sk-abc" not in cleaned
    assert "gsk_xyz" not in cleaned
    assert "a@b.com" not in cleaned
    assert "555-123-4567" not in cleaned
    assert "[REDACTED_KEY]" in cleaned
    assert "[REDACTED_EMAIL]" in cleaned


def test_mock_evaluation_is_never_production_eligible():
    assert not is_production_eligible(
        evaluation_status="COMPLETED", evaluation_source="MOCK_TEST",
        confidence=0.99, validation_errors=[],
    )


def test_low_confidence_real_evaluation_is_not_production_eligible():
    assert not is_production_eligible(
        evaluation_status="COMPLETED", evaluation_source="REAL_PRIMARY",
        confidence=0.5, validation_errors=[], required_confidence=0.85,
    )


def test_validation_errors_block_production_eligibility_regardless_of_score():
    assert not is_production_eligible(
        evaluation_status="COMPLETED", evaluation_source="REAL_PRIMARY",
        confidence=0.99, validation_errors=["something didn't check out"],
    )


def test_real_completed_high_confidence_no_errors_is_eligible():
    assert is_production_eligible(
        evaluation_status="COMPLETED", evaluation_source="REAL_ESCALATED",
        confidence=0.9, validation_errors=[], required_confidence=0.85,
    )


@pytest.mark.integration
@pytest.mark.db
def test_audit_record_round_trips_through_postgres():
    """Real DB test (matches this project's convention — no DB mocking elsewhere)."""
    started_at = datetime.now(timezone.utc)
    fake_routed = _router(groq_responses=["hi"]).generate(
        messages=[], complexity="routine", max_completion_tokens=10, temperature=0.1,
    )
    record_id = record_evaluation(
        agent_name="test_agent", evaluation_status="COMPLETED", started_at=started_at,
        job_id=None, routed=fake_routed, prompt_version="test-v1",
    )
    assert record_id > 0

    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT agent_name, provider, model, evaluation_status, evaluation_source "
                "FROM llm_evaluations WHERE id = %s",
                (record_id,),
            )
            row = cur.fetchone()
    assert row == ("test_agent", "groq", "routine-model", "COMPLETED", "REAL_PRIMARY")
