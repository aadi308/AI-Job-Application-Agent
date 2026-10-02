import json
import os
from datetime import datetime, timezone
from typing import Optional

from app.db import get_connection
from app.llm.schemas import REAL_EVALUATION_SOURCES, RoutedResult

DEFAULT_CONFIDENCE_THRESHOLD = float(os.environ.get("LLM_ROUTINE_CONFIDENCE_THRESHOLD", "0.85"))


def record_evaluation(
    agent_name: str,
    evaluation_status: str,
    started_at: datetime,
    job_id: Optional[int] = None,
    routed: Optional[RoutedResult] = None,
    validation_errors: Optional[list[str]] = None,
    safe_error_message: Optional[str] = None,
    result_json: Optional[dict] = None,
    prompt_version: str = "v1",
    owner_id: Optional[str] = None,
) -> int:
    """One audit row per LLM call — the record Step 10's production-eligibility gate reads."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO llm_evaluations
                    (owner_id, job_id, agent_name, provider, model, evaluation_source, evaluation_status,
                     prompt_version, input_tokens, output_tokens, total_tokens, latency_ms,
                     started_at, completed_at, retry_count, fallback_used, original_provider,
                     final_provider, confidence, validation_errors, safe_error_message, result_json)
                VALUES (%(owner_id)s, %(job_id)s, %(agent_name)s, %(provider)s, %(model)s, %(evaluation_source)s,
                        %(evaluation_status)s, %(prompt_version)s, %(input_tokens)s, %(output_tokens)s,
                        %(total_tokens)s, %(latency_ms)s, %(started_at)s, %(completed_at)s,
                        %(retry_count)s, %(fallback_used)s, %(original_provider)s, %(final_provider)s,
                        %(confidence)s, %(validation_errors)s, %(safe_error_message)s, %(result_json)s)
                RETURNING id
                """,
                {
                    "owner_id": owner_id,
                    "job_id": job_id,
                    "agent_name": agent_name,
                    "provider": routed.final_provider if routed else None,
                    "model": routed.result.model if routed else None,
                    "evaluation_source": routed.evaluation_source if routed else "MOCK_TEST",
                    "evaluation_status": evaluation_status,
                    "prompt_version": prompt_version,
                    "input_tokens": routed.result.input_tokens if routed else None,
                    "output_tokens": routed.result.output_tokens if routed else None,
                    "total_tokens": routed.result.total_tokens if routed else None,
                    "latency_ms": routed.result.latency_ms if routed else None,
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc),
                    "retry_count": sum(a.retry_count for a in routed.attempts) if routed else 0,
                    "fallback_used": routed.fallback_used if routed else False,
                    "original_provider": routed.original_provider if routed else None,
                    "final_provider": routed.final_provider if routed else None,
                    "confidence": routed.result.confidence if routed else None,
                    "validation_errors": json.dumps(validation_errors or []),
                    "safe_error_message": safe_error_message,
                    "result_json": json.dumps(result_json) if result_json is not None else None,
                },
            )
            row_id = cur.fetchone()[0]
        conn.commit()
    return row_id


def get_latest_evaluation(
    job_id: int, agent_name: str, owner_id: Optional[str] = None
) -> Optional[dict]:
    """Most recent audit row for this job+agent — used to re-check production eligibility
    at each downstream gate (resume tailoring, PDF generation, ...) rather than trusting
    that an earlier gate's decision is still valid."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT evaluation_status, evaluation_source, confidence, validation_errors
                FROM llm_evaluations
                WHERE job_id = %s AND agent_name = %s
                  AND owner_id IS NOT DISTINCT FROM %s
                ORDER BY id DESC LIMIT 1
                """,
                (job_id, agent_name, owner_id),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row))


def is_production_eligible(
    evaluation_status: str,
    evaluation_source: str,
    confidence: Optional[float],
    validation_errors: Optional[list[str]],
    required_confidence: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> bool:
    """The single gate resume tailoring / PDF generation / application prep must pass
    through before using an evaluation. Deliberately not just `score >= 80`: status,
    source (real vs. mock), confidence, and validation errors all have to check out —
    a mock evaluation or a low-confidence real one is blocked regardless of its score.
    """
    if evaluation_status != "COMPLETED":
        return False
    if evaluation_source not in REAL_EVALUATION_SOURCES:
        return False
    if validation_errors:
        return False
    if confidence is not None and confidence < required_confidence:
        return False
    return True
