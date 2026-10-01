from fastapi.testclient import TestClient

from app.main import app
from app.runtime import is_demo_mode


def test_demo_mode_is_opt_in(monkeypatch):
    monkeypatch.delenv("APP_MODE", raising=False)
    assert not is_demo_mode()

    monkeypatch.setenv("APP_MODE", "demo")
    assert is_demo_mode()


def test_public_demo_rejects_scrape_mutations(monkeypatch):
    monkeypatch.setenv("APP_MODE", "demo")
    response = TestClient(app).post(
        "/scrape/trigger", json={"source": "greenhouse", "board": "example"}
    )
    assert response.status_code == 403
    assert "read-only demo" in response.json()["detail"]
