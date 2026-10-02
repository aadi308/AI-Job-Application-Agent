"""Owner-scoped persistence for the authenticated application workspace."""

from __future__ import annotations

import json
from typing import Any

from app.db import get_connection


def list_jobs(owner_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """Return shared job facts joined only to the requesting user's private state."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT j.id, j.company, j.title, j.url, j.location, j.source,
                   COALESCE(s.status::text, 'discovered') AS status,
                   COALESCE(s.track, j.job_family) AS track,
                   s.ats_score, s.eval_summary, j.description, j.posted_at,
                   j.discovered_at, s.evaluated_at, j.job_family,
                   j.employment_type, j.work_mode, j.experience_level,
                   j.sponsorship_status, j.visa_categories, j.last_seen_at,
                   j.last_checked_at, j.is_open, j.relevance_reasons,
                   (a.resume_pdf IS NOT NULL) AS has_resume,
                   (a.outreach_text IS NOT NULL) AS has_outreach
            FROM jobs j
            LEFT JOIN user_job_state s
              ON s.job_id = j.id AND s.owner_id = %s
            LEFT JOIN user_artifacts a
              ON a.job_id = j.id AND a.owner_id = %s
            WHERE j.is_demo = true AND j.is_open = true
              AND j.source_job_id IS NOT NULL
              AND j.last_checked_at >= now() - interval '72 hours'
            ORDER BY j.posted_at DESC NULLS LAST, j.discovered_at DESC, j.id DESC
            LIMIT %s
            """,
            (owner_id, owner_id, limit),
        )
        columns = [column.name for column in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_job(owner_id: str, job_id: int) -> dict[str, Any] | None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT j.id, j.company, j.title, j.url, j.location, j.source,
                   COALESCE(s.status::text, 'discovered') AS status,
                   COALESCE(s.track, j.job_family) AS track,
                   s.ats_score, s.eval_summary, j.description, j.job_family,
                   j.employment_type, j.work_mode, j.experience_level,
                   j.sponsorship_status, j.visa_categories
            FROM jobs j
            LEFT JOIN user_job_state s
              ON s.job_id = j.id AND s.owner_id = %s
            WHERE j.id = %s AND j.is_demo = true AND j.is_open = true
            """,
            (owner_id, job_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip((column.name for column in cur.description), row))


def set_job_status(owner_id: str, job_id: int, status: str) -> bool:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM jobs WHERE id = %s AND is_open = true", (job_id,))
        if cur.fetchone() is None:
            return False
        cur.execute(
            """
            INSERT INTO user_job_state (owner_id, job_id, status, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (owner_id, job_id) DO UPDATE
            SET status = EXCLUDED.status, updated_at = now()
            """,
            (owner_id, job_id, status),
        )
        conn.commit()
        return True


def save_artifact(
    owner_id: str,
    job_id: int,
    *,
    resume_json: dict,
    resume_text: str,
    resume_pdf: bytes,
    outreach_text: str,
    claim_validation: dict,
) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_artifacts
                (owner_id, job_id, resume_json, resume_text, resume_pdf,
                 outreach_text, claim_validation, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (owner_id, job_id) DO UPDATE SET
                resume_json = EXCLUDED.resume_json,
                resume_text = EXCLUDED.resume_text,
                resume_pdf = EXCLUDED.resume_pdf,
                outreach_text = EXCLUDED.outreach_text,
                claim_validation = EXCLUDED.claim_validation,
                updated_at = now()
            """,
            (
                owner_id,
                job_id,
                json.dumps(resume_json),
                resume_text,
                resume_pdf,
                outreach_text,
                json.dumps(claim_validation),
            ),
        )
        conn.commit()


def get_artifact(owner_id: str, job_id: int) -> dict[str, Any] | None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT resume_json, resume_text, resume_pdf, outreach_text,
                   claim_validation, updated_at
            FROM user_artifacts
            WHERE owner_id = %s AND job_id = %s
            """,
            (owner_id, job_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip((column.name for column in cur.description), row))
