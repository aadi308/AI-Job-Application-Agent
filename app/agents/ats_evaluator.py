import json
from datetime import datetime, timezone

from pydantic import ValidationError

from app.core import vector_store
from app.db import get_connection
from app.llm.audit import is_production_eligible, record_evaluation
from app.llm.config import get_router
from app.llm.exceptions import AllProvidersFailedError
from app.llm.logging_utils import get_logger, log_llm_call
from app.llm.schemas import ATSEvaluation

log = get_logger("app.agents.ats_evaluator")

AGENT_NAME = "ats_evaluator"
PROMPT_VERSION = "v3-nullable-missing-evidence"

SYSTEM_PROMPT = """You are an ATS (Applicant Tracking System) compatibility evaluator for a \
job candidate. Evaluate the role against only the supplied resume evidence, regardless of job family.

You will be given relevant excerpts from the candidate's resume and a job posting. Score the \
fit in detail and classify the posting into one broad job family:
- "ai_ml", "data", "devops_cloud", "software", "security", "qa_testing"
- "product", "design", "sales_marketing", "hr_recruiting", "finance", "healthcare", or "other"

If the job posting is not an engineering/technical role (e.g. recruiting, sales, executive, \
accounting, non-technical operations), score it low regardless of whether the title contains \
words that superficially resemble the candidate's skills — do not infer a technical fit the \
posting doesn't actually describe. Base your reasoning on the job posting's actual \
responsibilities and requirements, not just its title, whenever a description is provided.

The candidate's resume excerpts are the ONLY source of truth for what they know or have done. \
Do not invent employment history, job titles, technologies, certifications, metrics, dates, \
education, responsibilities, or years of experience not present in the excerpts.

Respond with a JSON object with exactly these keys:
{
  "overall_score": int 0-100,
  "skills_score": int 0-100,
  "experience_score": int 0-100,
  "education_score": int 0-100,
  "keyword_score": int 0-100,
  "eligibility_status": "eligible" | "partially_eligible" | "not_eligible",
  "recommended_track": "one job-family value from the list above",
  "matching_requirements": ["..."],
  "partial_matches": ["..."],
  "missing_requirements": ["..."],
  "preferred_skills_missing": ["..."],
  "strengths": ["..."],
  "concerns": ["..."],
  "resume_recommendations": ["..."],
  "evidence": [
    {"requirement": "...", "resume_evidence": "string or null",
     "evidence_source": "string or null",
     "match_type": "exact" | "strong" | "partial" | "missing" | "unclear", "confidence": 0.0-1.0}
  ],
  "confidence": 0.0-1.0,
  "final_recommendation": "2-3 sentence summary of the fit"
}

For evidence items with match_type "missing" or "unclear", set resume_evidence and
evidence_source to null. For "exact", "strong", or "partial", both fields must contain
specific non-empty citations from the supplied resume excerpts.
"""


def fetch_unscored_jobs(conn, limit: int | None = None) -> list[dict]:
    query = (
        "SELECT id, company, title, location, description FROM jobs "
        "WHERE ats_score IS NULL ORDER BY id"
    )
    if limit:
        query += f" LIMIT {int(limit)}"
    with conn.cursor() as cur:
        cur.execute(query)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_job_by_id(conn, job_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, company, title, location, description FROM jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [c.name for c in cur.description]
        return dict(zip(cols, row))


def _confidence_extractor(parsed: dict) -> float | None:
    conf = parsed.get("confidence")
    return float(conf) if isinstance(conf, (int, float)) else None


def evaluate_job(job: dict, resume_context: str) -> tuple[ATSEvaluation | None, dict]:
    """Runs one job through the router + validates the schema. Returns (evaluation, audit_meta).
    evaluation is None if validation or all providers failed — audit_meta always describes
    what happened, for the caller to persist regardless of outcome."""
    router = get_router()
    started_at = datetime.now(timezone.utc)
    user_prompt = f"""Resume excerpts (most relevant to this job):
{resume_context}

Job posting:
Company: {job['company']}
Title: {job['title']}
Location: {job.get('location') or 'unspecified'}
Description: {job.get('description') or 'not available — score conservatively based on title alone'}
"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        routed = router.generate(
            messages=messages,
            complexity="strong",  # ATS evaluation begins directly at the strong model
            max_completion_tokens=3000,
            temperature=0.1,
            response_schema={},
            confidence_extractor=_confidence_extractor,
        )
    except AllProvidersFailedError as e:
        record_id = record_evaluation(
            agent_name=AGENT_NAME,
            evaluation_status="EVALUATION_FAILED",
            started_at=started_at,
            job_id=job["id"],
            safe_error_message=str(e)[:300],
            prompt_version=PROMPT_VERSION,
        )
        return None, {"status": "EVALUATION_FAILED", "record_id": record_id, "error": str(e)}

    log_llm_call(
        log, request_id=f"job-{job['id']}", job_id=job["id"], agent_name=AGENT_NAME,
        provider=routed.final_provider, model=routed.result.model,
        attempt_number=len(routed.attempts), latency_ms=routed.result.latency_ms,
        token_usage={"total": routed.result.total_tokens}, result_status="completed",
        fallback_reason="fallback" if routed.fallback_used else None,
    )

    try:
        parsed = json.loads(routed.result.content)
        evaluation = ATSEvaluation(**parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        errors = [str(e)[:300]]
        record_id = record_evaluation(
            agent_name=AGENT_NAME, evaluation_status="VALIDATION_FAILED", started_at=started_at,
            job_id=job["id"], routed=routed, validation_errors=errors,
            safe_error_message="schema validation failed", prompt_version=PROMPT_VERSION,
        )
        return None, {"status": "VALIDATION_FAILED", "record_id": record_id, "error": errors}

    eligible = is_production_eligible(
        evaluation_status="COMPLETED",
        evaluation_source=routed.evaluation_source,
        confidence=evaluation.confidence,
        validation_errors=None,
    )
    record_id = record_evaluation(
        agent_name=AGENT_NAME, evaluation_status="COMPLETED", started_at=started_at,
        job_id=job["id"], routed=routed, result_json=evaluation.model_dump(),
        prompt_version=PROMPT_VERSION,
    )
    return evaluation, {
        "status": "COMPLETED", "record_id": record_id, "production_eligible": eligible,
        "evaluation_source": routed.evaluation_source, "fallback_used": routed.fallback_used,
    }


def write_evaluation(conn, job_id: int, evaluation: ATSEvaluation) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET ats_score = %(ats_score)s,
                track = %(track)s,
                job_family = %(track)s,
                eval_summary = %(summary)s,
                evaluated_at = now(),
                updated_at = now()
            WHERE id = %(id)s
            """,
            {
                "ats_score": evaluation.overall_score,
                "track": evaluation.recommended_track,
                "summary": evaluation.final_recommendation,
                "id": job_id,
            },
        )


def evaluate_unscored_jobs(limit: int | None = None) -> dict:
    """Score every job with a NULL ats_score, via the Groq/OpenRouter router.

    Only production-eligible evaluations (real, completed, confident, no validation
    errors) get written to jobs.ats_score — everything else is recorded in
    llm_evaluations for audit/retry but leaves the job unscored rather than storing an
    unreliable number.
    """
    scored = 0
    failed = 0
    errors = []
    with get_connection() as conn:
        jobs = fetch_unscored_jobs(conn, limit=limit)
        for job in jobs:
            resume_context = "\n\n".join(
                vector_store.query_resume(
                    f"{job['title']} {job.get('location') or ''}", n_results=20
                )
            )
            evaluation, meta = evaluate_job(job, resume_context)
            if evaluation is not None and meta.get("production_eligible"):
                write_evaluation(conn, job["id"], evaluation)
                conn.commit()
                scored += 1
            else:
                failed += 1
                errors.append({"job_id": job["id"], "reason": meta})

    return {"attempted": len(jobs), "scored": scored, "failed": failed, "errors": errors}


def evaluate_job_by_id(job_id: int) -> dict:
    """Re-evaluates one specific job through the Groq/OpenRouter router regardless of
    whether it already has an ats_score — unlike evaluate_unscored_jobs, this doesn't skip
    jobs just because jobs.ats_score is already set. Needed for jobs that were scored
    before the llm_evaluations audit-trail table existed (or via the old title-only
    scoring path): they have a legacy ats_score but zero audit-trail rows, so
    is_production_eligible() correctly refuses to let them through the resume-generation
    gate until they're re-evaluated here.
    """
    with get_connection() as conn:
        job = fetch_job_by_id(conn, job_id)
        if job is None:
            raise ValueError(f"No job with id={job_id}")

        resume_context = "\n\n".join(
            vector_store.query_resume(f"{job['title']} {job.get('location') or ''}", n_results=20)
        )
        evaluation, meta = evaluate_job(job, resume_context)
        if evaluation is not None and meta.get("production_eligible"):
            write_evaluation(conn, job["id"], evaluation)
            conn.commit()

    return {"job_id": job_id, "evaluation": evaluation, "meta": meta}


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 2 and sys.argv[1] == "--job":
        result = evaluate_job_by_id(int(sys.argv[2]))
        evaluation = result["evaluation"]
        print(
            json.dumps(
                {
                    "job_id": result["job_id"],
                    "meta": result["meta"],
                    "overall_score": evaluation.overall_score if evaluation else None,
                    "track": evaluation.recommended_track if evaluation else None,
                },
                indent=2,
            )
        )
    else:
        limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
        summary = evaluate_unscored_jobs(limit=limit)
        print(json.dumps(summary, indent=2))
