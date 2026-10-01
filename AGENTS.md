# AGENTS.md — AI Job Search System Architecture

## Objective
Multi-agent system to find and track AI/ML Engineer and MLOps roles in the US market.

## Current Scope
- PostgreSQL job and application tracking
- FastAPI endpoints for health checks and manual job-board imports
- Greenhouse and Lever public API clients
- Streamlit dashboard and candidate-profile review
- Evidence-backed ATS evaluation, resume tailoring, PDF validation, and outreach drafts
- Groq/OpenRouter routing with audit records and human approval
- Read-only, fictional-data public demo mode (`APP_MODE=demo`)

## Stack Decisions
- **Postgres**: Docker container (docker-compose), not a local Homebrew install — user's choice, keeps it isolated/disposable.
- **Backend**: Python + FastAPI
- **Scraping**: `requests` against Greenhouse (`boards-api.greenhouse.io`) and Lever (`api.lever.co`) public JSON APIs — no HTML scraping needed, both expose stable JSON endpoints.

## Sub-agent personas used per feature
- **Architect** — designs schema/API shape before code is written
- **Implementer** — writes the code
- **Reviewer** — writes and runs tests, verifies against real API calls

## Repository layout
```
AI-Job-Search-Agent/
  docker-compose.yml       # postgres service
  .env.example             # safe configuration template
  Dockerfile               # API/dashboard deployment image
  render.yaml              # public demo services
  requirements.txt
  db/
    schema.sql
  app/
    main.py                # FastAPI app, /scrape/trigger endpoint
    db.py                  # connection/session handling
    models.py               # API models
    scrapers/
      greenhouse.py
      lever.py
    candidate/              # evidence-backed profile
    llm/                    # model providers and routing
    resume/                 # tailoring and validation
  tests/
    test_scrapers.py
    test_api.py
  examples/
    sample_resume.md        # fictional public fixture
  .github/workflows/        # CI and gated Render deployment
```

## Safety and test boundaries
- Never commit `.env`, real resumes, uploaded files, generated outputs, or local vector data.
- Keep default `pytest` deterministic: no network, paid models, or developer database.
- Mark disposable-database/browser tests `integration` and real external calls `live`.
- Keep hosted demo mode read-only. Do not expose local mode publicly without authentication,
  per-user isolation, rate limits, and cost controls.
