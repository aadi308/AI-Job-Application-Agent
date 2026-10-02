import json

from app.candidate.models import CandidateProfile


def profile_to_evidence_text(profile: CandidateProfile) -> str:
    """Return evidence belonging only to the authenticated profile."""
    return json.dumps(profile.model_dump(mode="json"), indent=2, ensure_ascii=False)
