import httpx
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.auth import AuthenticatedUser, SupabaseAuthClient


def test_supabase_auth_client_uses_expected_rest_endpoints_and_identity():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"})
        if request.url.path.endswith("/user"):
            return httpx.Response(200, json={"id": "user-a", "email": "a@example.test"})
        raise AssertionError(f"Unexpected request: {request.url}")

    with SupabaseAuthClient(
        "https://example.supabase.co",
        "public-anon-key",
        transport=httpx.MockTransport(handler),
    ) as client:
        tokens = client.sign_in("a@example.test", "safe-test-password")
        user = client.get_user(tokens["access_token"])

    assert user == AuthenticatedUser(id="user-a", email="a@example.test")
    assert requests[0].url.params["grant_type"] == "password"
    assert requests[0].headers["apikey"] == "public-anon-key"
    assert requests[1].headers["authorization"] == "Bearer access"


def test_protected_route_rejects_missing_bearer_token():
    app = FastAPI()

    @app.get("/private")
    def private(user: AuthenticatedUser = Depends(auth.get_current_user)):
        return {"owner_id": user.id}

    response = TestClient(app).get("/private")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_protected_route_uses_verified_identity_not_request_owner(monkeypatch):
    class StubAuthClient:
        def get_user(self, token: str) -> AuthenticatedUser:
            assert token == "valid-token"
            return AuthenticatedUser(id="verified-owner", email="owner@example.test")

    monkeypatch.setattr(auth, "get_auth_client", lambda: StubAuthClient())
    app = FastAPI()

    @app.get("/private")
    def private(
        owner_id: str,
        user: AuthenticatedUser = Depends(auth.get_current_user),
    ):
        return {"requested_owner": owner_id, "actual_owner": user.id}

    response = TestClient(app).get(
        "/private?owner_id=attacker-choice",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "requested_owner": "attacker-choice",
        "actual_owner": "verified-owner",
    }


def test_protected_route_rejects_invalid_token(monkeypatch):
    class RejectingAuthClient:
        def get_user(self, token: str):
            raise auth.AuthenticationError("Invalid token")

    monkeypatch.setattr(auth, "get_auth_client", lambda: RejectingAuthClient())
    app = FastAPI()

    @app.get("/private")
    def private(user: AuthenticatedUser = Depends(auth.get_current_user)):
        return {"owner_id": user.id}

    response = TestClient(app).get(
        "/private", headers={"Authorization": "Bearer invalid-token"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid token"}
