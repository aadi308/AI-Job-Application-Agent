"""Runtime-mode helpers shared by the API and Streamlit dashboard."""

import os

VALID_APP_MODES = {"local", "demo", "production"}


def app_mode() -> str:
    mode = os.environ.get("APP_MODE", "local").strip().lower()
    if mode not in VALID_APP_MODES:
        raise RuntimeError(
            f"Invalid APP_MODE={mode!r}; expected one of {sorted(VALID_APP_MODES)}"
        )
    return mode


def is_demo_mode() -> bool:
    """Return whether this process is serving the public, read-only demo."""
    return app_mode() == "demo"


def is_production_mode() -> bool:
    return app_mode() == "production"


def uses_public_job_feed() -> bool:
    return app_mode() in {"demo", "production"}


def allows_manual_imports() -> bool:
    return app_mode() == "local"
