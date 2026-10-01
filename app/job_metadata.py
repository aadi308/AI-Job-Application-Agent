"""Deterministic, explainable metadata extraction for job discovery filters.

ATS providers do not expose these fields consistently.  We therefore classify only
explicit wording from the title, location, and description and use ``unknown`` /
``not_specified`` when the posting does not say enough.
"""

import re
from typing import Iterable


JOB_FAMILY_PATTERNS = {
    "ai_ml": r"\b(machine learning|mlops|artificial intelligence|ai engineer|data scientist|nlp|computer vision)\b",
    "data": r"\b(data engineer|analytics engineer|database|business intelligence|\bbi\b)\b",
    "devops_cloud": r"\b(devops|site reliability|\bsre\b|cloud engineer|platform engineer|infrastructure engineer)\b",
    "software": r"\b(software|backend|front.?end|full.?stack|mobile|ios|android|developer)\b",
    "security": r"\b(security|cyber|infosec|application security)\b",
    "qa_testing": r"\b(quality assurance|\bqa\b|test engineer|sdet)\b",
    "product": r"\b(product manager|product owner|program manager|project manager)\b",
    "design": r"\b(designer|\bux\b|\bui\b|user experience|user research)\b",
    "sales_marketing": r"\b(sales|account executive|marketing|growth|business development)\b",
    "hr_recruiting": r"\b(recruit|talent|human resources|people operations)\b",
    "finance": r"\b(finance|financial|accounting|accountant|controller)\b",
    "healthcare": r"\b(clinical|healthcare|medical|nurse|physician)\b",
}

VISA_PATTERNS = {
    "h1b": r"\b(h-?1b|h1-b)\b",
    "f1_opt": r"\b(f-?1|optional practical training|\bopt\b)\b",
    "stem_opt": r"\b(stem[ -]?opt|stem extension)\b",
    "us_citizen": r"\b(u\.?s\.? citizen(ship)?|united states citizen(ship)?)\b",
    "green_card": r"\b(green card|permanent resident)\b",
    "ead": r"\b(employment authorization document|\bead\b)\b",
}


def _text(*values: str | None) -> str:
    return " ".join(value or "" for value in values).lower()


def classify_job_family(title: str) -> str:
    value = title.lower()
    for family, pattern in JOB_FAMILY_PATTERNS.items():
        if re.search(pattern, value, re.IGNORECASE):
            return family
    return "other"


def classify_employment_type(title: str, description: str | None) -> str:
    value = _text(title, description)
    checks = (
        ("internship", r"\b(intern(ship)?|co-?op)\b"),
        ("contract", r"\b(contract(or)?|1099|c2c|corp[- ]to[- ]corp)\b"),
        ("part_time", r"\bpart[- ]time\b"),
        ("temporary", r"\btemporary|seasonal\b"),
        ("full_time", r"\bfull[- ]time\b"),
    )
    return next((label for label, pattern in checks if re.search(pattern, value)), "unknown")


def classify_work_mode(title: str, location: str | None, description: str | None) -> str:
    # Hybrid is checked first because postings often contain both "hybrid" and "remote".
    value = _text(title, location, description)
    if re.search(r"\bhybrid\b", value):
        return "hybrid"
    if re.search(r"\b(remote|work from home|distributed)\b", value):
        return "remote"
    if re.search(r"\b(on[- ]?site|in[- ]office|office[- ]based)\b", value):
        return "onsite"
    return "unknown"


def classify_experience_level(title: str, description: str | None) -> str:
    title_value = title.lower()
    value = _text(title, description)
    checks = (
        ("internship", r"\b(intern(ship)?|co-?op)\b"),
        ("executive", r"\b(chief|vice president|\bvp\b|head of)\b"),
        ("lead", r"\b(principal|staff|lead|architect|manager|director)\b"),
        ("senior", r"\b(senior|\bsr\.?\b)\b"),
        ("entry", r"\b(junior|\bjr\.?\b|entry[- ]level|new grad|graduate)\b"),
    )
    for label, pattern in checks:
        if re.search(pattern, title_value):
            return label
    years = [int(n) for n in re.findall(r"\b(\d{1,2})\+?\s*(?:years?|yrs?)\b", value)]
    if years:
        minimum = min(years)
        if minimum <= 2:
            return "entry"
        if minimum >= 8:
            return "lead"
        if minimum >= 5:
            return "senior"
        return "mid"
    return "unknown"


def classify_sponsorship(description: str | None) -> str:
    value = _text(description)
    if not value:
        return "not_specified"
    unavailable = (
        r"(?:will not|cannot|can't|unable to|do not|does not|not able to)\s+(?:provide\s+)?(?:visa\s+)?sponsor",
        r"\bno\s+(?:visa\s+)?sponsorship\b",
        r"without\s+(?:current or future\s+)?(?:visa\s+)?sponsorship",
        r"sponsorship\s+(?:is\s+)?not\s+available",
    )
    if any(re.search(pattern, value) for pattern in unavailable):
        return "not_available"
    available = (
        r"\b(?:visa\s+)?sponsorship\s+(?:is\s+)?available\b",
        r"\b(?:we|company|employer)\s+(?:will\s+)?sponsor\b",
        r"\bsponsorship\s+(?:will be\s+)?provided\b",
    )
    if any(re.search(pattern, value) for pattern in available):
        return "available"
    if re.search(r"\b(sponsor(ship)?|work authorization|work authorisation|visa)\b", value):
        return "mentioned_review_required"
    return "not_specified"


def extract_visa_categories(description: str | None) -> list[str]:
    value = _text(description)
    return [name for name, pattern in VISA_PATTERNS.items() if re.search(pattern, value)]


def enrich_job(job: dict) -> dict:
    """Return a copy with normalized filter metadata derived from explicit posting text."""
    enriched = dict(job)
    title = enriched.get("title") or ""
    location = enriched.get("location")
    description = enriched.get("description")
    enriched.update(
        job_family=classify_job_family(title),
        employment_type=classify_employment_type(title, description),
        work_mode=classify_work_mode(title, location, description),
        experience_level=classify_experience_level(title, description),
        sponsorship_status=classify_sponsorship(description),
        visa_categories=extract_visa_categories(description),
    )
    return enriched


def labels(values: Iterable[str]) -> list[str]:
    """Human-readable labels for enum-like metadata values."""
    return [value.replace("_", " ").title() for value in values]
