"""Runtime-mode helpers shared by the API and Streamlit dashboard."""

import os


def is_demo_mode() -> bool:
    """Return whether this process is serving the public, read-only demo."""
    return os.environ.get("APP_MODE", "local").strip().lower() == "demo"
