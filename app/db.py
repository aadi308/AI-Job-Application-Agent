import os

import psycopg
from dotenv import load_dotenv
from sqlalchemy import create_engine

from app.job_metadata import enrich_job

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

_engine = None


def get_connection():
    return psycopg.connect(DATABASE_URL)


def get_engine():
    """SQLAlchemy engine for pandas.read_sql — plain psycopg connections work but pandas
    warns and falls back to an untested path without SQLAlchemy."""
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg://"))
    return _engine


def upsert_job(conn, job: dict) -> bool:
    """Insert a job, or backfill its description if the URL already exists.

    Returns True if a new row was inserted, False if an existing row was matched
    (and possibly had its description backfilled).
    """
    job = enrich_job(job)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (
                company, title, url, source, location, posted_at, description,
                job_family, employment_type, work_mode, experience_level,
                sponsorship_status, visa_categories
            )
            VALUES (
                %(company)s, %(title)s, %(url)s, %(source)s, %(location)s, %(posted_at)s,
                %(description)s, %(job_family)s, %(employment_type)s, %(work_mode)s,
                %(experience_level)s, %(sponsorship_status)s, %(visa_categories)s
            )
            ON CONFLICT (url) DO UPDATE SET
                title = EXCLUDED.title,
                location = EXCLUDED.location,
                posted_at = EXCLUDED.posted_at,
                description = COALESCE(EXCLUDED.description, jobs.description),
                job_family = EXCLUDED.job_family,
                employment_type = EXCLUDED.employment_type,
                work_mode = EXCLUDED.work_mode,
                experience_level = EXCLUDED.experience_level,
                sponsorship_status = EXCLUDED.sponsorship_status,
                visa_categories = EXCLUDED.visa_categories,
                updated_at = now()
            RETURNING (xmax = 0) AS inserted
            """,
            job,
        )
        return cur.fetchone()[0]
