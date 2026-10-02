import io
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st
from pypdf import PdfReader

from app.runtime import is_demo_mode

# Keep the public demo lightweight: these imports load the workflow graph, vector store,
# provider clients, and PDF pipeline, but demo mode only renders pre-generated artifacts.
if not is_demo_mode():
    from app.agents.ats_evaluator import evaluate_job_by_id
    from app.agents.supervisor import build_graph
    from app.agents.workflow_service import resolve_review, start_review
    from app.candidate.store import get_profile
    from app.llm.audit import get_latest_evaluation, is_production_eligible

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "outputs"
EXAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


@st.cache_resource
def _get_graph():
    # Cached once per server process (not per session/rerun) so the graph's in-memory
    # MemorySaver checkpointer survives between the "Generate" click and the later
    # "Approve"/"Reject" click — those are two separate Streamlit script reruns, and a
    # fresh checkpointer each time would lose the paused graph state in between.
    return build_graph()


def _pending_review_key(job_id: int) -> str:
    return f"pending_review_{job_id}"


def _find_output_file(job_id: int, suffix: str) -> Path | None:
    matches = list(OUTPUT_DIR.glob(f"{job_id}_*{suffix}"))
    return matches[0] if matches else None


def _apply_ready_filename(fallback: str) -> str:
    """outputs/<id>_<company>_<title>_resume.pdf is the right filename for tracking which
    file belongs to which application, but it's not what should land in a recruiter's
    inbox or an ATS upload — real name, no job ID or company, is what actually gets
    submitted. Falls back to the tracking name if there's no approved profile with a name
    yet, rather than guessing."""
    profile = get_profile()
    name = profile.contact.full_name.value if profile else None
    if not name:
        return fallback
    safe = re.sub(r"[^A-Za-z ]", "", name).strip()
    parts = safe.split()
    if not parts:
        return fallback
    return "_".join(parts) + "_Resume.pdf"


def _render_generate_flow(job_id: int) -> None:
    if is_demo_mode():
        st.info(
            "Live ATS re-evaluation and resume generation are disabled in the public demo "
            "to protect provider credentials and prevent unexpected API charges."
        )
        return

    pending_key = _pending_review_key(job_id)
    flash_key = f"flash_{job_id}"

    if flash_key in st.session_state:
        kind, message = st.session_state.pop(flash_key)
        getattr(st, kind)(message)

    if pending_key not in st.session_state:
        profile = get_profile()
        profile_ready = bool(profile and profile.approved)
        description_ready = bool(job_id and st.session_state.get(f"job_description_ready_{job_id}", True))
        latest_evaluation = get_latest_evaluation(job_id, agent_name="ats_evaluator")
        evaluation_ready = bool(
            latest_evaluation
            and is_production_eligible(
                evaluation_status=latest_evaluation["evaluation_status"],
                evaluation_source=latest_evaluation["evaluation_source"],
                confidence=latest_evaluation["confidence"],
                validation_errors=latest_evaluation["validation_errors"],
            )
        )

        st.markdown("**Resume readiness**")
        checks = st.columns(3)
        checks[0].success("Profile approved") if profile_ready else checks[0].error("Approve profile")
        checks[1].success("Job description available") if description_ready else checks[1].error("Description missing")
        checks[2].success("ATS evaluation verified") if evaluation_ready else checks[2].warning("Evaluation required")

        if not profile_ready:
            st.error("Complete and approve Candidate Profile before generating application materials.")
            return
        if not description_ready:
            st.error("A complete job description is required for reliable tailoring.")
            return
        if not evaluation_ready:
            st.info("Evaluate this job against the approved profile before tailoring the resume.")
            if st.button("Evaluate job fit", key=f"reeval_{job_id}", type="primary"):
                with st.spinner("Evaluating job fit (real LLM call)..."):
                    try:
                        result = evaluate_job_by_id(job_id)
                    except Exception as exc:
                        st.error(f"Evaluation failed: {exc}")
                        return
                if result["meta"].get("production_eligible"):
                    st.success("Evaluation completed and passed the reliability gate.")
                    st.rerun()
                st.error(f"Evaluation did not pass the reliability gate: {result['meta']}")
            return

        st.warning("No tailored resume generated yet for this job.")
        generated = False
        if st.button(
            "Generate tailored resume + outreach draft", key=f"generate_{job_id}", type="primary"
        ):
            graph = _get_graph()
            with st.spinner(
                "Tailoring resume + drafting outreach (real LLM calls, can take up to a minute)..."
            ):
                try:
                    payload = start_review(graph, job_id)
                    generated = True
                except Exception as e:
                    st.error(f"Generation failed: {e}")
            if generated:
                st.session_state[pending_key] = payload
                st.rerun()
        return

    payload = st.session_state[pending_key]

    if payload["resume_valid"]:
        st.success("Resume passed claim validation and PDF validation.")
    else:
        st.error("Resume FAILED automated validation — cannot be finalized even if approved.")
        for v in payload["resume_claim_violations"]:
            st.write(f"- [claim] {v}")
        for v in payload["resume_pdf_violations"]:
            st.write(f"- [pdf] {v}")

    st.markdown("**Tailored resume (preview)**")
    st.text(payload["tailored_resume"])
    st.markdown("**Outreach draft (preview)**")
    st.text(payload["outreach_message"])

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Approve", key=f"approve_{job_id}", type="primary"):
            graph = _get_graph()
            try:
                with st.spinner("Finalizing..."):
                    result = resolve_review(
                        graph, job_id, payload["thread_id"], approved=True, feedback=""
                    )
            except Exception as e:
                st.error(f"Approval failed: {e}")
                return
            del st.session_state[pending_key]
            if result["blocked"]:
                st.session_state[flash_key] = (
                    "error",
                    "Approved, but the resume failed automated validation, so only the "
                    "outreach draft was saved — the resume PDF was not. Fix the underlying "
                    "data (usually the candidate profile) and regenerate.",
                )
            st.rerun()
    with col2:
        reject_feedback = st.text_input(
            "Feedback (optional, only used if rejecting)", key=f"feedback_{job_id}"
        )
        if st.button("Reject", key=f"reject_{job_id}"):
            graph = _get_graph()
            try:
                resolve_review(
                    graph, job_id, payload["thread_id"], approved=False, feedback=reject_feedback
                )
            except Exception as e:
                st.error(f"Rejection failed: {e}")
                return
            del st.session_state[pending_key]
            st.session_state[flash_key] = ("info", "Rejected — nothing saved.")
            st.rerun()


def render_job_detail(job: pd.Series):
    st.subheader(f"{job['company']} — {job['title']}")

    if job.get("url"):
        st.link_button("Open job posting to apply ↗", job["url"], type="primary")
    else:
        st.warning("No URL stored for this job.")

    cols = st.columns(4)
    score = job.get("ats_score")
    cols[0].metric("ATS Score", f"{score:.0f}" if pd.notna(score) else "—")
    cols[1].metric("Job family", (job.get("job_family") or job.get("track") or "—").replace("_", " ").title())
    cols[2].metric("Status", job.get("status") or "—")
    cols[3].metric("Source", job.get("source") or "—")

    if job.get("location"):
        st.caption(f"📍 {job['location']}")

    metadata = []
    for label, key in (
        ("Work mode", "work_mode"),
        ("Employment", "employment_type"),
        ("Experience", "experience_level"),
        ("Sponsorship", "sponsorship_status"),
    ):
        value = job.get(key)
        if value and pd.notna(value):
            metadata.append(f"**{label}:** {str(value).replace('_', ' ').title()}")
    if metadata:
        st.markdown(" · ".join(metadata))
    visa_categories = job.get("visa_categories")
    if isinstance(visa_categories, (list, tuple)) and visa_categories:
        st.caption("Authorization / visa mentions: " + ", ".join(v.replace("_", " ").upper() for v in visa_categories))
    st.caption("Work-mode and authorization fields are extracted from posting text; verify details on the employer page.")

    if job.get("eval_summary") and pd.notna(job.get("eval_summary")):
        st.info(job["eval_summary"])

    with st.expander("Job description"):
        desc = job.get("description")
        st.write(desc if desc and pd.notna(desc) else "No description available.")
    st.session_state[f"job_description_ready_{int(job['id'])}"] = bool(
        desc and pd.notna(desc) and len(str(desc).strip()) >= 80
    )

    resume_pdf_path = _find_output_file(int(job["id"]), "_resume.pdf")
    resume_md_path = _find_output_file(int(job["id"]), "_resume.md")  # pre-Phase-6 fallback
    claim_report_path = _find_output_file(int(job["id"]), "_claim_validation.json")
    outreach_path = _find_output_file(int(job["id"]), "_outreach.txt")
    show_demo_artifacts = (
        is_demo_mode()
        and job.get("company") == "Example Robotics"
        and job.get("title") == "Machine Learning Platform Engineer"
    )

    tab1, tab2 = st.tabs(["Tailored Resume", "Outreach Draft"])
    with tab1:
        if show_demo_artifacts:
            st.success("Pre-generated fictional example · evidence checked against the sample resume")
            st.markdown((EXAMPLE_DIR / "demo_tailored_resume.md").read_text())
        elif resume_pdf_path:
            pdf_bytes = resume_pdf_path.read_bytes()
            st.download_button(
                "Download resume PDF (ready to apply with)",
                data=pdf_bytes,
                file_name=_apply_ready_filename(resume_pdf_path.name),
                mime="application/pdf",
                type="primary",
                help=f"Saved for tracking as {resume_pdf_path.name} in outputs/",
            )
            if claim_report_path:
                report = json.loads(claim_report_path.read_text())
                if report.get("passed"):
                    st.success("Passed claim validation — every bullet traces to real profile data.")
                else:
                    st.error(f"Failed claim validation: {report.get('violations')}")

            # Streamlit's own st.pdf() needs a component build newer than our pinned
            # version supports (same class of dependency conflict as the Phase 4
            # streamlit/starlette issue) — preview via extracted text instead, which
            # needs no extra component and doubles as a sanity check that the PDF's
            # text is actually extractable (the same thing pdf_validate.py checks).
            with st.expander("Preview extracted text", expanded=True):
                reader = PdfReader(io.BytesIO(pdf_bytes))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                st.text(text)
        elif resume_md_path:
            st.info("This was generated before PDF support — showing the markdown version.")
            st.markdown(resume_md_path.read_text())
        else:
            _render_generate_flow(int(job["id"]))
    with tab2:
        if show_demo_artifacts:
            st.info("Pre-generated fictional outreach example")
            st.text((EXAMPLE_DIR / "demo_outreach.txt").read_text())
        elif outreach_path:
            st.text(outreach_path.read_text())
        else:
            st.warning("No outreach draft generated yet for this job.")
