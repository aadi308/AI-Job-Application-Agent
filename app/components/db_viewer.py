import pandas as pd
import streamlit as st
from sqlalchemy import text

from app.db import get_engine
from app.runtime import is_demo_mode

STATUS_OPTIONS = ["discovered", "applied", "interviewing", "offer", "rejected", "withdrawn"]
JOB_FAMILY_OPTIONS = [
    "ai_ml", "data", "devops_cloud", "software", "security", "qa_testing",
    "product", "design", "sales_marketing", "hr_recruiting", "finance",
    "healthcare", "other",
]
EMPLOYMENT_TYPE_OPTIONS = ["full_time", "part_time", "contract", "internship", "temporary", "unknown"]
WORK_MODE_OPTIONS = ["remote", "hybrid", "onsite", "unknown"]
EXPERIENCE_LEVEL_OPTIONS = ["internship", "entry", "mid", "senior", "lead", "executive", "unknown"]
SPONSORSHIP_OPTIONS = ["available", "not_available", "mentioned_review_required", "not_specified"]
VISA_OPTIONS = ["h1b", "f1_opt", "stem_opt", "ead", "green_card", "us_citizen"]


def _format_option(value: str) -> str:
    labels = {
        "ai_ml": "AI / ML",
        "devops_cloud": "DevOps / Cloud",
        "qa_testing": "QA / Testing",
        "hr_recruiting": "HR / Recruiting",
        "h1b": "H-1B",
        "f1_opt": "F-1 / OPT",
        "stem_opt": "STEM OPT",
        "ead": "EAD",
        "us_citizen": "U.S. citizenship",
        "not_available": "Sponsorship not available",
        "available": "Sponsorship available",
        "mentioned_review_required": "Mentioned — review required",
        "not_specified": "Not specified",
    }
    return labels.get(value, value.replace("_", " ").title())


def fetch_jobs(
    job_family: list[str] | None = None,
    status: list[str] | None = None,
    location: str = "",
    employment_type: list[str] | None = None,
    work_mode: list[str] | None = None,
    sponsorship_status: list[str] | None = None,
    visa_categories: list[str] | None = None,
    experience_level: list[str] | None = None,
    min_score: int | None = None,
    scored_only: bool = False,
    search: str = "",
) -> pd.DataFrame:
    clauses = ["1=1"]
    params: dict = {}

    if is_demo_mode():
        clauses.append("is_demo = true")
    if job_family:
        clauses.append("job_family = ANY(:job_family)")
        params["job_family"] = job_family
    if status:
        clauses.append("status::text = ANY(:status)")
        params["status"] = status
    if location:
        clauses.append("location ILIKE :location")
        params["location"] = f"%{location}%"
    if employment_type:
        clauses.append("employment_type = ANY(:employment_type)")
        params["employment_type"] = employment_type
    if work_mode:
        clauses.append("work_mode = ANY(:work_mode)")
        params["work_mode"] = work_mode
    if sponsorship_status:
        clauses.append("sponsorship_status = ANY(:sponsorship_status)")
        params["sponsorship_status"] = sponsorship_status
    if visa_categories:
        clauses.append("visa_categories && CAST(:visa_categories AS text[])")
        params["visa_categories"] = visa_categories
    if experience_level:
        clauses.append("experience_level = ANY(:experience_level)")
        params["experience_level"] = experience_level
    if min_score:
        clauses.append("ats_score >= :min_score")
        params["min_score"] = min_score
    if scored_only:
        clauses.append("ats_score IS NOT NULL")
    if search:
        clauses.append("(company ILIKE :search OR title ILIKE :search)")
        params["search"] = f"%{search}%"

    query = f"""
        SELECT id, company, title, url, location, source, status, track, ats_score,
               eval_summary, description, discovered_at, evaluated_at, job_family,
               employment_type, work_mode, experience_level, sponsorship_status,
               visa_categories
        FROM jobs
        WHERE {' AND '.join(clauses)}
        ORDER BY ats_score DESC NULLS LAST, id
    """
    return pd.read_sql(text(query), get_engine(), params=params)


def render_filters() -> dict:
    st.sidebar.header("Filters")
    search = st.sidebar.text_input("Job title, company, or keyword")
    location = st.sidebar.text_input("Location")
    job_family = st.sidebar.multiselect(
        "Job family", JOB_FAMILY_OPTIONS, format_func=_format_option
    )
    work_mode = st.sidebar.multiselect(
        "Work mode", WORK_MODE_OPTIONS, format_func=_format_option
    )
    employment_type = st.sidebar.multiselect(
        "Employment type", EMPLOYMENT_TYPE_OPTIONS, format_func=_format_option
    )
    experience_level = st.sidebar.multiselect(
        "Experience level", EXPERIENCE_LEVEL_OPTIONS, format_func=_format_option
    )
    sponsorship_status = st.sidebar.multiselect(
        "Sponsorship", SPONSORSHIP_OPTIONS, format_func=_format_option,
        help="Derived only from explicit wording in the posting; always verify on the employer page.",
    )
    visa_categories = st.sidebar.multiselect(
        "Authorization / visa mentions", VISA_OPTIONS, format_func=_format_option,
        help="Filters explicit mentions such as H-1B, OPT, STEM OPT, EAD, green card, or citizenship.",
    )
    status = st.sidebar.multiselect("Status", STATUS_OPTIONS)
    min_score = st.sidebar.slider("Minimum ATS score", 0, 100, 0, step=5)
    scored_only = st.sidebar.checkbox("Scored jobs only", value=False)
    return {
        "job_family": job_family or None,
        "status": status or None,
        "location": location,
        "employment_type": employment_type or None,
        "work_mode": work_mode or None,
        "sponsorship_status": sponsorship_status or None,
        "visa_categories": visa_categories or None,
        "experience_level": experience_level or None,
        "min_score": min_score or None,
        "scored_only": scored_only,
        "search": search,
    }


def render_table(df: pd.DataFrame):
    st.caption(f"{len(df)} job(s) match the current filters")
    display_cols = [
        "id", "company", "title", "location", "work_mode", "employment_type",
        "experience_level", "sponsorship_status", "job_family", "status", "ats_score",
    ]
    event = st.dataframe(
        df[display_cols],
        hide_index=True,
        width="stretch",
        selection_mode="single-row",
        on_select="rerun",
        key="jobs_table",
    )
    selected_rows = event.selection.rows if event and event.selection else []
    if selected_rows:
        return df.iloc[selected_rows[0]]
    return None
