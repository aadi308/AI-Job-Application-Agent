import pytest

from app.db import get_connection
from app.usage import (
    ATS_EVALUATION,
    RESUME_GENERATION,
    QuotaExceeded,
    consume_daily_quota,
    get_daily_usage,
)


def test_quota_rejects_unknown_actions_without_database_access():
    with pytest.raises(ValueError, match="Unsupported quota action"):
        consume_daily_quota(None, "user-a", "unbounded_action", 1)


@pytest.mark.integration
@pytest.mark.db
def test_daily_quota_is_isolated_by_owner_and_action():
    owners = ("quota-test-user-a", "quota-test-user-b")
    with get_connection() as conn:
        conn.execute("DELETE FROM usage_events WHERE owner_id = ANY(%s)", (list(owners),))
        try:
            first = consume_daily_quota(conn, owners[0], ATS_EVALUATION, daily_limit=2)
            second = consume_daily_quota(conn, owners[0], ATS_EVALUATION, daily_limit=2)
            other_user = consume_daily_quota(conn, owners[1], ATS_EVALUATION, daily_limit=2)
            other_action = consume_daily_quota(conn, owners[0], RESUME_GENERATION, daily_limit=1)

            assert (first.used, first.remaining) == (1, 1)
            assert (second.used, second.remaining) == (2, 0)
            assert (other_user.used, other_user.remaining) == (1, 1)
            assert (other_action.used, other_action.remaining) == (1, 0)
            assert get_daily_usage(conn, owners[0], ATS_EVALUATION) == 2

            with pytest.raises(QuotaExceeded, match="limit of 2"):
                consume_daily_quota(conn, owners[0], ATS_EVALUATION, daily_limit=2)
            with pytest.raises(QuotaExceeded, match="limit of 1"):
                consume_daily_quota(conn, owners[0], RESUME_GENERATION, daily_limit=1)
        finally:
            conn.execute("DELETE FROM usage_events WHERE owner_id = ANY(%s)", (list(owners),))


@pytest.mark.integration
@pytest.mark.db
def test_global_quota_caps_multi_account_usage():
    owners = ("global-quota-user-a", "global-quota-user-b", "global-quota-user-c")
    with get_connection() as conn:
        conn.execute("DELETE FROM usage_events WHERE action = %s", (ATS_EVALUATION,))
        try:
            consume_daily_quota(
                conn, owners[0], ATS_EVALUATION, daily_limit=1, global_daily_limit=2
            )
            consume_daily_quota(
                conn, owners[1], ATS_EVALUATION, daily_limit=1, global_daily_limit=2
            )
            with pytest.raises(QuotaExceeded, match="Daily service"):
                consume_daily_quota(
                    conn, owners[2], ATS_EVALUATION, daily_limit=1, global_daily_limit=2
                )
        finally:
            conn.execute("DELETE FROM usage_events WHERE owner_id = ANY(%s)", (list(owners),))
