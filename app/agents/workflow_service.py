import shutil
import uuid
from pathlib import Path

from langgraph.types import Command

from app.agents.resume_writer import STAGING_DIR
from app.core import vector_store
from app.db import get_connection

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "outputs"


def load_job(job_id: int) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, company, title, location, description, track, ats_score "
                "FROM jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No job with id={job_id}")
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row))


def build_initial_state(job: dict) -> dict:
    resume_context = "\n\n".join(
        vector_store.query_resume(f"{job['title']} {job.get('location') or ''}", n_results=20)
    )
    return {
        "job_id": job["id"],
        "company": job["company"],
        "title": job["title"],
        "location": job.get("location"),
        "description": job.get("description"),
        "track": job.get("track") or "other",
        "ats_score": float(job["ats_score"]) if job["ats_score"] is not None else 0.0,
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


def graph_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def start_review(graph, job_id: int) -> dict:
    """Runs the graph from scratch up to the human_review interrupt.

    Returns the interrupt payload (tailored resume/outreach preview + validation status),
    plus a "thread_id" key that must be passed back into resolve_review to finish this
    specific attempt. Each call mints a fresh thread_id (job-<id>-<random>) rather than
    reusing a single "job-<id>" thread for every attempt on this job: a long-lived caller
    (the dashboard's cached graph/checkpointer, unlike the CLI's one-shot process) could
    otherwise carry stale checkpoint history from a failed earlier attempt into a later one.
    """
    job = load_job(job_id)
    initial_state = build_initial_state(job)
    thread_id = f"job-{job_id}-{uuid.uuid4().hex[:8]}"
    result = graph.invoke(initial_state, config=graph_config(thread_id))

    interrupts = result.get("__interrupt__")
    if not interrupts:
        raise RuntimeError("Graph finished without pausing for human review — unexpected")
    payload = dict(interrupts[0].value)
    payload["thread_id"] = thread_id
    return payload


def resolve_review(graph, job_id: int, thread_id: str, approved: bool, feedback: str = "") -> dict:
    """Resumes a paused graph (the one started by start_review, identified by thread_id)
    with the human decision.

    Returns {"approved": bool, "blocked": bool, "saved_paths": [Path, ...]}. "blocked" means
    the human approved but automated validation still failed, so the resume PDF was not saved
    (only the outreach draft was) — approval and validation are two independent gates.
    """
    job = load_job(job_id)
    final_state = graph.invoke(
        Command(resume={"approved": approved, "feedback": feedback}), config=graph_config(thread_id)
    )

    if not approved:
        return {"approved": False, "blocked": False, "saved_paths": []}

    safe_company = job["company"].replace(" ", "_")
    safe_title = job["title"].replace(" ", "_").replace("/", "-")
    prefix = f"{job_id}_{safe_company}_{safe_title}"
    OUTPUT_DIR.mkdir(exist_ok=True)

    if not final_state.get("resume_valid"):
        outreach_path = OUTPUT_DIR / f"{prefix}_outreach.txt"
        outreach_path.write_text(final_state["outreach_message"])
        return {"approved": True, "blocked": True, "saved_paths": [outreach_path]}

    staged_prefix = f"job-{job_id}"
    copied = []
    for staged_file in Path(STAGING_DIR).glob(f"{staged_prefix}_*"):
        suffix = staged_file.name[len(staged_prefix) :]  # e.g. "_resume.pdf"
        dest = OUTPUT_DIR / f"{prefix}{suffix}"
        shutil.copy(staged_file, dest)
        copied.append(dest)

    outreach_path = OUTPUT_DIR / f"{prefix}_outreach.txt"
    outreach_path.write_text(final_state["outreach_message"])
    copied.append(outreach_path)

    return {"approved": True, "blocked": False, "saved_paths": copied}
