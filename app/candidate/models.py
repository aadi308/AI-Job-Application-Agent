from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Status = Literal["verified", "user_approved", "job_specific", "unresolved"]


class FieldWithEvidence(BaseModel):
    """A single claim: its value, where it came from, and how much to trust it.

    status="unresolved" fields have value=None and source=None by construction —
    nothing populates a value without also providing a source, except fields the
    extractor is never even asked about (work authorization, salary, etc.).
    """

    value: Optional[str] = None
    source: Optional[str] = None
    status: Status = "unresolved"


class ContactInfo(BaseModel):
    full_name: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    preferred_name: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    email: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    phone: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    location: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    linkedin: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    github: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    portfolio: FieldWithEvidence = Field(default_factory=FieldWithEvidence)


class EducationEntry(BaseModel):
    institution: str
    degree: str
    dates: str
    source: str
    status: Status = "verified"


class EmploymentEntry(BaseModel):
    company: str
    title: str
    dates: str
    bullets: list[str] = Field(default_factory=list)
    source: str
    status: Status = "verified"


class ProjectEntry(BaseModel):
    name: str
    description: str
    tech_stack: list[str] = Field(default_factory=list)
    source: str
    status: Status = "verified"


class SkillEntry(BaseModel):
    skill: str
    source: str
    status: Status = "verified"


class CertificationEntry(BaseModel):
    name: str
    issuer: Optional[str] = None
    source: str
    status: Status = "verified"


class WorkAuthorization(BaseModel):
    """Never populated by the extractor — always starts unresolved.

    Only the candidate, editing this in Streamlit, may set these values.
    """

    authorized_to_work: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    requires_future_sponsorship: FieldWithEvidence = Field(default_factory=FieldWithEvidence)


class Preferences(BaseModel):
    """Never populated by the extractor — the resume doesn't state any of these."""

    preferred_roles: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    preferred_locations: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    work_mode: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    relocation: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    expected_salary: FieldWithEvidence = Field(default_factory=FieldWithEvidence)
    available_start_date: FieldWithEvidence = Field(default_factory=FieldWithEvidence)


class CandidateProfile(BaseModel):
    contact: ContactInfo = Field(default_factory=ContactInfo)
    education: list[EducationEntry] = Field(default_factory=list)
    employment: list[EmploymentEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    skills: list[SkillEntry] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    preferences: Preferences = Field(default_factory=Preferences)
    approved: bool = False
    approved_at: Optional[datetime] = None


class ApprovedAnswer(BaseModel):
    question_key: str
    question_label: str
    answer: str
    source: str
    status: Status = "user_approved"
