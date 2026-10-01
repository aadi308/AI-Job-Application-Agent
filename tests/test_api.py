import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app

pytestmark = [pytest.mark.integration, pytest.mark.db]

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_trigger_scrape_greenhouse_is_idempotent(monkeypatch):
    jobs = [
        {
            "company": "Example Co",
            "title": "ML Engineer",
            "url": "https://example.test/jobs/ml-engineer-ci-fixture",
            "source": "greenhouse",
            "location": "Remote",
            "posted_at": None,
            "description": "Build and operate machine-learning systems.",
        }
    ]
    monkeypatch.setitem(main_module.SCRAPERS, "greenhouse", lambda _: jobs)

    payload = {"source": "greenhouse", "board": "gitlab"}
    first = client.post("/scrape/trigger", json=payload)
    assert first.status_code == 200
    assert first.json()["fetched"] > 0

    second = client.post("/scrape/trigger", json=payload)
    assert second.status_code == 200
    assert second.json()["inserted"] == 0
