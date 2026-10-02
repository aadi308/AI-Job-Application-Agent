from fastapi import FastAPI, HTTPException

from app.db import get_connection, upsert_job
from app.models import ScrapeRequest, ScrapeResult
from app.runtime import is_demo_mode
from app.scrapers import greenhouse, lever

app = FastAPI(title="AI Job Application Agent")

SCRAPERS = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
}


@app.get("/health")
def health():
    with get_connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/scrape/trigger", response_model=ScrapeResult)
def trigger_scrape(req: ScrapeRequest):
    if is_demo_mode():
        raise HTTPException(
            status_code=403,
            detail="Scraping is disabled in the public read-only demo. Run locally to import jobs.",
        )
    fetch = SCRAPERS[req.source]
    try:
        jobs = fetch(req.board)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    inserted = 0
    with get_connection() as conn:
        for job in jobs:
            if upsert_job(conn, job):
                inserted += 1
        conn.commit()

    return ScrapeResult(source=req.source, board=req.board, fetched=len(jobs), inserted=inserted)
