import json
from types import SimpleNamespace

import pytest

from app.candidate.extractor import extract_profile_from_resume
from app.candidate.models import ApprovedAnswer, CandidateProfile, FieldWithEvidence
from app.candidate.store import (
    approve_profile,
    delete_answer,
    delete_profile,
    get_profile,
    list_answers,
    save_profile,
    upsert_answer,
)


@pytest.fixture
def _preserve_profile():
    """Preserve the singleton row inside the disposable integration-test database."""
    original = get_profile()
    yield
    if original is not None:
        save_profile(original)
    else:
        delete_profile()


def test_field_with_evidence_defaults_to_unresolved():
    field = FieldWithEvidence()
    assert field.status == "unresolved"
    assert field.value is None
    assert field.source is None


def test_extract_profile_preserves_evidence_and_does_not_infer_sensitive_fields(monkeypatch):
    response = {
        "contact": {
            "full_name": {"value": "Demo Candidate", "source": "header"},
            "email": {"value": "demo@example.test", "source": "header"},
        },
        "employment": [
            {
                "company": "Example Labs",
                "title": "ML Engineer",
                "dates": "2023-2025",
                "bullets": ["Deployed models with Kubernetes."],
                "source": "experience.example_labs",
            }
        ],
        "education": [
            {
                "institution": "Example University",
                "degree": "MS Computer Science",
                "dates": "2021-2023",
                "source": "education.example_university",
            }
        ],
        "skills": [{"skill": "Terraform", "source": "skills"}],
    }

    class FakeRouter:
        def generate(self, **_kwargs):
            result = SimpleNamespace(content=json.dumps(response))
            return SimpleNamespace(result=result)

    monkeypatch.setattr("app.candidate.extractor.get_router", lambda: FakeRouter())
    monkeypatch.setattr("app.candidate.extractor.record_evaluation", lambda **_kwargs: None)
    profile = extract_profile_from_resume("Synthetic resume text")

    assert profile.contact.email.value == "demo@example.test"
    assert profile.contact.email.status == "verified"
    assert profile.contact.email.source

    companies = [e.company for e in profile.employment]
    assert "Example Labs" in companies
    for entry in profile.employment:
        assert entry.source

    institutions = [e.institution for e in profile.education]
    assert "Example University" in institutions

    skills = [s.skill for s in profile.skills]
    assert any("terraform" in s.lower() for s in skills)

    # Critical safety property: fields the resume doesn't state must NOT be invented.
    assert profile.work_authorization.authorized_to_work.status == "unresolved"
    assert profile.work_authorization.authorized_to_work.value is None
    assert profile.work_authorization.requires_future_sponsorship.status == "unresolved"
    assert profile.preferences.expected_salary.status == "unresolved"
    assert profile.preferences.expected_salary.value is None
    assert profile.preferences.available_start_date.value is None


@pytest.mark.integration
@pytest.mark.db
def test_profile_round_trips_through_postgres(_preserve_profile):
    profile = CandidateProfile(
        contact={"full_name": FieldWithEvidence(value="Test Person", source="test", status="verified")}
    )
    save_profile(profile)
    reloaded = get_profile()
    assert reloaded is not None
    assert reloaded.contact.full_name.value == "Test Person"
    assert reloaded.contact.full_name.status == "verified"
    assert reloaded.approved is False


@pytest.mark.integration
@pytest.mark.db
def test_approve_profile_sets_approved_and_timestamp(_preserve_profile):
    profile = CandidateProfile()
    save_profile(profile)
    approved = approve_profile()
    assert approved.approved is True
    assert approved.approved_at is not None

    reloaded = get_profile()
    assert reloaded.approved is True
    assert reloaded.approved_at is not None


@pytest.mark.integration
@pytest.mark.db
def test_approve_profile_without_existing_profile_raises(_preserve_profile):
    delete_profile()
    with pytest.raises(ValueError, match="No profile exists"):
        approve_profile()


@pytest.mark.integration
@pytest.mark.db
def test_answer_bank_crud():
    try:
        answer = ApprovedAnswer(
            question_key="test_question",
            question_label="Are you a test?",
            answer="Yes",
            source="user_input",
            status="user_approved",
        )
        upsert_answer(answer)

        answers = list_answers()
        keys = [a.question_key for a in answers]
        assert "test_question" in keys

        updated = ApprovedAnswer(
            question_key="test_question",
            question_label="Are you a test?",
            answer="Definitely yes",
            source="user_input",
            status="user_approved",
        )
        upsert_answer(updated)
        answers = list_answers()
        match = next(a for a in answers if a.question_key == "test_question")
        assert match.answer == "Definitely yes"
    finally:
        # A failed assertion must not leave this fixture in the test answer bank.
        delete_answer("test_question")

    answers = list_answers()
    assert "test_question" not in [a.question_key for a in answers]
