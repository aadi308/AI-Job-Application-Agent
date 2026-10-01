"""Real API calls against Groq/OpenRouter — costs real (small) money and needs real
network access, so it's skipped by default.

Run explicitly with:
    RUN_LIVE_TESTS=true pytest -o addopts="-ra" -m live tests/integration/test_real_llm.py -v
"""

import pytest

from app.llm.config import build_router

pytestmark = pytest.mark.live


def test_real_groq_routine_connection():
    router = build_router()
    assert router.groq is not None, "GROQ_API_KEY must be set for this test"

    result = router.generate(
        messages=[{"role": "user", "content": "Respond with JSON: {\"status\": \"ok\"}"}],
        complexity="routine",
        max_completion_tokens=100,
        temperature=0.1,
        response_schema={},
    )

    assert result.final_provider == "groq"
    assert result.result.model == router.routine_model
    assert result.evaluation_source == "REAL_PRIMARY"
    assert result.result.total_tokens > 0
    assert "ok" in result.result.content.lower()


def test_real_ats_evaluation_with_synthetic_job(monkeypatch):
    """One opt-in strong-model ATS evaluation using fully synthetic job input."""
    from app.agents.ats_evaluator import evaluate_job

    monkeypatch.setattr("app.agents.ats_evaluator.record_evaluation", lambda **_kwargs: 1)

    job = {
        "id": None,
        "company": "Example Labs",
        "title": "MLOps Engineer",
        "location": "Remote",
        "description": "Build AWS and Kubernetes ML infrastructure using Terraform.",
    }
    resume_context = (
        "Demo Candidate — ML Engineer. Deployed Kubernetes services with Terraform on AWS."
    )
    evaluation, meta = evaluate_job(job, resume_context)

    assert meta["status"] == "COMPLETED"
    assert evaluation is not None
    assert 0 <= evaluation.overall_score <= 100
    assert 0.0 <= evaluation.confidence <= 1.0
    assert evaluation.recommended_track in ("devops", "mlops_intern")
    assert meta["evaluation_source"] in ("REAL_PRIMARY", "REAL_ESCALATED", "REAL_FALLBACK")
