"""Trusted scheduled sync for the public, read-only demo feed."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import psycopg

from app.job_metadata import enrich_job
from app.job_relevance import relevance_reasons
from app.scrapers import greenhouse, lever

FETCHERS = {"greenhouse": greenhouse.fetch_jobs, "lever": lever.fetch_jobs}
DEFAULT_BOARDS_PATH = Path(__file__).resolve().parent.parent / "config" / "demo_boards.json"


class SuspiciousFeedDropError(RuntimeError):
    """Raised when a nominally successful API response looks unsafe to apply."""


def _upsert_demo_job(conn, job: dict, source: str, token: str, now: datetime) -> bool | None:
    """Upsert by stable provider identity while protecting private URL ownership.

    Returns True for an insert, False for an update, and None when publication is
    intentionally skipped because another row owns the URL.
    """
    source_job_id = str(job["source_job_id"])
    identity_row = conn.execute(
        """SELECT id, is_demo, url FROM jobs
           WHERE source = %s AND board_token = %s AND source_job_id = %s
           FOR UPDATE""",
        (source, token, source_job_id),
    ).fetchone()
    url_row = conn.execute(
        "SELECT id, is_demo FROM jobs WHERE url = %s FOR UPDATE",
        (job["url"],),
    ).fetchone()

    if url_row is not None and (not url_row[1] or (identity_row and url_row[0] != identity_row[0])):
        return None
    if identity_row is not None and not identity_row[1]:
        return None

    values = {
        **job,
        "source": source,
        "source_job_id": source_job_id,
        "board_token": token,
        "now": now,
    }
    if identity_row is not None:
        conn.execute(
            """
            UPDATE jobs SET
                company = %(company)s, title = %(title)s, url = %(url)s,
                location = %(location)s,
                posted_at = COALESCE(%(posted_at)s, posted_at),
                description = COALESCE(%(description)s, description),
                job_family = %(job_family)s,
                employment_type = %(employment_type)s,
                work_mode = %(work_mode)s,
                experience_level = %(experience_level)s,
                sponsorship_status = %(sponsorship_status)s,
                visa_categories = %(visa_categories)s,
                is_demo = true, last_seen_at = %(now)s, last_checked_at = %(now)s,
                is_open = true, consecutive_misses = 0,
                relevance_reasons = %(relevance_reasons)s, updated_at = now()
            WHERE id = %(id)s AND is_demo = true
            """,
            {**values, "id": identity_row[0]},
        )
        return False

    if url_row is not None:
        # A public row with the same canonical URL but a rotated provider ID.
        conn.execute(
            """UPDATE jobs SET
                   company = %(company)s, title = %(title)s,
                   source = %(source)s, location = %(location)s,
                   posted_at = COALESCE(%(posted_at)s, posted_at),
                   description = COALESCE(%(description)s, description),
                   job_family = %(job_family)s,
                   employment_type = %(employment_type)s,
                   work_mode = %(work_mode)s,
                   experience_level = %(experience_level)s,
                   sponsorship_status = %(sponsorship_status)s,
                   visa_categories = %(visa_categories)s,
                   board_token = %(board_token)s, source_job_id = %(source_job_id)s,
                   last_seen_at = %(now)s, last_checked_at = %(now)s,
                   is_open = true, consecutive_misses = 0,
                   relevance_reasons = %(relevance_reasons)s, updated_at = now()
               WHERE id = %(id)s AND is_demo = true""",
            {**values, "id": url_row[0]},
        )
        return False

    conn.execute(
        """
        INSERT INTO jobs (
            company, title, url, source, location, posted_at, description,
            job_family, employment_type, work_mode, experience_level,
            sponsorship_status, visa_categories, is_demo, source_job_id,
            board_token, last_seen_at, last_checked_at, is_open,
            consecutive_misses, relevance_reasons
        ) VALUES (
            %(company)s, %(title)s, %(url)s, %(source)s, %(location)s,
            %(posted_at)s, %(description)s, %(job_family)s,
            %(employment_type)s, %(work_mode)s, %(experience_level)s,
            %(sponsorship_status)s, %(visa_categories)s, true,
            %(source_job_id)s, %(board_token)s, %(now)s, %(now)s, true, 0,
            %(relevance_reasons)s
        )
        """,
        values,
    )
    return True


def load_boards(path: Path = DEFAULT_BOARDS_PATH) -> list[dict]:
    boards = json.loads(path.read_text())
    for board in boards:
        if board.get("source") not in FETCHERS or not board.get("board"):
            raise ValueError(f"Invalid demo board entry: {board!r}")
    return boards


def _sync_board(conn, board: dict, fetch: Callable[[str], list[dict]], now: datetime) -> dict:
    source, token = board["source"], board["board"]
    run_id = conn.execute(
        "INSERT INTO sync_runs (source, board_token) VALUES (%s, %s) RETURNING id",
        (source, token),
    ).fetchone()[0]
    fetched = fetch(token)
    open_count = conn.execute(
        """SELECT count(*) FROM jobs WHERE is_demo = true AND source = %s
           AND board_token = %s AND is_open = true""",
        (source, token),
    ).fetchone()[0]
    if not fetched and open_count >= 5:
        raise SuspiciousFeedDropError(
            f"{source}/{token} returned zero jobs while {open_count} were open"
        )
    relevant = []
    for raw in fetched:
        accepted, reasons = relevance_reasons(raw)
        if accepted:
            job = enrich_job({
                **raw,
                "company": board.get("company") or raw.get("company") or token,
            })
            job["relevance_reasons"] = reasons
            relevant.append(job)

    if open_count >= 5 and len(relevant) < max(1, open_count // 5):
        raise SuspiciousFeedDropError(
            f"{source}/{token} relevant jobs dropped from {open_count} to {len(relevant)}"
        )

    seen_ids: list[str] = []
    inserted = 0
    for job in relevant:
        published = _upsert_demo_job(conn, job, source, token, now)
        if published is None:
            continue
        seen_ids.append(str(job["source_job_id"]))
        inserted += int(published)

    if seen_ids:
        conn.execute(
            """
            UPDATE jobs SET last_checked_at = %s,
                consecutive_misses = consecutive_misses + 1,
                is_open = CASE WHEN consecutive_misses + 1 >= 2 THEN false ELSE is_open END,
                updated_at = now()
            WHERE is_demo = true AND source = %s AND board_token = %s
              AND is_open = true AND NOT (source_job_id = ANY(%s))
            """,
            (now, source, token, seen_ids),
        )
    else:
        conn.execute(
            """UPDATE jobs SET last_checked_at = %s,
                consecutive_misses = consecutive_misses + 1,
                is_open = CASE WHEN consecutive_misses + 1 >= 2 THEN false ELSE is_open END,
                updated_at = now()
                WHERE is_demo = true AND source = %s AND board_token = %s AND is_open = true""",
            (now, source, token),
        )
    closed = conn.execute(
        """SELECT count(*) FROM jobs WHERE is_demo = true AND source = %s
           AND board_token = %s AND is_open = false AND last_checked_at = %s""",
        (source, token, now),
    ).fetchone()[0]
    conn.execute(
        """UPDATE sync_runs SET completed_at = %s, status = 'success',
           fetched_count = %s, relevant_count = %s, inserted_count = %s,
           closed_count = %s WHERE id = %s""",
        (now, len(fetched), len(relevant), inserted, closed, run_id),
    )
    return {"source": source, "board": token, "fetched": len(fetched),
            "relevant": len(relevant), "inserted": inserted, "closed": closed}


def sync_demo_jobs(database_url: str, boards: list[dict] | None = None) -> list[dict]:
    results = []
    with psycopg.connect(database_url) as conn:
        for board in boards or load_boards():
            now = datetime.now(timezone.utc)
            try:
                result = _sync_board(conn, board, FETCHERS[board["source"]], now)
                conn.commit()
                results.append(result)
            except Exception as exc:
                # A database error leaves PostgreSQL's transaction aborted, and a fetch
                # failure must not leave any partial miss updates behind. Roll the board
                # transaction back, then record the failure in a clean transaction.
                conn.rollback()
                conn.execute(
                    """INSERT INTO sync_runs (
                           source, board_token, started_at, completed_at, status, error_message
                       ) VALUES (%s, %s, %s, %s, 'failed', %s)""",
                    (
                        board["source"], board["board"], now, now,
                        str(exc)[:1000],
                    ),
                )
                conn.commit()
                results.append({
                    "source": board["source"],
                    "board": board["board"],
                    "status": "failed",
                })
    return results
