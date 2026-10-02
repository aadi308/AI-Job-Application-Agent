import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from pypdf import PdfReader

from app.agents.ats_evaluator import evaluate_job_by_id
from app.agents.networking import networking_node
from app.agents.resume_writer import _plain_text_preview
from app.auth import AuthenticatedUser, get_current_user
from app.candidate.extractor import extract_profile_from_resume
from app.candidate.models import ApprovedAnswer, CandidateProfile
from app.candidate.store import (
    approve_profile,
    delete_answer,
    delete_profile,
    get_profile,
    list_answers,
    save_profile,
    upsert_answer,
)
from app.db import get_connection, upsert_job
from app.llm.audit import get_latest_evaluation, is_production_eligible
from app.models import ScrapeRequest, ScrapeResult
from app.resume.pipeline import generate_tailored_resume
from app.runtime import allows_manual_imports, is_production_mode
from app.scrapers import greenhouse, lever
from app.usage import ATS_EVALUATION, RESUME_GENERATION, QuotaExceeded, consume_daily_quota
from app.user_workspace import get_artifact, get_job, list_jobs, save_artifact, set_job_status

app = FastAPI(title="AI Job Application Agent")

SCRAPERS = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20
MIN_RESUME_TEXT = 80
ATS_DAILY_LIMIT = int(os.environ.get("ATS_DAILY_LIMIT", "3"))
RESUME_DAILY_LIMIT = int(os.environ.get("RESUME_DAILY_LIMIT", "2"))
GLOBAL_ATS_DAILY_LIMIT = int(os.environ.get("GLOBAL_ATS_DAILY_LIMIT", "30"))
GLOBAL_RESUME_DAILY_LIMIT = int(os.environ.get("GLOBAL_RESUME_DAILY_LIMIT", "20"))


class JobStatusUpdate(BaseModel):
    status: Literal["discovered", "applied", "interviewing", "offer", "rejected", "withdrawn"]


def get_workspace_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not is_production_mode():
        raise HTTPException(status_code=403, detail="Authenticated workspaces require production mode")
    return user


@app.get("/health")
def health():
    with get_connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/scrape/trigger", response_model=ScrapeResult)
def trigger_scrape(req: ScrapeRequest):
    if not allows_manual_imports():
        raise HTTPException(
            status_code=403,
            detail="Scraping is disabled in the public read-only demo. Run locally to import jobs.",
        )
    fetch = SCRAPERS[req.source]
    try:
        jobs = fetch(req.board)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    inserted = 0
    with get_connection() as conn:
        for job in jobs:
            if upsert_job(conn, job):
                inserted += 1
        conn.commit()

    return ScrapeResult(source=req.source, board=req.board, fetched=len(jobs), inserted=inserted)


@app.get("/jobs")
def authenticated_jobs(user: AuthenticatedUser = Depends(get_workspace_user)):
    return jsonable_encoder(list_jobs(user.id))


@app.get("/me/profile")
def read_profile(user: AuthenticatedUser = Depends(get_workspace_user)):
    profile = get_profile(user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No candidate profile exists")
    return profile


@app.put("/me/profile")
def write_profile(profile: CandidateProfile, user: AuthenticatedUser = Depends(get_workspace_user)):
    # Any edit invalidates approval; the user must review and approve the final state.
    profile.approved = False
    profile.approved_at = None
    save_profile(profile, user.id)
    return profile


@app.delete("/me/profile", status_code=status.HTTP_204_NO_CONTENT)
def remove_profile(user: AuthenticatedUser = Depends(get_workspace_user)):
    delete_profile(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/me/profile/approve")
def approve_candidate_profile(user: AuthenticatedUser = Depends(get_workspace_user)):
    try:
        return approve_profile(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _reserve(owner_id: str, action: str, limit: int, global_limit: int):
    try:
        with get_connection() as conn:
            result = consume_daily_quota(
                conn, owner_id, action, limit, global_daily_limit=global_limit
            )
            conn.commit()
        return result
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


def _extract_pdf_text(payload: bytes) -> str:
    if not payload or len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Resume PDF must be between 1 byte and 10 MB")
    try:
        reader = PdfReader(io.BytesIO(payload))
        if len(reader.pages) > MAX_PDF_PAGES:
            raise HTTPException(status_code=413, detail="Resume PDF is limited to 20 pages")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="The uploaded PDF could not be read") from exc
    if len(text.strip()) < MIN_RESUME_TEXT:
        raise HTTPException(status_code=422, detail="The PDF does not contain enough extractable text")
    return text


@app.post("/me/profile/extract")
async def extract_candidate_profile(
    request: Request, user: AuthenticatedUser = Depends(get_workspace_user)
):
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/pdf":
        raise HTTPException(status_code=415, detail="Send the resume as application/pdf")
    text = _extract_pdf_text(await request.body())
    quota = _reserve(
        user.id, RESUME_GENERATION, RESUME_DAILY_LIMIT, GLOBAL_RESUME_DAILY_LIMIT
    )
    try:
        profile = extract_profile_from_resume(text, owner_id=user.id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Profile extraction failed: {exc}") from exc
    save_profile(profile, user.id)
    return {"profile": profile, "quota_remaining": quota.remaining}


@app.get("/me/answers")
def read_answers(user: AuthenticatedUser = Depends(get_workspace_user)):
    return list_answers(user.id)


@app.put("/me/answers/{question_key}")
def write_answer(
    question_key: str,
    answer: ApprovedAnswer,
    user: AuthenticatedUser = Depends(get_workspace_user),
):
    if question_key != answer.question_key:
        raise HTTPException(status_code=400, detail="Question key does not match request path")
    upsert_answer(answer, user.id)
    return answer


@app.delete("/me/answers/{question_key}", status_code=status.HTTP_204_NO_CONTENT)
def remove_answer(question_key: str, user: AuthenticatedUser = Depends(get_workspace_user)):
    delete_answer(question_key, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.put("/me/jobs/{job_id}/status")
def update_status(
    job_id: int,
    update: JobStatusUpdate,
    user: AuthenticatedUser = Depends(get_workspace_user),
):
    if not set_job_status(user.id, job_id, update.status):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "status": update.status}


@app.post("/me/jobs/{job_id}/evaluate")
def evaluate_fit(job_id: int, user: AuthenticatedUser = Depends(get_workspace_user)):
    quota = _reserve(user.id, ATS_EVALUATION, ATS_DAILY_LIMIT, GLOBAL_ATS_DAILY_LIMIT)
    try:
        result = evaluate_job_by_id(job_id, owner_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Evaluation failed: {exc}") from exc
    evaluation = result["evaluation"]
    return {
        "job_id": job_id,
        "evaluation": evaluation.model_dump() if evaluation else None,
        "meta": result["meta"],
        "quota_remaining": quota.remaining,
    }


@app.post("/me/jobs/{job_id}/generate")
def generate_documents(job_id: int, user: AuthenticatedUser = Depends(get_workspace_user)):
    profile = get_profile(user.id)
    if profile is None or not profile.approved:
        raise HTTPException(status_code=422, detail="Approve your candidate profile first")
    job = get_job(user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.get("description") or len(job["description"].strip()) < 80:
        raise HTTPException(status_code=422, detail="A complete job description is required")
    evaluation = get_latest_evaluation(job_id, "ats_evaluator", owner_id=user.id)
    if evaluation is None or not is_production_eligible(**evaluation):
        raise HTTPException(status_code=422, detail="Complete a reliable ATS evaluation first")

    quota = _reserve(
        user.id, RESUME_GENERATION, RESUME_DAILY_LIMIT, GLOBAL_RESUME_DAILY_LIMIT
    )
    try:
        with TemporaryDirectory(prefix="ai-job-agent-") as directory:
            result = generate_tailored_resume(
                profile,
                job["company"],
                job["title"],
                job["description"],
                directory,
                f"job-{job_id}",
                owner_id=user.id,
            )
            pdf_bytes = Path(result.pdf_path).read_bytes()
        resume_text = _plain_text_preview(result.structured_resume)
        outreach = networking_node(
            {
                "owner_id": user.id,
                "job_id": job_id,
                "company": job["company"],
                "title": job["title"],
                "location": job.get("location"),
                "description": job.get("description"),
                "track": job.get("track") or "other",
                "ats_score": float(job.get("ats_score") or 0),
                "resume_context": resume_text,
            }
        )["outreach_message"]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Document generation failed: {exc}") from exc

    validation = {
        "passed": result.is_valid,
        "claim_violations": result.claim_report.violations,
        "pdf_violations": result.pdf_report.violations,
    }
    save_artifact(
        user.id,
        job_id,
        resume_json=result.structured_resume.model_dump(mode="json"),
        resume_text=resume_text,
        resume_pdf=pdf_bytes,
        outreach_text=outreach,
        claim_validation=validation,
    )
    return {
        "job_id": job_id,
        "resume_text": resume_text,
        "outreach_text": outreach,
        "validation": validation,
        "quota_remaining": quota.remaining,
    }


@app.get("/me/jobs/{job_id}/artifact")
def read_artifact(job_id: int, user: AuthenticatedUser = Depends(get_workspace_user)):
    artifact = get_artifact(user.id, job_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="No generated artifact exists")
    artifact.pop("resume_pdf", None)
    return jsonable_encoder(artifact)


@app.get("/me/jobs/{job_id}/resume.pdf")
def download_resume(job_id: int, user: AuthenticatedUser = Depends(get_workspace_user)):
    artifact = get_artifact(user.id, job_id)
    if artifact is None or not artifact.get("resume_pdf"):
        raise HTTPException(status_code=404, detail="No generated resume exists")
    return Response(
        content=bytes(artifact["resume_pdf"]),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="tailored_resume.pdf"'},
    )
