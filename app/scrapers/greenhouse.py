from datetime import datetime, timezone

import requests

from app.scrapers._html import strip_html

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"


def fetch_jobs(board_token: str) -> list[dict]:
    """Fetch open jobs from a company's public Greenhouse job board.

    board_token is the company slug used by Greenhouse, e.g. "gitlab" for
    https://boards-api.greenhouse.io/v1/boards/gitlab/jobs
    """
    resp = requests.get(
        BASE_URL.format(board_token=board_token),
        params={"content": "true"},
        timeout=15,
    )
    resp.raise_for_status()
    raw_jobs = resp.json().get("jobs", [])

    jobs = []
    for job in raw_jobs:
        posted_at = None
        if job.get("first_published"):
            posted_at = datetime.fromisoformat(job["first_published"]).astimezone(timezone.utc)

        jobs.append(
            {
                "source_job_id": str(job["id"]),
                "board_token": board_token,
                "company": job.get("company_name") or board_token,
                "title": job["title"],
                "url": job["absolute_url"],
                "source": "greenhouse",
                "location": (job.get("location") or {}).get("name"),
                "posted_at": posted_at,
                "description": strip_html(job.get("content")),
            }
        )
    return jobs
