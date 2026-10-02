"""Atomic per-user daily usage limits for paid or rate-limited operations."""

from __future__ import annotations

from dataclasses import dataclass


ATS_EVALUATION = "ats_evaluation"
RESUME_GENERATION = "resume_generation"
ALLOWED_ACTIONS = frozenset({ATS_EVALUATION, RESUME_GENERATION})


@dataclass(frozen=True)
class UsageResult:
    action: str
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class QuotaExceeded(RuntimeError):
    def __init__(self, action: str, limit: int, scope: str = "user") -> None:
        self.action = action
        self.limit = limit
        self.scope = scope
        prefix = "Daily service" if scope == "global" else "Daily"
        super().__init__(f"{prefix} {action} limit of {limit} has been reached")


def consume_daily_quota(
    conn,
    owner_id: str,
    action: str,
    daily_limit: int,
    global_daily_limit: int | None = None,
) -> UsageResult:
    """Atomically consume one daily quota unit inside the caller's transaction.

    A transaction-scoped advisory lock serializes attempts for one
    owner/action/day while allowing unrelated users and actions to proceed.
    """

    if not owner_id:
        raise ValueError("owner_id is required")
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported quota action: {action}")
    if daily_limit < 1:
        raise ValueError("daily_limit must be at least 1")
    if global_daily_limit is not None and global_daily_limit < daily_limit:
        raise ValueError("global_daily_limit must be at least the per-user daily_limit")

    with conn.cursor() as cur:
        # Always acquire the global lock first to keep lock ordering deterministic.
        if global_daily_limit is not None:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"usage:global:{action}",),
            )
            cur.execute(
                """
                SELECT count(*) FROM usage_events
                WHERE action = %s AND created_at >= CURRENT_DATE
                  AND created_at < CURRENT_DATE + INTERVAL '1 day'
                """,
                (action,),
            )
            if cur.fetchone()[0] >= global_daily_limit:
                raise QuotaExceeded(action, global_daily_limit, scope="global")
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"usage:{owner_id}:{action}",),
        )
        cur.execute(
            """
            SELECT count(*)
            FROM usage_events
            WHERE owner_id = %s
              AND action = %s
              AND created_at >= CURRENT_DATE
              AND created_at < CURRENT_DATE + INTERVAL '1 day'
            """,
            (owner_id, action),
        )
        used = cur.fetchone()[0]
        if used >= daily_limit:
            raise QuotaExceeded(action, daily_limit)
        cur.execute(
            "INSERT INTO usage_events (owner_id, action) VALUES (%s, %s)",
            (owner_id, action),
        )
    return UsageResult(action=action, used=used + 1, limit=daily_limit)


def get_daily_usage(conn, owner_id: str, action: str) -> int:
    """Return today's recorded calls for one owner and action."""

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM usage_events
            WHERE owner_id = %s
              AND action = %s
              AND created_at >= CURRENT_DATE
              AND created_at < CURRENT_DATE + INTERVAL '1 day'
            """,
            (owner_id, action),
        )
        return cur.fetchone()[0]
