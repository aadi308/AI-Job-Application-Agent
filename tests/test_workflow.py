import pytest
from langgraph.types import Command

from app.agents.ats_evaluator import evaluate_job, write_evaluation
from app.agents.supervisor import build_graph
from app.core import vector_store
from app.db import get_connection

pytestmark = [pytest.mark.live, pytest.mark.integration, pytest.mark.db]


def _fetch_high_scoring_job() -> dict:
    # Targets a specific, known-strong-match real job (Palantir "DevOps Engineer") rather
    # than "any job with ats_score >= 80", since that score predates this session's
    # Groq/router integration — old scores don't guarantee the new evaluator will also
    # rate it with confidence above the production-eligibility threshold. This exact job
    # has been repeatedly verified (elsewhere in this project's history) to score highly
    # with high confidence under the current pipeline, making the test deterministic
    # rather than dependent on which stale row happens to sort first.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, company, title, location, description, track, ats_score "
                "FROM jobs WHERE company = 'palantir' AND title = 'DevOps Engineer' "
                "ORDER BY id LIMIT 1"
            )
            row = cur.fetchone()
            assert row is not None, "expected the palantir 'DevOps Engineer' job in the DB"
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row))


def test_workflow_produces_resume_and_outreach_then_pauses_for_review():
    job = _fetch_high_scoring_job()
    resume_context = "\n\n".join(
        vector_store.query_resume(f"{job['title']} {job.get('location') or ''}", n_results=20)
    )

    # resume_writer_node requires a production-eligible ats_evaluator audit record for
    # this job_id. Jobs scored before the Groq/router integration (or via a different
    # test run) don't have one, so (re-)evaluate for real here rather than assuming
    # ats_score being set is still sufficient — it isn't, by design (Step 10's gate).
    evaluation, meta = evaluate_job(job, resume_context)
    assert meta["status"] == "COMPLETED" and meta["production_eligible"], meta
    with get_connection() as conn:
        write_evaluation(conn, job["id"], evaluation)
        conn.commit()

    graph = build_graph()
    config = {"configurable": {"thread_id": f"test-job-{job['id']}"}}

    initial_state = {
        "job_id": job["id"],
        "company": job["company"],
        "title": job["title"],
        "location": job.get("location"),
        "description": job.get("description"),
        "track": evaluation.recommended_track,
        "ats_score": float(evaluation.overall_score),
        "resume_context": resume_context,
        "tailored_resume": None,
        "resume_json": None,
        "resume_pdf_path": None,
        "resume_valid": None,
        "resume_claim_violations": [],
        "resume_pdf_violations": [],
        "outreach_message": None,
        "human_approved": None,
        "human_feedback": None,
    }

    result = graph.invoke(initial_state, config=config)

    assert "__interrupt__" in result, "graph should pause for human review before finishing"
    payload = result["__interrupt__"][0].value
    assert payload["tailored_resume"]
    assert payload["outreach_message"]
    assert "[Name]" not in payload["outreach_message"]

    final_state = graph.invoke(Command(resume={"approved": True, "feedback": ""}), config=config)

    assert final_state["human_approved"] is True
    assert final_state["tailored_resume"] == payload["tailored_resume"]
    assert final_state["outreach_message"] == payload["outreach_message"]
