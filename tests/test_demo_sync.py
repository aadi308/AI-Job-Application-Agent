from datetime import datetime, timezone

import pytest

from app.demo_sync import SuspiciousFeedDropError, _sync_board


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _RecordingConnection:
    """Small SQL boundary fake; lifecycle behavior is covered by DB tests below."""

    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.calls.append((normalized, params))
        if normalized.startswith("INSERT INTO sync_runs"):
            return _Result((7,))
        if normalized.startswith("SELECT count(*)"):
            return _Result((0,))
        return _Result()


class _PrivateCollisionConnection(_RecordingConnection):
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT id, is_demo, url FROM jobs"):
            self.calls.append((normalized, params))
            return _Result(None)
        if normalized.startswith("SELECT id, is_demo FROM jobs WHERE url"):
            self.calls.append((normalized, params))
            return _Result((99, False))
        return super().execute(query, params)


class _AnomalousDropConnection(_RecordingConnection):
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT count(*) FROM jobs") and "is_open = true" in normalized:
            self.calls.append((normalized, params))
            return _Result((10,))
        return super().execute(query, params)


class _LifecycleConnection(_RecordingConnection):
    def __init__(self):
        super().__init__()
        self.misses = 0
        self.is_open = True

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized.startswith("UPDATE jobs SET last_checked_at") and self.is_open:
            self.misses += 1
            if self.misses >= 2:
                self.is_open = False
        if normalized.startswith("SELECT count(*)"):
            self.calls.append((normalized, params))
            return _Result((0 if self.is_open else 1,))
        return super().execute(query, params)


def test_sync_does_not_publish_a_private_url_collision():
    conn = _PrivateCollisionConnection()
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    result = _sync_board(
        conn,
        {"source": "greenhouse", "board": "example", "company": "Example"},
        lambda _token: [{
            "source_job_id": "123",
            "company": "Example",
            "title": "Machine Learning Engineer",
            "url": "https://example.test/jobs/123",
            "source": "greenhouse",
            "location": "Remote - United States",
            "posted_at": now,
            "description": "Build and operate machine learning systems.",
        }],
        now,
    )

    assert not any(sql.startswith("INSERT INTO jobs") for sql, _ in conn.calls)
    assert result["inserted"] == 0


def test_sync_closes_only_after_second_successful_miss():
    conn = _LifecycleConnection()
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    first = _sync_board(
        conn,
        {"source": "lever", "board": "example", "company": "Example"},
        lambda _token: [],
        now,
    )
    assert conn.is_open is True
    assert first["closed"] == 0

    second = _sync_board(
        conn,
        {"source": "lever", "board": "example", "company": "Example"},
        lambda _token: [],
        now,
    )
    assert conn.is_open is False
    assert second["closed"] == 1

    miss_update = next(
        sql for sql, _ in conn.calls
        if sql.startswith("UPDATE jobs SET last_checked_at")
    )
    assert "consecutive_misses = consecutive_misses + 1" in miss_update
    assert "consecutive_misses + 1 >= 2 THEN false" in miss_update


def test_failed_fetch_never_updates_job_misses():
    conn = _RecordingConnection()
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def fail_fetch(_token):
        raise RuntimeError("temporary provider outage")

    with pytest.raises(RuntimeError, match="temporary provider outage"):
        _sync_board(
            conn,
            {"source": "greenhouse", "board": "example", "company": "Example"},
            fail_fetch,
            now,
        )

    assert not any(sql.startswith("UPDATE jobs") for sql, _ in conn.calls)


def test_suspicious_empty_feed_is_not_applied_as_misses():
    conn = _AnomalousDropConnection()
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    with pytest.raises(SuspiciousFeedDropError, match="returned zero jobs"):
        _sync_board(
            conn,
            {"source": "greenhouse", "board": "example", "company": "Example"},
            lambda _token: [],
            now,
        )

    assert not any(sql.startswith("UPDATE jobs") for sql, _ in conn.calls)


def _job(now, *, source_job_id="provider-1", url="https://example.test/jobs/one"):
    return {
        "source_job_id": source_job_id,
        "company": "Example",
        "title": "Machine Learning Engineer",
        "url": url,
        "source": "greenhouse",
        "location": "Remote - United States",
        "posted_at": now,
        "description": "Build and operate machine learning systems.",
    }


@pytest.mark.integration
@pytest.mark.db
def test_db_same_provider_identity_can_change_url_without_duplication():
    from app.db import get_connection

    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    board = {"source": "greenhouse", "board": "identity-change", "company": "Example"}
    with get_connection() as conn:
        try:
            _sync_board(conn, board, lambda _token: [_job(now)], now)
            changed_url = "https://example.test/jobs/one-new-url"
            _sync_board(
                conn,
                board,
                lambda _token: [_job(now, url=changed_url)],
                now,
            )
            row = conn.execute(
                """SELECT count(*), max(url) FROM jobs
                   WHERE source = %s AND board_token = %s AND source_job_id = %s""",
                ("greenhouse", "identity-change", "provider-1"),
            ).fetchone()
            assert row == (1, changed_url)
        finally:
            conn.rollback()


@pytest.mark.integration
@pytest.mark.db
def test_db_private_url_collision_is_never_published():
    from app.db import get_connection

    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    url = "https://example.test/jobs/private-collision"
    board = {"source": "greenhouse", "board": "private-collision", "company": "Example"}
    with get_connection() as conn:
        try:
            conn.execute(
                """INSERT INTO jobs (company, title, url, source, is_demo)
                   VALUES ('Private', 'Private role', %s, 'greenhouse', false)""",
                (url,),
            )
            result = _sync_board(
                conn,
                board,
                lambda _token: [_job(now, source_job_id="private-1", url=url)],
                now,
            )
            assert result["inserted"] == 0
            published = conn.execute(
                "SELECT count(*) FROM jobs WHERE url = %s AND is_demo = true", (url,)
            ).fetchone()[0]
            assert published == 0
        finally:
            conn.rollback()


@pytest.mark.integration
@pytest.mark.db
def test_db_two_misses_close_and_reappearance_reopens_job():
    from app.db import get_connection

    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    board = {"source": "greenhouse", "board": "lifecycle", "company": "Example"}
    with get_connection() as conn:
        try:
            _sync_board(conn, board, lambda _token: [_job(now)], now)
            _sync_board(conn, board, lambda _token: [], now)
            _sync_board(conn, board, lambda _token: [], now)
            assert conn.execute(
                "SELECT is_open, consecutive_misses FROM jobs WHERE board_token = 'lifecycle'"
            ).fetchone() == (False, 2)

            _sync_board(conn, board, lambda _token: [_job(now)], now)
            assert conn.execute(
                "SELECT is_open, consecutive_misses FROM jobs WHERE board_token = 'lifecycle'"
            ).fetchone() == (True, 0)
        finally:
            conn.rollback()
