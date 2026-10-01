"""Initialize a fresh external PostgreSQL database for hosted deployments.

The advisory transaction lock makes this safe when the API and dashboard start at
the same time. Existing databases are left untouched; schema evolution should move
to a migration tool when the schema changes after the first public release.
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
DEMO_SEED_PATH = Path(__file__).resolve().parent.parent / "db" / "demo_seed.sql"
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"
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

        if os.environ.get("APP_MODE", "local").strip().lower() == "demo":
            for statement in DEMO_SEED_PATH.read_text().split(";"):
                if statement.strip():
                    conn.execute(statement)

    return not exists


if __name__ == "__main__":
    created = initialize_database()
    print("Database schema created." if created else "Database schema already exists.")
