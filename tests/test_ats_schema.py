import pytest
from pydantic import ValidationError

from app.llm.schemas import EvidenceItem


def test_missing_requirement_accepts_null_resume_evidence():
    item = EvidenceItem(
        requirement="Five years of production model monitoring",
        resume_evidence=None,
        evidence_source=None,
        match_type="missing",
        confidence=0.95,
    )

    assert item.resume_evidence is None
    assert item.evidence_source is None


def test_unclear_requirement_accepts_omitted_resume_evidence():
    item = EvidenceItem(
        requirement="Experience at global scale",
        match_type="unclear",
        confidence=0.5,
    )

    assert item.resume_evidence is None
    assert item.evidence_source is None


@pytest.mark.parametrize("match_type", ["exact", "strong", "partial"])
def test_positive_match_still_requires_specific_evidence(match_type):
    with pytest.raises(ValidationError, match="requires resume_evidence and evidence_source"):
        EvidenceItem(
            requirement="Kubernetes",
            resume_evidence=None,
            evidence_source=None,
            match_type=match_type,
            confidence=0.9,
        )
