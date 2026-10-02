import pytest

from app.candidate.models import CandidateProfile, ContactInfo, EmploymentEntry, FieldWithEvidence
from app.resume.models import ResumeBullet, ResumeExperienceEntry, ResumeHeader, StructuredResume
from app.resume.pdf import html_to_pdf
from app.resume.pdf_validate import validate_pdf
from app.resume.pipeline import build_diff_report, build_evidence_report, generate_tailored_resume
from app.resume.tailor import _build_resume
from app.resume.template import render_html
from app.resume.validate_claims import validate_claims


def _make_profile(bullets=("Reduced latency by 20% using caching.",)):
    return CandidateProfile(
        contact=ContactInfo(
            full_name=FieldWithEvidence(value="Test Person", status="verified"),
            email=FieldWithEvidence(value="test@example.com", status="verified"),
            phone=FieldWithEvidence(value="555-0100", status="verified"),
        ),
        employment=[
            EmploymentEntry(
                company="Acme Corp", title="Engineer", dates="2020-2022",
                bullets=list(bullets), source="test",
            )
        ],
    )


def _make_resume(text: str, source_bullet: str, company="Acme Corp", title="Engineer", dates="2020-2022"):
    return StructuredResume(
        header=ResumeHeader(full_name="Test Person", email="test@example.com", phone="555-0100"),
        summary="A test summary.",
        experience=[
            ResumeExperienceEntry(
                company=company, title=title, dates=dates,
                bullets=[ResumeBullet(text=text, source_bullet=source_bullet)],
            )
        ],
    )


def test_claim_validation_catches_invented_metric():
    profile = _make_profile()
    bad = _make_resume(
        "Reduced latency by 80% using caching.", "Reduced latency by 20% using caching."
    )
    report = validate_claims(bad, profile)
    assert not report.passed
    assert any("80%" in v for v in report.violations)


def test_claim_validation_catches_unverifiable_bullet():
    profile = _make_profile()
    bad = _make_resume("Led a team of 10 engineers.", "Led a team of 10 engineers.")
    report = validate_claims(bad, profile)
    assert not report.passed
    assert any("does not match any real bullet" in v for v in report.violations)


def test_claim_validation_catches_fake_employer():
    profile = _make_profile()
    bad = StructuredResume(
        header=ResumeHeader(full_name="Test Person", email="test@example.com"),
        summary="s",
        experience=[ResumeExperienceEntry(company="Google", title="Engineer", dates="2020-2022")],
    )
    report = validate_claims(bad, profile)
    assert not report.passed
    assert any("Employer not found" in v for v in report.violations)


def test_claim_validation_allows_dropping_plus_modifier():
    profile = _make_profile(bullets=["Maintained 99%+ uptime across services."])
    good = _make_resume(
        "Maintained uptime above 99% across services.", "Maintained 99%+ uptime across services."
    )
    report = validate_claims(good, profile)
    assert report.passed, report.violations


def test_claim_validation_handles_same_company_different_titles():
    """A candidate with two roles at the same employer (e.g. intern then full-time) must be
    matched by (company, title), not company alone."""
    profile = CandidateProfile(
        contact=ContactInfo(email=FieldWithEvidence(value="test@example.com", status="verified")),
        employment=[
            EmploymentEntry(
                company="Acme Corp", title="Senior Engineer", dates="2022-2024",
                bullets=["Led the platform team."], source="test",
            ),
            EmploymentEntry(
                company="Acme Corp", title="Intern", dates="2021-2022",
                bullets=["Assisted with onboarding."], source="test",
            ),
        ],
    )
    resume = _make_resume(
        "Led the platform team.", "Led the platform team.",
        company="Acme Corp", title="Senior Engineer", dates="2022-2024",
    )
    report = validate_claims(resume, profile)
    assert report.passed, report.violations


@pytest.mark.integration
def test_html_to_pdf_produces_extractable_text(tmp_path):
    resume = _make_resume("Reduced latency by 20% using caching.", "Reduced latency by 20% using caching.")
    html = render_html(resume)
    pdf_path = str(tmp_path / "out.pdf")
    html_to_pdf(html, pdf_path)

    report = validate_pdf(pdf_path, expected_email="test@example.com", expected_phone="555-0100")
    assert report.passed, report.violations
    assert report.page_count == 1
    assert report.extracted_text_length > 0


@pytest.mark.integration
def test_pdf_validation_flags_missing_contact_info(tmp_path):
    resume = _make_resume("Reduced latency by 20% using caching.", "Reduced latency by 20% using caching.")
    html = render_html(resume)
    pdf_path = str(tmp_path / "out.pdf")
    html_to_pdf(html, pdf_path)

    report = validate_pdf(pdf_path, expected_email="someone-else@example.com", expected_phone=None)
    assert not report.passed
    assert any("email" in v for v in report.violations)


def test_diff_and_evidence_reports_reflect_real_bullets():
    profile = _make_profile(
        bullets=["Reduced latency by 20% using caching.", "Wrote documentation."]
    )
    resume = _make_resume("Reduced latency by 20% using caching.", "Reduced latency by 20% using caching.")

    diff = build_diff_report(resume, profile)
    assert diff["experience"][0]["excluded_bullets"] == ["Wrote documentation."]

    evidence = build_evidence_report(resume)
    assert evidence["experience"][0]["bullets"][0]["source"] == "Reduced latency by 20% using caching."


def test_resume_builder_uses_exact_verified_bullets_and_grounded_summary():
    profile = _make_profile(bullets=("Deployed Kubernetes services with Terraform.",))
    selection = {
        "summary": "Invented claim that must be ignored.",
        "employer_selections": [{"employer_index": 0, "bullet_indices": [0]}],
        "skill_indices": [],
        "project_indices": [],
        "certification_indices": [],
    }
    resume = _build_resume(selection, profile, company="Target Co", title="Platform Engineer")

    assert resume.experience[0].bullets[0].text == "Deployed Kubernetes services with Terraform."
    assert resume.experience[0].bullets[0].source_bullet == resume.experience[0].bullets[0].text
    assert "Invented claim" not in resume.summary
    assert "Platform Engineer" in resume.summary


@pytest.mark.live
def test_full_pipeline_with_live_llm_and_synthetic_input(tmp_path, monkeypatch):
    """Opt-in live LLM call and real PDF generation using only synthetic input."""
    monkeypatch.setattr("app.resume.tailor.record_evaluation", lambda **_kwargs: 1)
    profile = _make_profile(
        bullets=("Deployed Kubernetes services with Terraform on AWS.",)
    )

    result = generate_tailored_resume(
        profile=profile,
        company="Test Co",
        title="Senior DevOps Engineer",
        description="We need someone with Terraform, Kubernetes, and AWS experience.",
        output_dir=str(tmp_path),
        file_prefix="integration_test",
    )

    assert result.claim_report.passed, result.claim_report.violations
    assert result.pdf_report.passed, result.pdf_report.violations
    assert result.pdf_report.page_count <= 2
    assert result.is_valid
