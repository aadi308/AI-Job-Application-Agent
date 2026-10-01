import os

import pytest


# Application modules read DATABASE_URL while pytest is collecting test modules. Keep
# ordinary unit-test collection independent of a developer's .env, and only point at a
# database when the caller explicitly supplies a disposable test database.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
else:
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql://job_search_test:job_search_test@127.0.0.1:5432/job_search_test",
    )


def pytest_collection_modifyitems(config, items):
    no_test_db = pytest.mark.skip(
        reason="set TEST_DATABASE_URL to an isolated database to run integration tests"
    )
    live_disabled = pytest.mark.skip(
        reason="set RUN_LIVE_TESTS=true to run live/network/paid tests"
    )
    live_enabled = os.environ.get("RUN_LIVE_TESTS", "").lower() == "true"

    for item in items:
        if "db" in item.keywords and not TEST_DATABASE_URL:
            item.add_marker(no_test_db)
        if "live" in item.keywords and not live_enabled:
            item.add_marker(live_disabled)
