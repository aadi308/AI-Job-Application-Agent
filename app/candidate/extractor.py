import json
from datetime import datetime, timezone

from app.candidate.models import (
    CandidateProfile,
    CertificationEntry,
    EducationEntry,
    EmploymentEntry,
    FieldWithEvidence,
    ProjectEntry,
    SkillEntry,
)
from app.llm.audit import record_evaluation
from app.llm.config import get_router
from app.llm.exceptions import AllProvidersFailedError

AGENT_NAME = "candidate_extractor"
PROMPT_VERSION = "v2-groq"

# Deliberately scoped to only what a resume can actually contain. Work authorization,
# salary expectations, location/remote preference, and start date are NEVER asked for
# here — they're not derivable from a resume, and guessing them would violate the
# "never infer sensitive/eligibility answers" requirement. Those fields are populated
# only by the candidate, directly, in the Streamlit editor.
SYSTEM_PROMPT = """You extract structured facts from a candidate's resume. Extract ONLY \
information explicitly present in the resume text — never infer, estimate, or add anything \
that isn't directly stated.

For every item you extract, include a "source" string identifying where in the resume it came \
from (e.g. "header", "professional_experience.ml_engineer_example_labs", \
"education.ms_cs_lsus", "core_technical_skills").

If a contact field (preferred_name, github, portfolio, etc.) is not present in the resume, set \
its value to null rather than guessing.

Respond with a JSON object with exactly this shape:
{
  "contact": {
    "full_name": {"value": "...", "source": "..."},
    "preferred_name": {"value": null, "source": null},
    "email": {"value": "...", "source": "..."},
    "phone": {"value": "...", "source": "..."},
    "location": {"value": "...", "source": "..."},
    "linkedin": {"value": "...", "source": "..."},
    "github": {"value": "...", "source": "..."},
    "portfolio": {"value": "...", "source": "..."}
  },
  "education": [{"institution": "...", "degree": "...", "dates": "...", "source": "..."}],
  "employment": [{"company": "...", "title": "...", "dates": "...", "bullets": ["..."], "source": "..."}],
  "projects": [{"name": "...", "description": "...", "tech_stack": ["..."], "source": "..."}],
  "skills": [{"skill": "...", "source": "..."}],
  "certifications": [{"name": "...", "issuer": "...", "source": "..."}]
}
"""


def _wrap_contact_field(data: dict | None) -> FieldWithEvidence:
    if not data or not data.get("value"):
        return FieldWithEvidence()
    return FieldWithEvidence(value=data["value"], source=data.get("source"), status="verified")


def extract_profile_from_resume(
    resume_text: str, owner_id: str | None = None
) -> CandidateProfile:
    router = get_router()
    started_at = datetime.now(timezone.utc)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Resume:\n\n{resume_text}"},
    ]

    try:
        routed = router.generate(
            messages=messages,
            complexity="routine",  # structured extraction, no evaluative judgment required
            # NOT the spec's blanket routine default of 1500 — verified against a real
            # resume that 1500 silently truncates mid-JSON (JSON mode is grammar-constrained
            # to close brackets validly even when cut off, so the truncation doesn't raise,
            # it just quietly drops most of the resume). The MODEL tier is routine-appropriate
            # for this task; the OUTPUT size (a whole resume) needs a bigger budget regardless.
            max_completion_tokens=4000,
            temperature=0.1,
            response_schema={},
        )
    except AllProvidersFailedError as e:
        record_evaluation(
            agent_name=AGENT_NAME, evaluation_status="EVALUATION_FAILED", started_at=started_at,
            safe_error_message=str(e)[:300], prompt_version=PROMPT_VERSION,
            owner_id=owner_id,
        )
        raise

    data = json.loads(routed.result.content)
    record_evaluation(
        agent_name=AGENT_NAME, evaluation_status="COMPLETED", started_at=started_at,
        routed=routed, prompt_version=PROMPT_VERSION,
        owner_id=owner_id,
    )

    contact_data = data.get("contact", {})
    return CandidateProfile(
        contact={
            field: _wrap_contact_field(contact_data.get(field))
            for field in [
                "full_name",
                "preferred_name",
                "email",
                "phone",
                "location",
                "linkedin",
                "github",
                "portfolio",
            ]
        },
        education=[EducationEntry(**e) for e in data.get("education", [])],
        employment=[EmploymentEntry(**e) for e in data.get("employment", [])],
        projects=[ProjectEntry(**p) for p in data.get("projects", [])],
        skills=[SkillEntry(**s) for s in data.get("skills", [])],
        certifications=[CertificationEntry(**c) for c in data.get("certifications", [])],
        # work_authorization and preferences are intentionally left at their default
        # (unresolved) construction — the extractor was never given a schema slot for
        # them, so there is no code path by which the LLM's output can populate them.
    )
