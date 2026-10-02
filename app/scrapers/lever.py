from datetime import datetime, timezone

import requests

from app.scrapers._html import strip_html

BASE_URL = "https://api.lever.co/v0/postings/{company}"


def _build_description(job: dict) -> str | None:
    parts = []
    if job.get("descriptionPlain"):
        parts.append(job["descriptionPlain"].strip())
    for item in job.get("lists") or []:
        heading = (item.get("text") or "").strip()
        body = strip_html(item.get("content"), max_chars=2000)
        if body:
            parts.append(f"{heading}: {body}" if heading else body)
    if job.get("additionalPlain"):
        parts.append(job["additionalPlain"].strip())
    return strip_html("\n\n".join(parts)) if parts else None


def fetch_jobs(company: str) -> list[dict]:
    """Fetch open jobs from a company's public Lever postings API.

    company is the slug used by Lever, e.g. "palantir" for
    https://api.lever.co/v0/postings/palantir?mode=json
    """
    resp = requests.get(
        BASE_URL.format(company=company),
        params={"mode": "json"},
        timeout=15,
    )
    # Lever returns 404 with {"ok": false, "error": "..."} for unknown company
    # slugs, so check the body before raising on status.
    raw_jobs = resp.json()
    if isinstance(raw_jobs, dict):
        raise ValueError(f"Lever API error for '{company}': {raw_jobs.get('error')}")
    resp.raise_for_status()

    jobs = []
    for job in raw_jobs:
        posted_at = None
        if job.get("createdAt"):
            posted_at = datetime.fromtimestamp(job["createdAt"] / 1000, tz=timezone.utc)

        categories = job.get("categories") or {}
        jobs.append(
            {
                "source_job_id": str(job["id"]),
                "board_token": company,
                "company": company,
                "title": job["text"],
                "url": job["hostedUrl"],
                "source": "lever",
                "location": categories.get("location"),
                "posted_at": posted_at,
                "description": _build_description(job),
            }
        )
    return jobs
