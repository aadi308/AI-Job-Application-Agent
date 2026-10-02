"""Authenticated, API-only Streamlit UI for the public production deployment."""

from __future__ import annotations

import json
import os

import pandas as pd
import streamlit as st

from app.api_client import APIClient, APIError
from app.auth import AuthenticationError, SupabaseAuthClient
from app.candidate.models import CandidateProfile

STATUS_OPTIONS = ["discovered", "applied", "interviewing", "offer", "rejected", "withdrawn"]
JOB_FAMILY_OPTIONS = [
    "ai_ml", "data", "devops_cloud", "software", "security", "qa_testing",
    "product", "design", "sales_marketing", "hr_recruiting", "finance", "healthcare", "other",
]
EMPLOYMENT_TYPE_OPTIONS = ["full_time", "part_time", "contract", "internship", "temporary", "unknown"]
WORK_MODE_OPTIONS = ["remote", "hybrid", "onsite", "unknown"]
EXPERIENCE_LEVEL_OPTIONS = ["internship", "entry", "mid", "senior", "lead", "executive", "unknown"]
SPONSORSHIP_OPTIONS = ["available", "not_available", "mentioned_review_required", "not_specified"]
VISA_OPTIONS = ["h1b", "f1_opt", "stem_opt", "ead", "green_card", "us_citizen"]


def _format_option(value: str) -> str:
    labels = {
        "ai_ml": "AI / ML", "devops_cloud": "DevOps / Cloud", "qa_testing": "QA / Testing",
        "hr_recruiting": "HR / Recruiting", "h1b": "H-1B", "f1_opt": "F-1 / OPT",
        "stem_opt": "STEM OPT", "ead": "EAD", "us_citizen": "U.S. citizenship",
        "not_available": "Sponsorship not available", "available": "Sponsorship available",
        "mentioned_review_required": "Mentioned — review required", "not_specified": "Not specified",
    }
    return labels.get(value, value.replace("_", " ").title())


def _auth_client() -> SupabaseAuthClient:
    return SupabaseAuthClient(
        os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_ANON_KEY", "")
    )


def render_authentication() -> APIClient | None:
    session = st.session_state.get("auth_session")
    if session and session.get("access_token"):
        try:
            with _auth_client() as auth:
                user = auth.get_user(session["access_token"])
            st.sidebar.success(user.email or "Signed in")
            if st.sidebar.button("Sign out"):
                st.session_state.pop("auth_session", None)
                st.rerun()
            return APIClient(session["access_token"])
        except (AuthenticationError, RuntimeError):
            refresh_token = session.get("refresh_token")
            if refresh_token:
                try:
                    with _auth_client() as auth:
                        refreshed = auth.refresh(refresh_token)
                    st.session_state["auth_session"] = refreshed
                    st.rerun()
                except (AuthenticationError, RuntimeError):
                    pass
            st.session_state.pop("auth_session", None)

    st.title("AI Job Application Agent")
    st.write(
        "Create a private workspace to evaluate job fit, tailor an evidence-backed resume, "
        "and track applications. Your profile and generated documents are isolated from other users."
    )
    sign_in, sign_up = st.tabs(["Sign in", "Create account"])
    with sign_in:
        with st.form("sign_in"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            try:
                with _auth_client() as auth:
                    st.session_state["auth_session"] = auth.sign_in(email, password)
                st.rerun()
            except (AuthenticationError, RuntimeError) as exc:
                st.error(str(exc))
    with sign_up:
        with st.form("sign_up"):
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password (at least 6 characters)", type="password", key="signup_pw")
            submitted = st.form_submit_button("Create account")
        if submitted:
            try:
                with _auth_client() as auth:
                    response = auth.sign_up(email, password)
                if response.get("access_token"):
                    st.session_state["auth_session"] = response
                    st.rerun()
                st.success("Account created. Check your email to confirm it, then sign in.")
            except (AuthenticationError, RuntimeError) as exc:
                st.error(str(exc))
    return None


def _get_profile(api: APIClient) -> dict | None:
    try:
        return api.get("/me/profile")
    except APIError as exc:
        if "No candidate profile" in str(exc):
            return None
        raise


def render_profile(api: APIClient) -> None:
    st.header("My Candidate Profile")
    st.caption("Only your signed-in account can access this profile and its generated documents.")
    try:
        profile = _get_profile(api)
    except APIError as exc:
        st.error(str(exc))
        return

    uploaded = st.file_uploader("Upload resume PDF", type=["pdf"])
    if uploaded and st.button("Extract profile from resume", type="primary"):
        try:
            with st.spinner("Extracting resume evidence..."):
                result = api.post(
                    "/me/profile/extract",
                    data=uploaded.getvalue(),
                    content_type="application/pdf",
                )
            profile = result["profile"]
            st.success(f"Profile extracted. {result['quota_remaining']} generation credit(s) remain today.")
        except APIError as exc:
            st.error(str(exc))

    if profile is None:
        st.info("Upload a resume, or create an empty profile and fill the JSON editor.")
        if st.button("Create empty profile"):
            try:
                profile = api.put("/me/profile", json=CandidateProfile().model_dump(mode="json"))
                st.rerun()
            except APIError as exc:
                st.error(str(exc))
        return

    if profile.get("approved"):
        st.success("Approved and ready for job evaluation.")
    else:
        st.warning("Review and save the profile, then approve it before evaluation.")

    edited = st.text_area(
        "Profile data",
        value=json.dumps(profile, indent=2),
        height=500,
        help="Only include truthful facts. Saving changes requires approval again.",
    )
    save_col, approve_col = st.columns(2)
    if save_col.button("Save profile"):
        try:
            payload = json.loads(edited)
            api.put("/me/profile", json=payload)
            st.success("Saved. Review once more, then approve.")
            st.rerun()
        except (ValueError, APIError) as exc:
            st.error(f"Could not save profile: {exc}")
    if approve_col.button("Approve profile", type="primary"):
        try:
            api.post("/me/profile/approve")
            st.success("Profile approved.")
            st.rerun()
        except APIError as exc:
            st.error(str(exc))


def _filter_jobs(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filters")
    search = st.sidebar.text_input("Job title, company, or keyword")
    location = st.sidebar.text_input("Location")
    families = st.sidebar.multiselect("Job family", JOB_FAMILY_OPTIONS, format_func=_format_option)
    modes = st.sidebar.multiselect("Work mode", WORK_MODE_OPTIONS, format_func=_format_option)
    types = st.sidebar.multiselect("Employment type", EMPLOYMENT_TYPE_OPTIONS, format_func=_format_option)
    levels = st.sidebar.multiselect("Experience level", EXPERIENCE_LEVEL_OPTIONS, format_func=_format_option)
    sponsorship = st.sidebar.multiselect("Sponsorship", SPONSORSHIP_OPTIONS, format_func=_format_option)
    visas = st.sidebar.multiselect("Authorization / visa mentions", VISA_OPTIONS, format_func=_format_option)
    statuses = st.sidebar.multiselect("My status", STATUS_OPTIONS)
    minimum = st.sidebar.slider("Minimum ATS score", 0, 100, 0, 5)
    result = df.copy()
    if search:
        haystack = result[["title", "company", "description"]].fillna("").agg(" ".join, axis=1)
        result = result[haystack.str.contains(search, case=False, regex=False)]
    if location:
        result = result[result["location"].fillna("").str.contains(location, case=False, regex=False)]
    for selected, column in (
        (families, "job_family"), (modes, "work_mode"), (types, "employment_type"),
        (levels, "experience_level"), (sponsorship, "sponsorship_status"), (statuses, "status"),
    ):
        if selected:
            result = result[result[column].isin(selected)]
    if visas:
        result = result[result["visa_categories"].apply(lambda values: bool(set(values or []) & set(visas)))]
    if minimum:
        result = result[pd.to_numeric(result["ats_score"], errors="coerce").fillna(-1) >= minimum]
    return result


def render_jobs(api: APIClient) -> None:
    st.title("AI Job Application Agent")
    try:
        jobs = api.get("/jobs")
    except APIError as exc:
        st.error(str(exc))
        return
    if not jobs:
        st.warning("No currently verified matching jobs are available. The feed refreshes daily.")
        return
    df = _filter_jobs(pd.DataFrame(jobs))
    st.caption(f"{len(df)} job(s) match your filters")
    columns = [
        "company", "title", "location", "work_mode", "employment_type",
        "experience_level", "sponsorship_status", "status", "ats_score",
    ]
    event = st.dataframe(
        df[columns], hide_index=True, width="stretch", selection_mode="single-row",
        on_select="rerun", key="production_jobs",
    )
    if not event.selection.rows:
        st.info("Select a job to evaluate fit, tailor a resume, or update its status.")
        return
    job = df.iloc[event.selection.rows[0]].to_dict()
    st.subheader(f"{job['company']} — {job['title']}")
    st.link_button("Open employer posting ↗", job["url"], type="primary")
    st.write(job.get("description") or "No description available.")
    if job.get("eval_summary"):
        st.info(job["eval_summary"])

    status_value = st.selectbox(
        "My application status", STATUS_OPTIONS,
        index=STATUS_OPTIONS.index(job.get("status", "discovered")),
    )
    if st.button("Save status"):
        try:
            api.put(f"/me/jobs/{job['id']}/status", json={"status": status_value})
            st.success("Status saved.")
            st.rerun()
        except APIError as exc:
            st.error(str(exc))

    if st.button("Evaluate job fit", type="primary"):
        try:
            with st.spinner("Evaluating against your approved evidence..."):
                result = api.post(f"/me/jobs/{job['id']}/evaluate")
            if result["meta"].get("production_eligible"):
                st.success(f"Evaluation completed. {result['quota_remaining']} evaluation credit(s) remain today.")
                st.rerun()
            else:
                st.error(f"Evaluation did not pass the reliability gate: {result['meta']}")
        except APIError as exc:
            st.error(str(exc))

    if st.button("Generate tailored resume + outreach"):
        try:
            with st.spinner("Generating and validating application materials..."):
                result = api.post(f"/me/jobs/{job['id']}/generate")
            st.session_state[f"artifact_{job['id']}"] = result
            st.success(f"Generated. {result['quota_remaining']} generation credit(s) remain today.")
        except APIError as exc:
            st.error(str(exc))

    artifact = st.session_state.get(f"artifact_{job['id']}")
    if artifact is None and (job.get("has_resume") or job.get("has_outreach")):
        try:
            artifact = api.get(f"/me/jobs/{job['id']}/artifact")
        except APIError:
            artifact = None
    if artifact:
        validation = artifact.get("validation") or artifact.get("claim_validation") or {}
        if validation.get("passed"):
            st.success("Resume passed claim and PDF validation.")
        else:
            st.warning("Review validation findings before using this resume.")
            st.json(validation)
        st.text_area("Tailored resume", artifact.get("resume_text", ""), height=400)
        st.text_area("Outreach draft", artifact.get("outreach_text", ""), height=180)
        try:
            pdf = api.get(f"/me/jobs/{job['id']}/resume.pdf", raw=True)
            st.download_button("Download tailored resume PDF", pdf, "tailored_resume.pdf", "application/pdf")
        except APIError:
            pass


def render_production_app() -> None:
    api = render_authentication()
    if api is None:
        return
    page = st.sidebar.radio("Page", ["Jobs", "Candidate Profile"])
    if page == "Candidate Profile":
        render_profile(api)
    else:
        render_jobs(api)
