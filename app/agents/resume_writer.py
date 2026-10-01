from pathlib import Path

from app.agents.state import JobApplicationState
from app.candidate.store import get_profile
from app.llm.audit import get_latest_evaluation, is_production_eligible
from app.resume.pipeline import generate_tailored_resume, save_artifacts

STAGING_DIR = Path(__file__).resolve().parent.parent.parent / "outputs" / ".staging"


def _plain_text_preview(resume) -> str:
    lines = [resume.header.full_name]
    contact_bits = [
        v
        for v in [
            resume.header.email,
            resume.header.phone,
            resume.header.location,
            resume.header.linkedin,
            resume.header.github,
            resume.header.portfolio,
        ]
        if v
    ]
    lines.append(" · ".join(contact_bits))
    lines.append("")
    lines.append("SUMMARY")
    lines.append(resume.summary)
    lines.append("")
    lines.append("SKILLS")
    lines.append(", ".join(resume.skills))
    lines.append("")
    lines.append("EXPERIENCE")
    for job in resume.experience:
        lines.append(f"{job.title} — {job.company} ({job.dates})")
        for b in job.bullets:
            lines.append(f"  - {b.text}")
    lines.append("")
    lines.append("EDUCATION")
    for edu in resume.education:
        lines.append(f"{edu.degree} — {edu.institution} ({edu.dates})")
    if resume.certifications:
        lines.append("")
        lines.append("CERTIFICATIONS")
        for c in resume.certifications:
            lines.append(f"{c.name}" + (f" — {c.issuer}" if c.issuer else ""))
    return "\n".join(lines)


def resume_writer_node(state: JobApplicationState) -> dict:
    profile = get_profile()
    if profile is None:
        raise RuntimeError(
            "No candidate profile exists yet. Run Phase 5's extraction and approve it "
            "in the dashboard before generating tailored resumes."
        )
    if not profile.approved:
        raise RuntimeError(
            "Candidate profile exists but hasn't been approved yet. Review and approve "
            "it in the dashboard (Candidate Profile page) before generating resumes — "
            "unapproved profile data shouldn't be used for real application materials."
        )

    # Re-check production eligibility against the audit trail directly, rather than
    # trusting that jobs.ats_score being non-null still implies it — this is the gate
    # Step 10 asks for before resume tailoring/PDF generation specifically.
    evaluation = get_latest_evaluation(state["job_id"], agent_name="ats_evaluator")
    if evaluation is None or not is_production_eligible(
        evaluation_status=evaluation["evaluation_status"],
        evaluation_source=evaluation["evaluation_source"],
        confidence=evaluation["confidence"],
        validation_errors=evaluation["validation_errors"],
    ):
        raise RuntimeError(
            f"Job {state['job_id']}'s ATS evaluation is not production-eligible "
            f"(status={evaluation['evaluation_status'] if evaluation else 'no evaluation found'}) "
            "— cannot generate a resume from an unreliable or mock evaluation."
        )

    file_prefix = f"job-{state['job_id']}"
    result = generate_tailored_resume(
        profile=profile,
        company=state["company"],
        title=state["title"],
        description=state.get("description"),
        output_dir=str(STAGING_DIR),
        file_prefix=file_prefix,
    )
    # Write resume.json, diff/evidence/validation reports to staging now, so approval
    # in run_workflow.py only needs to copy files, not reconstruct anything from state.
    save_artifacts(result, profile, output_dir=str(STAGING_DIR), file_prefix=file_prefix)

    return {
        "tailored_resume": _plain_text_preview(result.structured_resume),
        "resume_json": result.structured_resume.model_dump(),
        "resume_pdf_path": result.pdf_path,
        "resume_valid": result.is_valid,
        "resume_claim_violations": result.claim_report.violations,
        "resume_pdf_violations": result.pdf_report.violations,
    }
