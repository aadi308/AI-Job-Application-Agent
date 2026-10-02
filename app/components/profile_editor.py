from pathlib import Path
from uuid import uuid4

import streamlit as st
from pypdf import PdfReader

from app.candidate.extractor import extract_profile_from_resume
from app.candidate.models import (
    ApprovedAnswer,
    CandidateProfile,
    CertificationEntry,
    EducationEntry,
    EmploymentEntry,
    FieldWithEvidence,
    ProjectEntry,
    SkillEntry,
)
from app.candidate.store import (
    approve_profile,
    delete_answer,
    get_profile,
    list_answers,
    save_profile,
    upsert_answer,
)

RESUME_PATH = "master_resume.md"
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "resume_uploads"
MIN_EXTRACTED_TEXT_CHARS = 200
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20


def _extract_text_from_pdf(uploaded_file) -> str:
    reader = PdfReader(uploaded_file)
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(f"Resume PDFs are limited to {MAX_PDF_PAGES} pages.")
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _render_resume_source_picker(button_label: str, on_extract):
    """Shared upload-or-master-file picker used both for first-time extraction and
    re-extraction, so there's one place that owns 'where does profile data come from'."""
    tab_upload, tab_existing = st.tabs(["Upload your resume", "Use master_resume.md"])

    with tab_upload:
        uploaded = st.file_uploader("Resume PDF", type=["pdf"], key=f"{button_label}_uploader")
        if uploaded is not None and st.button(button_label, key=f"{button_label}_upload_btn", type="primary"):
            payload = uploaded.getvalue()
            if len(payload) > MAX_UPLOAD_BYTES:
                st.error("Resume PDFs are limited to 10 MB.")
                return
            try:
                text = _extract_text_from_pdf(uploaded)
            except Exception as exc:
                st.error(f"Couldn't read that PDF safely: {exc}")
                return

            if len(text.strip()) < MIN_EXTRACTED_TEXT_CHARS:
                st.error(
                    "Couldn't get usable text out of that PDF — it may be a scanned image "
                    "rather than a real text layer. Try a different file, or use "
                    "master_resume.md instead."
                )
            else:
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                saved_path = UPLOAD_DIR / f"{uuid4().hex}.pdf"
                saved_path.write_bytes(payload)
                with st.spinner("Extracting structured facts from your uploaded resume..."):
                    on_extract(text)
                st.success(f"Extracted from {uploaded.name}. Review it below before approving.")
                st.rerun()

    with tab_existing:
        st.caption(f"Extract from the resume already on file at `{RESUME_PATH}`.")
        if st.button(button_label, key=f"{button_label}_master_btn"):
            with st.spinner("Extracting structured facts from your resume..."):
                on_extract(open(RESUME_PATH).read())
            st.success("Profile extracted. Review it below before approving.")
            st.rerun()

CONTACT_LABELS = {
    "full_name": "Full name",
    "preferred_name": "Preferred name",
    "email": "Email",
    "phone": "Phone",
    "location": "Current location",
    "linkedin": "LinkedIn",
    "github": "GitHub",
    "portfolio": "Portfolio",
}

WORK_AUTH_LABELS = {
    "authorized_to_work": "Authorized to work in the US?",
    "requires_future_sponsorship": "Will you require future visa sponsorship?",
}

PREFERENCE_LABELS = {
    "preferred_roles": "Preferred roles",
    "preferred_locations": "Preferred locations",
    "work_mode": "Remote / hybrid / onsite",
    "relocation": "Willing to relocate?",
    "expected_salary": "Expected salary",
    "available_start_date": "Available start date",
}


def _status_badge(status: str) -> str:
    return {
        "verified": "🟢 verified",
        "user_approved": "🔵 user-approved",
        "job_specific": "🟣 job-specific",
        "unresolved": "⚪ unresolved",
    }.get(status, status)


def _editable_field_group(section_title: str, fields: dict, labels: dict, help_text: str = "") -> dict:
    st.markdown(f"**{section_title}**")
    if help_text:
        st.caption(help_text)
    updated = {}
    for key, label in labels.items():
        current: FieldWithEvidence = fields[key]
        col1, col2 = st.columns([3, 1])
        with col1:
            new_value = st.text_input(
                label,
                value=current.value or "",
                key=f"{section_title}_{key}",
            )
        with col2:
            st.caption(_status_badge(current.status))
            if current.source:
                st.caption(f"source: {current.source}")
        if new_value != (current.value or ""):
            status = "user_approved" if new_value else "unresolved"
            source = current.source or "user_input"
            updated[key] = FieldWithEvidence(value=new_value or None, source=source if new_value else None, status=status)
        else:
            updated[key] = current
    return updated


def _reextract_preserving_manual_fields(old_profile: CandidateProfile, resume_text: str) -> None:
    """Re-extraction used to silently wipe anything the resume file doesn't state but the
    user typed in by hand (work authorization, preferences, a LinkedIn URL the resume text
    only lists as a bare word) — this happened for real and cost a manually-restored
    LinkedIn/GitHub URL. Work authorization and preferences are never LLM-populated at all,
    so always carry the old values forward; for contact fields, keep the user's own
    manually-approved value if the fresh extraction didn't find one."""
    new_profile = extract_profile_from_resume(resume_text)
    new_profile.work_authorization = old_profile.work_authorization
    new_profile.preferences = old_profile.preferences
    for field_name in new_profile.contact.model_fields:
        new_field = getattr(new_profile.contact, field_name)
        old_field = getattr(old_profile.contact, field_name)
        if not new_field.value and old_field.status == "user_approved" and old_field.value:
            setattr(new_profile.contact, field_name, old_field)
    save_profile(new_profile)


def render_profile_editor():
    st.header("Candidate Profile")
    st.info(
        "Private local data: this profile is loaded from your persistent PostgreSQL volume. "
        "It is not read from Git and is hidden completely when `APP_MODE=demo`."
    )

    profile = get_profile()

    if profile is None:
        st.info(
            "No candidate profile yet. Upload your resume (or use the one already on file) "
            "and we'll extract it — you'll review and approve everything before it's usable. "
            "Prefer to skip extraction entirely? Use \"Start from scratch\" below."
        )
        _render_resume_source_picker(
            "Extract profile",
            lambda text: save_profile(extract_profile_from_resume(text)),
        )
        st.divider()
        if st.button("Start from scratch (no resume, manual entry only)"):
            save_profile(CandidateProfile())
            st.rerun()
        return

    if profile.approved:
        st.success(f"Profile approved at {profile.approved_at}")
    else:
        st.warning("Profile not yet approved — review everything below, then approve it.")

    with st.expander("Re-extract from a resume (overwrites current profile)"):
        st.caption(
            "⚠️ This replaces contact/employment/education/projects/skills/certifications "
            "with a fresh extraction. Work authorization and preferences you've entered "
            "manually are kept."
        )
        _render_resume_source_picker(
            "Re-extract",
            lambda text: _reextract_preserving_manual_fields(profile, text),
        )

    st.divider()
    contact_fields = {k: getattr(profile.contact, k) for k in CONTACT_LABELS}
    new_contact = _editable_field_group("Contact", contact_fields, CONTACT_LABELS)

    st.divider()
    st.markdown("**Work Authorization**")
    st.caption(
        "Never inferred or guessed — these start unresolved and can only be filled in by you here."
    )
    wa_fields = {k: getattr(profile.work_authorization, k) for k in WORK_AUTH_LABELS}
    new_wa = _editable_field_group("Work Authorization", wa_fields, WORK_AUTH_LABELS)

    st.divider()
    st.markdown("**Preferences**")
    st.caption("Not derivable from a resume — fill these in directly.")
    pref_fields = {k: getattr(profile.preferences, k) for k in PREFERENCE_LABELS}
    new_prefs = _editable_field_group("Preferences", pref_fields, PREFERENCE_LABELS)

    if st.button("Save changes"):
        from app.candidate.models import ContactInfo, Preferences, WorkAuthorization

        profile.contact = ContactInfo(**new_contact)
        profile.work_authorization = WorkAuthorization(**new_wa)
        profile.preferences = Preferences(**new_prefs)
        save_profile(profile)
        st.success("Saved.")
        st.rerun()

    st.divider()

    with st.expander(f"Education ({len(profile.education)})"):
        for i, e in enumerate(profile.education):
            col1, col2 = st.columns([5, 1])
            col1.markdown(f"**{e.degree}** — {e.institution} ({e.dates})")
            col1.caption(f"source: {e.source} · {_status_badge(e.status)}")
            if col2.button("🗑", key=f"del_edu_{i}"):
                profile.education.pop(i)
                save_profile(profile)
                st.rerun()
        with st.form("add_education", clear_on_submit=True):
            st.markdown("**Add education entry**")
            institution = st.text_input("Institution")
            degree = st.text_input("Degree")
            dates = st.text_input("Dates (e.g. Aug 2018 – Jun 2022)")
            if st.form_submit_button("Add") and institution and degree:
                profile.education.append(
                    EducationEntry(
                        institution=institution, degree=degree, dates=dates,
                        source="user_input", status="user_approved",
                    )
                )
                save_profile(profile)
                st.rerun()

    with st.expander(f"Employment ({len(profile.employment)})"):
        for i, job in enumerate(profile.employment):
            col1, col2 = st.columns([5, 1])
            with col1:
                st.markdown(f"**{job.title}** — {job.company} ({job.dates})")
                for b in job.bullets:
                    st.markdown(f"- {b}")
                st.caption(f"source: {job.source} · {_status_badge(job.status)}")
            if col2.button("🗑", key=f"del_emp_{i}"):
                profile.employment.pop(i)
                save_profile(profile)
                st.rerun()
        with st.form("add_employment", clear_on_submit=True):
            st.markdown("**Add employment entry**")
            company = st.text_input("Company")
            title = st.text_input("Title")
            dates = st.text_input("Dates")
            bullets_text = st.text_area("Bullet points (one per line)")
            if st.form_submit_button("Add") and company and title:
                profile.employment.append(
                    EmploymentEntry(
                        company=company, title=title, dates=dates,
                        bullets=[b.strip() for b in bullets_text.splitlines() if b.strip()],
                        source="user_input", status="user_approved",
                    )
                )
                save_profile(profile)
                st.rerun()

    with st.expander(f"Projects ({len(profile.projects)})"):
        for i, p in enumerate(profile.projects):
            col1, col2 = st.columns([5, 1])
            with col1:
                st.markdown(f"**{p.name}** — {', '.join(p.tech_stack)}")
                st.write(p.description)
                st.caption(f"source: {p.source} · {_status_badge(p.status)}")
            if col2.button("🗑", key=f"del_proj_{i}"):
                profile.projects.pop(i)
                save_profile(profile)
                st.rerun()
        with st.form("add_project", clear_on_submit=True):
            st.markdown("**Add project**")
            name = st.text_input("Project name")
            description = st.text_area("Description")
            tech = st.text_input("Tech stack (comma-separated)")
            if st.form_submit_button("Add") and name and description:
                profile.projects.append(
                    ProjectEntry(
                        name=name, description=description,
                        tech_stack=[t.strip() for t in tech.split(",") if t.strip()],
                        source="user_input", status="user_approved",
                    )
                )
                save_profile(profile)
                st.rerun()

    with st.expander(f"Skills ({len(profile.skills)})"):
        st.write(", ".join(s.skill for s in profile.skills))
        with st.form("add_skill", clear_on_submit=True):
            new_skill = st.text_input("Add a skill")
            if st.form_submit_button("Add") and new_skill:
                profile.skills.append(
                    SkillEntry(skill=new_skill, source="user_input", status="user_approved")
                )
                save_profile(profile)
                st.rerun()

    with st.expander(f"Certifications ({len(profile.certifications)})"):
        for i, c in enumerate(profile.certifications):
            col1, col2 = st.columns([5, 1])
            col1.markdown(f"- {c.name}" + (f" — {c.issuer}" if c.issuer else ""))
            if col2.button("🗑", key=f"del_cert_{i}"):
                profile.certifications.pop(i)
                save_profile(profile)
                st.rerun()
        with st.form("add_cert", clear_on_submit=True):
            st.markdown("**Add certification**")
            cert_name = st.text_input("Certification name")
            cert_issuer = st.text_input("Issuer (optional)")
            if st.form_submit_button("Add") and cert_name:
                profile.certifications.append(
                    CertificationEntry(
                        name=cert_name, issuer=cert_issuer or None,
                        source="user_input", status="user_approved",
                    )
                )
                save_profile(profile)
                st.rerun()

    st.divider()
    unresolved_wa = [k for k, v in new_wa.items() if v.status == "unresolved"]
    unresolved_prefs = [k for k, v in new_prefs.items() if v.status == "unresolved"]
    if unresolved_wa or unresolved_prefs:
        st.info(
            f"{len(unresolved_wa)} work-authorization field(s) and {len(unresolved_prefs)} "
            "preference field(s) still unresolved. You can approve anyway and fill these in "
            "later — but they'll need to be resolved before Phase 7/8 can use them."
        )

    if not profile.approved:
        if st.button("Approve profile", type="primary"):
            approve_profile()
            st.success("Profile approved.")
            st.rerun()

    st.divider()
    st.subheader("Approved Answer Bank")
    st.caption("Reusable answers to recurring application questions.")

    answers = list_answers()
    if answers:
        for a in answers:
            col1, col2, col3 = st.columns([3, 4, 1])
            col1.write(f"**{a.question_label}**")
            col2.write(a.answer)
            if col3.button("🗑", key=f"del_{a.question_key}"):
                delete_answer(a.question_key)
                st.rerun()
    else:
        st.caption("No saved answers yet.")

    with st.form("add_answer"):
        st.markdown("**Add an answer**")
        q_key = st.text_input("Key (e.g. `willing_to_relocate`)")
        q_label = st.text_input("Question (e.g. `Are you willing to relocate?`)")
        a_val = st.text_input("Answer")
        submitted = st.form_submit_button("Save answer")
        if submitted and q_key and q_label and a_val:
            upsert_answer(
                ApprovedAnswer(
                    question_key=q_key,
                    question_label=q_label,
                    answer=a_val,
                    source="user_input",
                    status="user_approved",
                )
            )
            st.rerun()
