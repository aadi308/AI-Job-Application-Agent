import json
from dataclasses import dataclass
from pathlib import Path

from app.candidate.models import CandidateProfile
from app.resume.models import ClaimValidationReport, PDFValidationReport, StructuredResume
from app.resume.pdf import html_to_pdf
from app.resume.pdf_validate import validate_pdf
from app.resume.tailor import tailor_resume
from app.resume.template import render_html
from app.resume.validate_claims import validate_claims


@dataclass
class ResumeGenerationResult:
    structured_resume: StructuredResume
    claim_report: ClaimValidationReport
    pdf_report: PDFValidationReport
    pdf_path: str
    html: str

    @property
    def is_valid(self) -> bool:
        return self.claim_report.passed and self.pdf_report.passed


def generate_tailored_resume(
    profile: CandidateProfile,
    company: str,
    title: str,
    description: str | None,
    output_dir: str,
    file_prefix: str,
) -> ResumeGenerationResult:
    resume = tailor_resume(profile, company, title, description)
    claim_report = validate_claims(resume, profile)

    html = render_html(resume)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    pdf_path = str(Path(output_dir) / f"{file_prefix}_resume.pdf")
    html_to_pdf(html, pdf_path)

    pdf_report = validate_pdf(
        pdf_path,
        expected_email=profile.contact.email.value or "",
        expected_phone=profile.contact.phone.value,
    )

    return ResumeGenerationResult(resume, claim_report, pdf_report, pdf_path, html)


def build_diff_report(resume: StructuredResume, profile: CandidateProfile) -> dict:
    """Which real bullets got included vs left out per employer, so a human can see what
    the tailoring step trimmed."""
    profile_jobs = {job.company: job for job in profile.employment}
    entries = []
    for entry in resume.experience:
        real_job = profile_jobs.get(entry.company)
        included_sources = {b.source_bullet.strip().lower() for b in entry.bullets}
        all_bullets = real_job.bullets if real_job else []
        entries.append(
            {
                "company": entry.company,
                "included_bullets": [b.text for b in entry.bullets],
                "excluded_bullets": [
                    b for b in all_bullets if b.strip().lower() not in included_sources
                ],
            }
        )
    return {"experience": entries}


def build_evidence_report(resume: StructuredResume) -> dict:
    """Every tailored bullet paired with the real profile bullet it was derived from."""
    return {
        "experience": [
            {
                "company": entry.company,
                "bullets": [{"text": b.text, "source": b.source_bullet} for b in entry.bullets],
            }
            for entry in resume.experience
        ]
    }


def save_artifacts(
    result: ResumeGenerationResult, profile: CandidateProfile, output_dir: str, file_prefix: str
) -> dict[str, str]:
    """Saves structured resume JSON, diff report, evidence report, and PDF validation
    report alongside the PDF (already written by generate_tailored_resume). Returns a
    dict of artifact name -> file path."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths = {"pdf": result.pdf_path}

    resume_json_path = out / f"{file_prefix}_resume.json"
    resume_json_path.write_text(result.structured_resume.model_dump_json(indent=2))
    paths["resume_json"] = str(resume_json_path)

    diff_path = out / f"{file_prefix}_diff_report.json"
    diff_path.write_text(json.dumps(build_diff_report(result.structured_resume, profile), indent=2))
    paths["diff_report"] = str(diff_path)

    evidence_path = out / f"{file_prefix}_evidence_report.json"
    evidence_path.write_text(json.dumps(build_evidence_report(result.structured_resume), indent=2))
    paths["evidence_report"] = str(evidence_path)

    claim_validation_path = out / f"{file_prefix}_claim_validation.json"
    claim_validation_path.write_text(result.claim_report.model_dump_json(indent=2))
    paths["claim_validation_report"] = str(claim_validation_path)

    pdf_validation_path = out / f"{file_prefix}_pdf_validation.json"
    pdf_validation_path.write_text(result.pdf_report.model_dump_json(indent=2))
    paths["pdf_validation_report"] = str(pdf_validation_path)

    return paths
