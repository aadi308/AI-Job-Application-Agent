from typing import Optional, TypedDict


class JobApplicationState(TypedDict):
    job_id: int
    company: str
    title: str
    location: Optional[str]
    description: Optional[str]
    track: str
    ats_score: float
    resume_context: str  # still used by networking_node for tone/background
    tailored_resume: Optional[str]  # plain-text preview of the structured resume
    resume_json: Optional[dict]  # StructuredResume.model_dump()
    resume_pdf_path: Optional[str]  # staged PDF path, not yet in outputs/
    resume_valid: Optional[bool]  # claim_report.passed and pdf_report.passed
    resume_claim_violations: list[str]
    resume_pdf_violations: list[str]
    outreach_message: Optional[str]
    human_approved: Optional[bool]
    human_feedback: Optional[str]
