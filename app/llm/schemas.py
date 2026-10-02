from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

TaskComplexity = Literal["routine", "strong"]

EvaluationSource = Literal["REAL_PRIMARY", "REAL_ESCALATED", "REAL_FALLBACK", "MOCK_TEST"]
EvaluationStatus = Literal[
    "PENDING", "RUNNING", "COMPLETED", "EVALUATION_FAILED", "VALIDATION_FAILED", "RATE_LIMITED"
]
MatchType = Literal["exact", "strong", "partial", "missing", "unclear"]

REAL_EVALUATION_SOURCES = {"REAL_PRIMARY", "REAL_ESCALATED", "REAL_FALLBACK"}


class GenerateResult(BaseModel):
    """What every provider returns, regardless of which one served the request."""

    content: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    confidence: Optional[float] = None


class RoutingAttempt(BaseModel):
    """One provider/model attempt within a routed request, for the audit trail."""

    provider: str
    model: str
    succeeded: bool
    error: Optional[str] = None
    latency_ms: float = 0.0
    retry_count: int = 0


class RoutedResult(BaseModel):
    result: GenerateResult
    evaluation_source: EvaluationSource
    fallback_used: bool
    original_provider: str
    final_provider: str
    attempts: list[RoutingAttempt] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    requirement: str
    resume_evidence: Optional[str] = None
    evidence_source: Optional[str] = None
    match_type: MatchType
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def matching_claims_must_have_sources(self):
        """Missing/unclear requirements legitimately have no resume citation.

        Positive and partial matches remain evidence-gated: allowing null there would
        turn the schema fix into a path for unsupported candidate claims.
        """
        if self.match_type in {"exact", "strong", "partial"}:
            if not self.resume_evidence or not self.evidence_source:
                raise ValueError(
                    f"{self.match_type} evidence requires resume_evidence and evidence_source"
                )
        return self


class ATSEvaluation(BaseModel):
    """Structured ATS evaluation output (Step 6 schema)."""

    overall_score: int = Field(ge=0, le=100)
    skills_score: int = Field(ge=0, le=100)
    experience_score: int = Field(ge=0, le=100)
    education_score: int = Field(ge=0, le=100)
    keyword_score: int = Field(ge=0, le=100)
    eligibility_status: str
    recommended_track: str
    matching_requirements: list[str] = Field(default_factory=list)
    partial_matches: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    preferred_skills_missing: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    resume_recommendations: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    final_recommendation: str
