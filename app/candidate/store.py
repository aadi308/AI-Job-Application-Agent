import json
from datetime import datetime, timezone

from app.candidate.models import ApprovedAnswer, CandidateProfile
from app.db import get_connection


def get_profile() -> CandidateProfile | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT contact, education, employment, projects, skills,
                       certifications, work_authorization, preferences,
                       approved, approved_at
                FROM candidate_profile WHERE id = 1
                """
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return CandidateProfile(**dict(zip(cols, row)))


def save_profile(profile: CandidateProfile) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO candidate_profile
                    (id, contact, education, employment, projects, skills,
                     certifications, work_authorization, preferences, approved, approved_at, updated_at)
                VALUES (1, %(contact)s, %(education)s, %(employment)s, %(projects)s, %(skills)s,
                        %(certifications)s, %(work_authorization)s, %(preferences)s, %(approved)s,
                        %(approved_at)s, now())
                ON CONFLICT (id) DO UPDATE SET
                    contact = EXCLUDED.contact,
                    education = EXCLUDED.education,
                    employment = EXCLUDED.employment,
                    projects = EXCLUDED.projects,
                    skills = EXCLUDED.skills,
                    certifications = EXCLUDED.certifications,
                    work_authorization = EXCLUDED.work_authorization,
                    preferences = EXCLUDED.preferences,
                    approved = EXCLUDED.approved,
                    approved_at = EXCLUDED.approved_at,
                    updated_at = now()
                """,
                {
                    "contact": json.dumps(profile.contact.model_dump()),
                    "education": json.dumps([e.model_dump() for e in profile.education]),
                    "employment": json.dumps([e.model_dump() for e in profile.employment]),
                    "projects": json.dumps([p.model_dump() for p in profile.projects]),
                    "skills": json.dumps([s.model_dump() for s in profile.skills]),
                    "certifications": json.dumps([c.model_dump() for c in profile.certifications]),
                    "work_authorization": json.dumps(profile.work_authorization.model_dump()),
                    "preferences": json.dumps(profile.preferences.model_dump()),
                    "approved": profile.approved,
                    "approved_at": profile.approved_at,
                },
            )
        conn.commit()


def delete_profile() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM candidate_profile WHERE id = 1")
        conn.commit()


def approve_profile() -> CandidateProfile:
    profile = get_profile()
    if profile is None:
        raise ValueError("No profile exists yet — run extraction first")
    profile.approved = True
    profile.approved_at = datetime.now(timezone.utc)
    save_profile(profile)
    return profile


def list_answers() -> list[ApprovedAnswer]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT question_key, question_label, answer, source, status "
                "FROM approved_answers ORDER BY question_key"
            )
            cols = [c.name for c in cur.description]
            return [ApprovedAnswer(**dict(zip(cols, row))) for row in cur.fetchall()]


def upsert_answer(answer: ApprovedAnswer) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO approved_answers (question_key, question_label, answer, source, status, updated_at)
                VALUES (%(question_key)s, %(question_label)s, %(answer)s, %(source)s, %(status)s, now())
                ON CONFLICT (question_key) DO UPDATE SET
                    question_label = EXCLUDED.question_label,
                    answer = EXCLUDED.answer,
                    source = EXCLUDED.source,
                    status = EXCLUDED.status,
                    updated_at = now()
                """,
                answer.model_dump(),
            )
        conn.commit()


def delete_answer(question_key: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM approved_answers WHERE question_key = %s", (question_key,))
        conn.commit()
