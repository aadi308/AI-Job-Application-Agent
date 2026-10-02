import sys
from pathlib import Path

# `streamlit run app/dashboard.py` puts this file's own directory (app/) on sys.path,
# not the project root, so `import app.*` can't resolve without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from app.runtime import is_demo_mode, is_production_mode

demo_mode = is_demo_mode()
production_mode = is_production_mode()
if not production_mode:
    from app.components.db_viewer import fetch_jobs, render_filters, render_table
    from app.components.job_inspector import render_job_detail
if not demo_mode and not production_mode:
    from app.components.pipeline_actions import render_scrape_trigger, render_status_updater
    from app.components.profile_editor import render_profile_editor

st.set_page_config(page_title="AI Job Application Agent", layout="wide")

if production_mode:
    from app.components.production_ui import render_production_app

    render_production_app()
    st.stop()

if demo_mode:
    st.sidebar.info("Public read-only demo · daily employer-board feed · no paid model calls")
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
    st.title("AI Job Application Agent")

    if demo_mode:
        st.info(
            "This read-only feed tracks relevant US AI/ML roles from allowlisted employers' "
            "public Greenhouse and Lever boards and refreshes daily. A listing being live on an "
            "employer board reduces ghost-job risk but cannot prove active hiring; verify the "
            "posting before applying. Clone the project for private candidate workflows."
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
