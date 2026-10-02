"""Initialize a fresh external PostgreSQL database for hosted deployments.

The advisory transaction lock makes this safe when the API and dashboard start at
the same time. Existing databases are left untouched; schema evolution should move
to a migration tool when the schema changes after the first public release.
"""

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Running ``python scripts/init_db.py`` puts scripts/ rather than the repository root
# first on sys.path. Add the root before importing app modules so the README command
# works from a fresh clone without requiring an editable package install.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.job_metadata import enrich_job


SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
DEMO_SEED_PATH = PROJECT_ROOT / "db" / "demo_seed.sql"
MIGRATIONS_DIR = PROJECT_ROOT / "db" / "migrations"
LOCK_NAME = "ai-job-search-agent-schema-init"


def initialize_database() -> bool:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    with psycopg.connect(database_url) as conn:
        # Serialize startup for the two Render services sharing one Neon database.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_NAME,))
        exists = conn.execute("SELECT to_regclass('public.jobs') IS NOT NULL").fetchone()[0]
        if not exists:
            for statement in SCHEMA_PATH.read_text().split(";"):
                if statement.strip():
                    conn.execute(statement)

        # Apply idempotent compatibility migrations even when a Docker volume or hosted
        # database predates the current schema. This preserves existing private data.
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            for statement in migration.read_text().split(";"):
                if statement.strip():
                    conn.execute(statement)

        # Backfill filter metadata for jobs collected before these columns existed.
        rows = conn.execute(
            "SELECT id, title, location, description FROM jobs WHERE is_demo = false"
        ).fetchall()
        for job_id, title, location, description in rows:
            metadata = enrich_job(
                {"title": title, "location": location, "description": description}
            )
            conn.execute(
                """
                UPDATE jobs SET
                    job_family = %(job_family)s,
                    employment_type = %(employment_type)s,
                    work_mode = %(work_mode)s,
                    experience_level = %(experience_level)s,
                    sponsorship_status = %(sponsorship_status)s,
                    visa_categories = %(visa_categories)s
                WHERE id = %(id)s
                """,
                {"id": job_id, **metadata},
            )

        # Fictional fixtures are opt-in for screenshots/tests. Production demo rows are
        # populated by the scheduled, allowlisted employer-board sync instead.
        if os.environ.get("SEED_DEMO_DATA", "false").strip().lower() == "true":
            for statement in DEMO_SEED_PATH.read_text().split(";"):
                if statement.strip():
                    conn.execute(statement)

    return not exists


if __name__ == "__main__":
    created = initialize_database()
    print("Database schema created." if created else "Database schema already exists.")
