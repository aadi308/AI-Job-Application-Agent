import json
from datetime import datetime, timezone

from app.candidate.models import CandidateProfile
from app.llm.audit import record_evaluation
from app.llm.config import get_router
from app.llm.exceptions import AllProvidersFailedError
from app.resume.models import (
    ResumeBullet,
    ResumeCertification,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeHeader,
    ResumeProjectEntry,
    StructuredResume,
)

AGENT_NAME = "resume_tailor"
PROMPT_VERSION = "v3-evidence-selection"

# The LLM never writes company/title/dates/institution/degree/skill-name/contact text
# itself — it only picks INDICES into the real profile. This eliminates the class of "LLM
# retyped a proper noun slightly differently" bugs by construction: those fields are
# always filled in from the profile in Python, never from LLM free text.
SYSTEM_PROMPT = """You select and lightly rephrase content from a candidate's verified \
profile to build a resume tailored to a specific job. The profile below has NUMBERED \
employer entries, education entries, and certifications, and each employer's bullets are \
also numbered. You respond with INDICES into these lists, not free text for factual fields.

STRICT RULES:
- "employer_indices": which employer entries to include, in the order they should appear \
(usually all of them, most relevant first).
- For each included employer, "bullet_indices": which of THAT employer's numbered bullets to \
include (select the 3-6 most relevant to the target job). Do not rewrite factual content.
- "certification_indices": which numbered certifications to include (usually all).
- "project_indices": which numbered projects are relevant enough to include. Include a \
project if it demonstrates skills relevant to THIS job — for an MLOps/AI/ML-adjacent role, \
ML projects are usually highly relevant even if the candidate's main experience is DevOps; \
for a pure infrastructure/DevOps role, include projects that show relevant engineering \
practice. When in doubt, include it — omitting a real, relevant project is worse than a \
slightly longer resume.
- "skill_indices": the 10-15 MOST relevant numbered skills for this job (do not invent new \
skill names or merge several into a new category label — only pick from the numbered list; do \
not just return every skill).
- Do not write a summary. The application creates one deterministically from verified fields.

CRITICAL FORMAT REQUIREMENT for every "*_indices" field: it must be a JSON array where each \
index is its own separate integer array element — for example [0, 3, 7, 12, 15], never a \
single combined number or string like "0371215". Double-check this before responding.

Respond with a JSON object matching this shape:
{
  "skill_indices": [0, 2, 5],
  "employer_selections": [
    {"employer_index": 0, "bullet_indices": [1, 2]}
  ],
  "project_indices": [0, 1],
  "certification_indices": [0]
}
"""


def _profile_context(profile: CandidateProfile) -> str:
    lines = []

    lines.append("Skills (numbered):")
    for i, s in enumerate(profile.skills):
        lines.append(f"  [{i}] {s.skill}")

    lines.append("\nEmployment (numbered, with numbered bullets):")
    for i, job in enumerate(profile.employment):
        lines.append(f"[{i}] {job.title} at {job.company} ({job.dates})")
        for j, b in enumerate(job.bullets):
            lines.append(f"    [{j}] {b}")

    if profile.projects:
        lines.append("\nProjects (numbered):")
        for i, p in enumerate(profile.projects):
            tech = f" [{', '.join(p.tech_stack)}]" if p.tech_stack else ""
            lines.append(f"  [{i}] {p.name}{tech}: {p.description}")

    lines.append("\nEducation (numbered):")
    for i, e in enumerate(profile.education):
        lines.append(f"  [{i}] {e.degree}, {e.institution} ({e.dates})")

    if profile.certifications:
        lines.append("\nCertifications (numbered):")
        for i, cert in enumerate(profile.certifications):
            lines.append(f"  [{i}] {cert.name}" + (f" ({cert.issuer})" if cert.issuer else ""))

    return "\n".join(lines)


def tailor_resume(
    profile: CandidateProfile, company: str, title: str, description: str | None
) -> StructuredResume:
    router = get_router()
    started_at = datetime.now(timezone.utc)
    user_prompt = f"""Candidate profile (only source of truth, numbered for selection):
{_profile_context(profile)}

Target job:
Company: {company}
Title: {title}
Description: {description or 'not available'}

Produce your index-based selection now.
"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        routed = router.generate(
            messages=messages,
            complexity="strong",  # resume tailoring begins directly at the strong model
            max_completion_tokens=4000,
            temperature=0.1,
            response_schema={},
        )
    except AllProvidersFailedError as e:
        record_evaluation(
            agent_name=AGENT_NAME, evaluation_status="EVALUATION_FAILED", started_at=started_at,
            safe_error_message=str(e)[:300], prompt_version=PROMPT_VERSION,
        )
        raise

    selection = json.loads(routed.result.content)
    record_evaluation(
        agent_name=AGENT_NAME, evaluation_status="COMPLETED", started_at=started_at,
        routed=routed, prompt_version=PROMPT_VERSION,
    )
    return _build_resume(selection, profile, company=company, title=title)


def _build_resume(
    selection: dict,
    profile: CandidateProfile,
    company: str = "",
    title: str = "",
) -> StructuredResume:
    """Constructs the StructuredResume entirely from real profile data, using the LLM's
    selection only to decide which real items to include and how to phrase bullets."""
    c = profile.contact
    header = ResumeHeader(
        full_name=c.full_name.value or "",
        email=c.email.value or "",
        phone=c.phone.value,
        location=c.location.value,
        linkedin=c.linkedin.value,
        github=c.github.value,
        portfolio=c.portfolio.value,
    )

    def _in_range(raw, length: int) -> int | None:
        # JSON mode only guarantees syntactically valid JSON, not that a given field is
        # the type the prompt asked for — observed for real: Groq returning "0" (string)
        # where an int index was expected. Coerce defensively; drop anything that isn't
        # cleanly an in-range integer rather than letting it crash the whole resume.
        try:
            i = int(raw)
        except (TypeError, ValueError):
            return None
        return i if 0 <= i < length else None

    raw_skill_indices = selection.get("skill_indices", [])
    if not isinstance(raw_skill_indices, list):
        raw_skill_indices = []
    skills = []
    for raw in raw_skill_indices:
        i = _in_range(raw, len(profile.skills))
        if i is not None:
            skills.append(profile.skills[i].skill)
    if raw_skill_indices and not skills:
        # The model clearly intended to select skills (skill_indices was non-empty) but
        # every element failed to parse as a valid index — observed for real: Groq
        # sometimes concatenates a run of indices into one malformed string like
        # "03471011121417181923" instead of a proper array. Guessing how to split an
        # ambiguous digit run back into indices risks picking the WRONG skills, which
        # is worse than picking too many. Since every profile skill is real regardless
        # of curation, failing open to the full real list is strictly safer than an
        # empty skills section — no fabrication risk either way, just a curation
        # quality tradeoff, and "unfiltered but true" beats "empty."
        skills = [s.skill for s in profile.skills]

    experience = []
    raw_employer_selections = selection.get("employer_selections", [])
    if not isinstance(raw_employer_selections, list):
        raw_employer_selections = []
    for entry in raw_employer_selections:
        if not isinstance(entry, dict):
            continue
        idx = _in_range(entry.get("employer_index"), len(profile.employment))
        if idx is None:
            continue
        job = profile.employment[idx]
        bullets = []
        raw_bullets = entry.get("bullet_indices")
        if raw_bullets is None:
            # Backward compatible with v2 responses and saved test fixtures.
            raw_bullets = [
                b.get("bullet_index")
                for b in entry.get("bullets", [])
                if isinstance(b, dict)
            ]
        if not isinstance(raw_bullets, list):
            raw_bullets = []
        for raw_bullet in raw_bullets:
            bi = _in_range(raw_bullet, len(job.bullets))
            if bi is None:
                continue
            real_bullet = job.bullets[bi]
            bullets.append(ResumeBullet(text=real_bullet, source_bullet=real_bullet))
        experience.append(
            ResumeExperienceEntry(company=job.company, title=job.title, dates=job.dates, bullets=bullets)
        )

    raw_project_indices = selection.get("project_indices", [])
    if not isinstance(raw_project_indices, list):
        raw_project_indices = []
    projects = []
    for raw in raw_project_indices:
        i = _in_range(raw, len(profile.projects))
        if i is not None:
            p = profile.projects[i]
            projects.append(
                ResumeProjectEntry(name=p.name, description=p.description, tech_stack=p.tech_stack)
            )
    if raw_project_indices and not projects and profile.projects:
        # Same "fail open to the full real list" safety net as skills/certifications —
        # these projects are often the strongest evidence for the MLOps/AI track
        # specifically, so silently losing them to a selection glitch is high-cost.
        projects = [
            ResumeProjectEntry(name=p.name, description=p.description, tech_stack=p.tech_stack)
            for p in profile.projects
        ]

    # Unlike bullets/skills, there's no legitimate reason to ever drop a real degree from
    # a resume — found via real testing that leaving this to LLM selection (like skills)
    # silently dropped the in-progress M.S. entry on repeated real runs, even though the
    # prompt said "usually all". Education is now never LLM-selected: always every real
    # entry, same as company/title/dates already were.
    education = [
        ResumeEducationEntry(institution=e.institution, degree=e.degree, dates=e.dates)
        for e in profile.education
    ]

    raw_cert_indices = selection.get("certification_indices", [])
    if not isinstance(raw_cert_indices, list):
        raw_cert_indices = []
    certifications = []
    for raw in raw_cert_indices:
        i = _in_range(raw, len(profile.certifications))
        if i is not None:
            cert = profile.certifications[i]
            certifications.append(ResumeCertification(name=cert.name, issuer=cert.issuer))
    if raw_cert_indices and not certifications and profile.certifications:
        # Same "fail open to the full real list" safety net as skills above — an empty
        # section despite real certifications existing is worse than an unfiltered one.
        certifications = [
            ResumeCertification(name=c.name, issuer=c.issuer) for c in profile.certifications
        ]

    # Only approved profile values plus the target role are used in the summary.
    summary_parts = []
    if experience:
        role_names = ", ".join(dict.fromkeys(e.title for e in experience[:3]))
        summary_parts.append(f"Experience includes {role_names} roles.")
    if skills:
        summary_parts.append(f"Relevant skills include {', '.join(skills[:8])}.")
    if title:
        target = f"the {title} role" + (f" at {company}" if company else "")
        summary_parts.append(f"Selected experience and skills are tailored for {target}.")
    summary = " ".join(summary_parts) or "Content selected from the approved candidate profile."

    return StructuredResume(
        header=header,
        summary=summary,
        skills=skills,
        experience=experience,
        projects=projects,
        education=education,
        certifications=certifications,
    )
