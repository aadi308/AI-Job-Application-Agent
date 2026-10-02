"""Deterministic, explainable filters for the public AI-job feed."""

import re


ROLE_PATTERNS = (
    r"\bmachine learning\b",
    r"\bml\s*(?:ops|engineer|platform|infrastructure|systems?)\b",
    r"\bartificial intelligence\b",
    r"\bai\s+(?:engineer|platform|infrastructure|research|systems?|safety)\b",
    r"\bdeep learning\b",
    r"\b(?:research|applied) scientist\b",
    r"\b(?:staff\+?\s+)?research engineer\b",
    r"\breinforcement learning\b",
    r"\binterpretability\b",
    r"\balignment\b",
    r"\bdata scientist\b",
)
EXCLUDED_TITLE_PATTERNS = (
    r"\b(?:sales|account executive|recruit(?:er|ing)|marketing|legal|counsel)\b",
    r"\bpeople research\b",
    r"\b(?:economist|economic research|demand planning)\b",
)
US_COUNTRY_PATTERNS = (
    r"\b(?:united states|u\.s\.|usa)\b",
    r"\bremote(?:\s*[-–—,]\s*)?(?:us|usa|united states)\b",
)
US_STATE_ABBREVIATIONS = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
)
US_STATE_NAMES = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia",
)


def _is_us_location(location: str) -> bool:
    lowered = location.lower()
    if any(re.search(pattern, lowered) for pattern in US_COUNTRY_PATTERNS):
        return True
    if any(re.search(rf"\b{re.escape(state)}\b", lowered) for state in US_STATE_NAMES):
        return True
    # Require postal abbreviations to follow a comma so ordinary words such as "or"
    # cannot be mistaken for Oregon.
    abbreviations = "|".join(US_STATE_ABBREVIATIONS)
    return bool(re.search(rf",\s*(?:{abbreviations})\b", location, re.IGNORECASE))


def relevance_reasons(job: dict) -> tuple[bool, list[str]]:
    """Return a decision and auditable reasons using posting text only."""
    title = (job.get("title") or "").lower()
    location = (job.get("location") or "").lower()
    reasons: list[str] = []
    if any(re.search(pattern, title) for pattern in EXCLUDED_TITLE_PATTERNS):
        return False, ["excluded_title"]
    if not any(re.search(pattern, title) for pattern in ROLE_PATTERNS):
        return False, ["not_ai_ml_role"]
    reasons.append("ai_ml_title")
    if not location:
        return False, reasons + ["location_missing"]
    if not _is_us_location(job.get("location") or ""):
        return False, reasons + ["not_us_location"]
    return True, reasons + ["us_location"]


def is_relevant(job: dict) -> bool:
    return relevance_reasons(job)[0]
