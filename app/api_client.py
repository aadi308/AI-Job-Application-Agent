"""Authenticated HTTP client used by the production Streamlit frontend."""

from __future__ import annotations

import os
from typing import Any

import requests


class APIError(RuntimeError):
    pass


def api_base_url() -> str:
    explicit = os.environ.get("FASTAPI_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    hostport = os.environ.get("FASTAPI_HOSTPORT", "").strip()
    if hostport:
        return f"http://{hostport.rstrip('/')}"
    return "http://127.0.0.1:8000"


class APIClient:
    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: bytes | None = None,
        content_type: str | None = None,
        timeout: float = 120.0,
        raw: bool = False,
    ):
        headers = {"Authorization": f"Bearer {self._token}"}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            response = requests.request(
                method,
                f"{api_base_url()}{path}",
                headers=headers,
                json=json,
                data=data,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise APIError("The application API is temporarily unavailable") from exc
        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise APIError(str(detail or f"API request failed ({response.status_code})"))
        if raw:
            return response.content
        if response.status_code == 204:
            return None
        return response.json()

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.request("DELETE", path, **kwargs)
