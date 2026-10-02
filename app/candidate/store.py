import json
from datetime import datetime, timezone

from app.candidate.models import ApprovedAnswer, CandidateProfile
from app.db import get_connection


def _owner(owner_id: str | None) -> str | None:
    if owner_id is None:
        return None
    value = owner_id.strip()
    if not value or len(value) > 128:
        raise ValueError("A valid authenticated owner ID is required")
    return value


def get_profile(owner_id: str | None = None) -> CandidateProfile | None:
    owner_id = _owner(owner_id)
    with get_connection() as conn, conn.cursor() as cur:
        if owner_id is None:
            cur.execute(
                """SELECT contact, education, employment, projects, skills,
                          certifications, work_authorization, preferences,
                          approved, approved_at
                   FROM candidate_profile WHERE id = 1"""
            )
        else:
            cur.execute(
                """SELECT contact, education, employment, projects, skills,
                          certifications, work_authorization, preferences,
                          approved, approved_at
                   FROM user_candidate_profiles WHERE owner_id = %s""",
                (owner_id,),
            )
        row = cur.fetchone()
        if row is None:
            return None
        return CandidateProfile(**dict(zip((c.name for c in cur.description), row)))


def _profile_values(profile: CandidateProfile, owner_id: str | None) -> dict:
    return {
        "owner_id": owner_id,
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
    }


def save_profile(profile: CandidateProfile, owner_id: str | None = None) -> None:
    owner_id = _owner(owner_id)
    values = _profile_values(profile, owner_id)
    with get_connection() as conn, conn.cursor() as cur:
        if owner_id is None:
            cur.execute(
                """INSERT INTO candidate_profile
                       (id, contact, education, employment, projects, skills,
                        certifications, work_authorization, preferences, approved,
                        approved_at, updated_at)
                   VALUES (1, %(contact)s, %(education)s, %(employment)s, %(projects)s,
                           %(skills)s, %(certifications)s, %(work_authorization)s,
                           %(preferences)s, %(approved)s, %(approved_at)s, now())
                   ON CONFLICT (id) DO UPDATE SET
                       contact=EXCLUDED.contact, education=EXCLUDED.education,
                       employment=EXCLUDED.employment, projects=EXCLUDED.projects,
                       skills=EXCLUDED.skills, certifications=EXCLUDED.certifications,
                       work_authorization=EXCLUDED.work_authorization,
                       preferences=EXCLUDED.preferences, approved=EXCLUDED.approved,
                       approved_at=EXCLUDED.approved_at, updated_at=now()""",
                values,
            )
        else:
            cur.execute(
                """INSERT INTO user_candidate_profiles
                       (owner_id, contact, education, employment, projects, skills,
                        certifications, work_authorization, preferences, approved,
                        approved_at, updated_at)
                   VALUES (%(owner_id)s, %(contact)s, %(education)s, %(employment)s,
                           %(projects)s, %(skills)s, %(certifications)s,
                           %(work_authorization)s, %(preferences)s, %(approved)s,
                           %(approved_at)s, now())
                   ON CONFLICT (owner_id) DO UPDATE SET
                       contact=EXCLUDED.contact, education=EXCLUDED.education,
                       employment=EXCLUDED.employment, projects=EXCLUDED.projects,
                       skills=EXCLUDED.skills, certifications=EXCLUDED.certifications,
                       work_authorization=EXCLUDED.work_authorization,
                       preferences=EXCLUDED.preferences, approved=EXCLUDED.approved,
                       approved_at=EXCLUDED.approved_at, updated_at=now()""",
                values,
            )
        conn.commit()


def delete_profile(owner_id: str | None = None) -> None:
    owner_id = _owner(owner_id)
    with get_connection() as conn, conn.cursor() as cur:
        if owner_id is None:
            cur.execute("DELETE FROM candidate_profile WHERE id = 1")
        else:
            cur.execute("DELETE FROM user_candidate_profiles WHERE owner_id = %s", (owner_id,))
        conn.commit()


def approve_profile(owner_id: str | None = None) -> CandidateProfile:
    profile = get_profile(owner_id)
    if profile is None:
        raise ValueError("No profile exists yet — run extraction first")
    profile.approved = True
    profile.approved_at = datetime.now(timezone.utc)
    save_profile(profile, owner_id)
    return profile


def list_answers(owner_id: str | None = None) -> list[ApprovedAnswer]:
    owner_id = _owner(owner_id)
    with get_connection() as conn, conn.cursor() as cur:
        if owner_id is None:
            cur.execute(
                "SELECT question_key, question_label, answer, source, status "
                "FROM approved_answers ORDER BY question_key"
            )
        else:
            cur.execute(
                """SELECT question_key, question_label, answer, source, status
                   FROM user_approved_answers WHERE owner_id = %s ORDER BY question_key""",
                (owner_id,),
            )
        cols = [c.name for c in cur.description]
        return [ApprovedAnswer(**dict(zip(cols, row))) for row in cur.fetchall()]


def upsert_answer(answer: ApprovedAnswer, owner_id: str | None = None) -> None:
    owner_id = _owner(owner_id)
    values = {**answer.model_dump(), "owner_id": owner_id}
    with get_connection() as conn, conn.cursor() as cur:
        if owner_id is None:
            cur.execute(
                """INSERT INTO approved_answers
                       (question_key, question_label, answer, source, status, updated_at)
                   VALUES (%(question_key)s, %(question_label)s, %(answer)s, %(source)s,
                           %(status)s, now())
                   ON CONFLICT (question_key) DO UPDATE SET
                       question_label=EXCLUDED.question_label, answer=EXCLUDED.answer,
                       source=EXCLUDED.source, status=EXCLUDED.status, updated_at=now()""",
                values,
            )
        else:
            cur.execute(
                """INSERT INTO user_approved_answers
                       (owner_id, question_key, question_label, answer, source, status, updated_at)
                   VALUES (%(owner_id)s, %(question_key)s, %(question_label)s, %(answer)s,
                           %(source)s, %(status)s, now())
                   ON CONFLICT (owner_id, question_key) DO UPDATE SET
                       question_label=EXCLUDED.question_label, answer=EXCLUDED.answer,
                       source=EXCLUDED.source, status=EXCLUDED.status, updated_at=now()""",
                values,
            )
        conn.commit()


def delete_answer(question_key: str, owner_id: str | None = None) -> None:
    owner_id = _owner(owner_id)
    with get_connection() as conn, conn.cursor() as cur:
        if owner_id is None:
            cur.execute("DELETE FROM approved_answers WHERE question_key = %s", (question_key,))
        else:
            cur.execute(
                "DELETE FROM user_approved_answers WHERE owner_id = %s AND question_key = %s",
                (owner_id, question_key),
            )
        conn.commit()
