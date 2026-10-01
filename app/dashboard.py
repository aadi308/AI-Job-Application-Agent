import sys
from pathlib import Path

# `streamlit run app/dashboard.py` puts this file's own directory (app/) on sys.path,
# not the project root, so `import app.*` can't resolve without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from app.components.db_viewer import fetch_jobs, render_filters, render_table
from app.components.job_inspector import render_job_detail
from app.runtime import is_demo_mode

demo_mode = is_demo_mode()
if not demo_mode:
    from app.components.pipeline_actions import render_scrape_trigger, render_status_updater
    from app.components.profile_editor import render_profile_editor

st.set_page_config(page_title="AI Job Search Dashboard", layout="wide")

if demo_mode:
    st.sidebar.info("Public read-only demo · fictional data · no paid model calls")
else:
    st.sidebar.warning(
        "Private local mode · candidate details come from your persistent PostgreSQL database"
    )

pages = ["Jobs"] if demo_mode else ["Jobs", "Candidate Profile"]
page = st.sidebar.radio("Page", pages)
st.sidebar.divider()

if page == "Candidate Profile":
    render_profile_editor()
else:
    st.title("AI Job Search Dashboard")

    if demo_mode:
        st.info(
            "This hosted demo uses fictional data and is read-only. Clone the project and run "
            "it locally to scrape boards, edit a candidate profile, or generate new artifacts."
        )

    if not demo_mode:
        render_scrape_trigger()
    filters = render_filters()

    df = fetch_jobs(**filters)
    selected_job = render_table(df)

    st.divider()

    if selected_job is not None:
        render_job_detail(selected_job)
        if not demo_mode:
            render_status_updater(selected_job)
    else:
        st.info("Select a row in the table above to see job details, tailored resume, and outreach draft.")
