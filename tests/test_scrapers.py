from datetime import datetime, timezone

import pytest

from app.scrapers import greenhouse, lever


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_greenhouse_fetch_jobs_returns_expected_shape(monkeypatch):
    payload = {
        "jobs": [
            {
                "company_name": "Example Labs",
                "title": "ML Engineer",
                "absolute_url": "https://example.test/jobs/1",
                "location": {"name": "Remote"},
                "first_published": "2026-01-15T12:00:00+00:00",
                "content": "<p>Build reliable ML systems.</p>",
            }
        ]
    }
    monkeypatch.setattr(greenhouse.requests, "get", lambda *args, **kwargs: FakeResponse(payload))
    jobs = greenhouse.fetch_jobs("gitlab")
    assert len(jobs) > 0
    job = jobs[0]
    assert job["source"] == "greenhouse"
    assert job["title"]
    assert job["url"].startswith("https://")


def test_lever_fetch_jobs_returns_expected_shape(monkeypatch):
    payload = [
        {
            "text": "MLOps Engineer",
            "hostedUrl": "https://example.test/jobs/2",
            "createdAt": int(datetime(2026, 1, 15, tzinfo=timezone.utc).timestamp() * 1000),
            "categories": {"location": "New York, NY"},
            "descriptionPlain": "Operate machine-learning infrastructure.",
            "lists": [],
        }
    ]
    monkeypatch.setattr(lever.requests, "get", lambda *args, **kwargs: FakeResponse(payload))
    jobs = lever.fetch_jobs("palantir")
    assert len(jobs) > 0
    job = jobs[0]
    assert job["source"] == "lever"
    assert job["title"]
    assert job["url"].startswith("https://")


def test_lever_fetch_jobs_raises_on_unknown_company(monkeypatch):
    monkeypatch.setattr(
        lever.requests,
        "get",
        lambda *args, **kwargs: FakeResponse({"ok": False, "error": "not found"}, 404),
    )
    with pytest.raises(ValueError, match="not found"):
        lever.fetch_jobs("this-company-does-not-exist-xyz")
