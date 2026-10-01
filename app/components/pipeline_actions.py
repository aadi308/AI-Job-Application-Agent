import os

import pandas as pd
import requests
import streamlit as st

from app.components.db_viewer import STATUS_OPTIONS
from app.db import get_connection

_render_hostport = os.environ.get("FASTAPI_HOSTPORT")
FASTAPI_URL = (
    os.environ.get("FASTAPI_URL")
    or (f"http://{_render_hostport}" if _render_hostport else None)
    or "http://127.0.0.1:8000"
).rstrip("/")


def trigger_scrape(source: str, board: str) -> dict:
    resp = requests.post(
        f"{FASTAPI_URL}/scrape/trigger",
        json={"source": source, "board": board},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def update_status(job_id: int, new_status: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = %s, updated_at = now() WHERE id = %s",
                (new_status, job_id),
            )
        conn.commit()


def render_scrape_trigger():
    st.sidebar.header("Scrape a board")
    source = st.sidebar.selectbox("Source", ["greenhouse", "lever"])
    board = st.sidebar.text_input("Board slug", placeholder="e.g. asana, palantir")
    if st.sidebar.button("Trigger scrape", disabled=not board):
        try:
            result = trigger_scrape(source, board)
            st.sidebar.success(f"Fetched {result['fetched']}, inserted {result['inserted']} new.")
            st.rerun()
        except requests.exceptions.ConnectionError:
            st.sidebar.error(
                f"Can't reach the FastAPI server at {FASTAPI_URL}. "
                "Check `FASTAPI_URL`, or start it locally with:\n\n"
                "`uvicorn app.main:app --host 127.0.0.1 --port 8000`"
            )
        except requests.exceptions.HTTPError as e:
            detail = e.response.json().get("detail", str(e)) if e.response is not None else str(e)
            st.sidebar.error(f"Scrape failed: {detail}")


def render_status_updater(job: pd.Series):
    st.write("**Update status**")
    current = job.get("status") or "discovered"
    new_status = st.selectbox(
        "New status",
        STATUS_OPTIONS,
        index=STATUS_OPTIONS.index(current),
        key=f"status_{job['id']}",
    )
    if st.button("Save status", key=f"save_status_{job['id']}"):
        update_status(int(job["id"]), new_status)
        st.success(f"Status updated to '{new_status}'.")
        st.rerun()
