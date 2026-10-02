import pytest

from app.candidate.models import ApprovedAnswer, CandidateProfile, SkillEntry
from app.candidate.store import get_profile, list_answers, save_profile, upsert_answer
from app.db import get_connection
from app.user_workspace import get_artifact, save_artifact, set_job_status

pytestmark = [pytest.mark.integration, pytest.mark.db]


def test_private_records_are_isolated_between_users():
    owners = ("isolation-user-a", "isolation-user-b")
    job_url = "https://example.test/jobs/multi-user-isolation"
    with get_connection() as conn:
        conn.execute("DELETE FROM user_candidate_profiles WHERE owner_id = ANY(%s)", (list(owners),))
        conn.execute("DELETE FROM user_approved_answers WHERE owner_id = ANY(%s)", (list(owners),))
        conn.execute("DELETE FROM user_job_state WHERE owner_id = ANY(%s)", (list(owners),))
        conn.execute("DELETE FROM user_artifacts WHERE owner_id = ANY(%s)", (list(owners),))
        job_id = conn.execute(
            """
            INSERT INTO jobs (company, title, url, source, description, is_demo, is_open)
            VALUES ('Example Co', 'ML Engineer', %s, 'greenhouse', %s, true, true)
            ON CONFLICT (url) DO UPDATE SET is_demo = true, is_open = true
            RETURNING id
            """,
            (job_url, "A complete test job description " * 8),
        ).fetchone()[0]

    try:
        save_profile(
            CandidateProfile(skills=[SkillEntry(skill="Python", source="resume")]), owners[0]
        )
        save_profile(
            CandidateProfile(skills=[SkillEntry(skill="Go", source="resume")]), owners[1]
        )
        upsert_answer(
            ApprovedAnswer(
                question_key="sponsorship",
                question_label="Need sponsorship?",
                answer="User A answer",
                source="user_input",
            ),
            owners[0],
        )
        assert get_profile(owners[0]).skills[0].skill == "Python"
        assert get_profile(owners[1]).skills[0].skill == "Go"
        assert list_answers(owners[0])[0].answer == "User A answer"
        assert list_answers(owners[1]) == []

        assert set_job_status(owners[0], job_id, "applied")
        save_artifact(
            owners[0], job_id, resume_json={"owner": "a"}, resume_text="private A",
            resume_pdf=b"%PDF-test-a", outreach_text="hello A",
            claim_validation={"passed": True},
        )
        assert get_artifact(owners[0], job_id)["resume_text"] == "private A"
        assert get_artifact(owners[1], job_id) is None
    finally:
        with get_connection() as conn:
            conn.execute("DELETE FROM user_candidate_profiles WHERE owner_id = ANY(%s)", (list(owners),))
            conn.execute("DELETE FROM user_approved_answers WHERE owner_id = ANY(%s)", (list(owners),))
            conn.execute("DELETE FROM user_job_state WHERE owner_id = ANY(%s)", (list(owners),))
            conn.execute("DELETE FROM user_artifacts WHERE owner_id = ANY(%s)", (list(owners),))
            conn.execute("DELETE FROM jobs WHERE url = %s", (job_url,))
