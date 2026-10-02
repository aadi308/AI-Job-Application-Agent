from fastapi.testclient import TestClient

from app import main as main_module
from app.auth import AuthenticatedUser
from app.main import app


def _client(owner_id: str = "verified-user") -> TestClient:
    app.dependency_overrides[main_module.get_workspace_user] = lambda: AuthenticatedUser(
        id=owner_id, email=f"{owner_id}@example.test"
    )
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_jobs_uses_verified_owner(monkeypatch):
    observed = []
    monkeypatch.setattr(
        main_module,
        "list_jobs",
        lambda owner_id: observed.append(owner_id) or [{"id": 1, "title": "ML Engineer"}],
    )

    response = _client("user-a").get("/jobs")

    assert response.status_code == 200
    assert response.json()[0]["title"] == "ML Engineer"
    assert observed == ["user-a"]


def test_profile_write_is_owner_scoped_and_invalidates_approval(monkeypatch):
    saved = []
    monkeypatch.setattr(
        main_module,
        "save_profile",
        lambda profile, owner_id: saved.append((profile, owner_id)),
    )
    payload = {
        "approved": True,
        "approved_at": "2026-01-01T00:00:00Z",
        "skills": [{"skill": "Python", "source": "resume", "status": "verified"}],
    }

    response = _client("user-b").put("/me/profile", json=payload)

    assert response.status_code == 200
    assert saved[0][1] == "user-b"
    assert saved[0][0].approved is False
    assert saved[0][0].approved_at is None


def test_artifact_download_cannot_select_another_owner(monkeypatch):
    observed = []

    def fake_get_artifact(owner_id, job_id):
        observed.append((owner_id, job_id))
        return None

    monkeypatch.setattr(main_module, "get_artifact", fake_get_artifact)

    response = _client("user-c").get("/me/jobs/42/resume.pdf")

    assert response.status_code == 404
    assert observed == [("user-c", 42)]


def test_protected_application_route_rejects_anonymous_request():
    response = TestClient(app).get("/jobs")
    assert response.status_code == 401
