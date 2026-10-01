from typing import Optional

from pydantic import BaseModel, Field


class ResumeBullet(BaseModel):
    text: str
    # Verbatim (or near-verbatim) copy of the real profile bullet this was derived from.
    # Claim validation checks this actually exists in the candidate profile.
    source_bullet: str


class ResumeExperienceEntry(BaseModel):
    company: str
    title: str
    dates: str
    bullets: list[ResumeBullet] = Field(default_factory=list)


class ResumeProjectEntry(BaseModel):
    name: str
    description: str
    tech_stack: list[str] = Field(default_factory=list)


class ResumeEducationEntry(BaseModel):
    institution: str
    degree: str
    dates: str


class ResumeCertification(BaseModel):
    name: str
    issuer: Optional[str] = None


class ResumeHeader(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None


class StructuredResume(BaseModel):
    header: ResumeHeader
    summary: str
    skills: list[str] = Field(default_factory=list)
    experience: list[ResumeExperienceEntry] = Field(default_factory=list)
    projects: list[ResumeProjectEntry] = Field(default_factory=list)
    education: list[ResumeEducationEntry] = Field(default_factory=list)
    certifications: list[ResumeCertification] = Field(default_factory=list)


class ClaimValidationReport(BaseModel):
    passed: bool
    violations: list[str] = Field(default_factory=list)


class PDFValidationReport(BaseModel):
    passed: bool
    page_count: int
    violations: list[str] = Field(default_factory=list)
    extracted_text_length: int = 0
