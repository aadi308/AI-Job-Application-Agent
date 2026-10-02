"""Supabase authentication client and FastAPI authorization dependencies.

Tokens are validated by Supabase Auth's ``/user`` endpoint.  The application
never accepts a user identifier from request data; ownership is derived from
the verified bearer token instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


class AuthConfigurationError(RuntimeError):
    """Raised when the server is missing its Supabase configuration."""


class AuthenticationError(RuntimeError):
    """Raised when Supabase rejects an authentication operation."""


@dataclass(frozen=True)
class AuthenticatedUser:
    """The identity fields the application may trust after verification."""

    id: str
    email: str | None = None


class SupabaseAuthClient:
    """Small Supabase Auth REST client with no SDK-specific global state."""

    def __init__(
        self,
        supabase_url: str,
        anon_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not supabase_url or not anon_key:
            raise AuthConfigurationError(
                "SUPABASE_URL and SUPABASE_ANON_KEY are required"
            )
        self._base_url = f"{supabase_url.rstrip('/')}/auth/v1"
        self._anon_key = anon_key
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"apikey": anon_key, "Content-Type": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SupabaseAuthClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def sign_up(self, email: str, password: str) -> dict[str, Any]:
        return self._request("POST", "/signup", json={"email": email, "password": password})

    def sign_in(self, email: str, password: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/token",
            params={"grant_type": "password"},
            json={"email": email, "password": password},
        )

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/token",
            params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token},
        )

    def get_user(self, access_token: str) -> AuthenticatedUser:
        payload = self._request(
            "GET", "/user", headers={"Authorization": f"Bearer {access_token}"}
        )
        user_id = payload.get("id")
        if not isinstance(user_id, str) or not user_id:
            raise AuthenticationError("Authentication provider returned no user identity")
        email = payload.get("email")
        return AuthenticatedUser(id=user_id, email=email if isinstance(email, str) else None)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise AuthenticationError("Authentication service is unavailable") from exc

        if response.is_error:
            message = "Authentication request was rejected"
            try:
                body = response.json()
                candidate = body.get("msg") or body.get("message") or body.get("error_description")
                if isinstance(candidate, str) and candidate:
                    message = candidate
            except ValueError:
                pass
            raise AuthenticationError(message)

        try:
            body = response.json()
        except ValueError as exc:
            raise AuthenticationError("Authentication provider returned an invalid response") from exc
        if not isinstance(body, dict):
            raise AuthenticationError("Authentication provider returned an invalid response")
        return body


@lru_cache(maxsize=1)
def get_auth_client() -> SupabaseAuthClient:
    """Return the process-wide auth client configured from server-side variables."""

    return SupabaseAuthClient(
        os.environ.get("SUPABASE_URL", ""),
        os.environ.get("SUPABASE_ANON_KEY", ""),
    )


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    """FastAPI dependency that resolves a verified bearer token to its owner."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return get_auth_client().get_user(credentials.credentials)
    except (AuthConfigurationError, AuthenticationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
