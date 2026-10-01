# AI Job Application Agent

An evidence-first job-search workspace for discovering AI/ML and MLOps roles, evaluating fit, tailoring a resume, and preparing outreach without silently inventing candidate claims.

The project combines public Greenhouse and Lever job-board APIs, PostgreSQL, FastAPI, Streamlit, and a reviewable multi-agent workflow. Human approval and claim validation remain part of the process: generated material is a draft, not an automatic application.

> **Project status:** active prototype. Local mode provides the complete private workflow; hosted `demo` mode is read-only, uses fictional data, and disables paid or mutating actions. It is not an autonomous application bot.

## Why this project exists

Job searches often scatter information across browser tabs, spreadsheets, job boards, and one-off resume files. This project puts that work into one inspectable pipeline:

```text
Greenhouse / Lever boards
           |
           v
     FastAPI scraper
           |
           v
       PostgreSQL
           |
           +--> ATS evaluation
           +--> candidate evidence
           +--> tailored resume + outreach
                         |
                         v
                    human review
```

The design emphasizes reproducibility, truthful outputs, provider audit records, and control over when paid model calls occur.

## Current capabilities

- Import jobs from public Greenhouse and Lever JSON APIs.
- Store and update jobs in PostgreSQL without duplicating the same URL.
- Browse, filter, inspect, and update jobs in a Streamlit dashboard.
- Extract a structured candidate profile with evidence and require profile approval.
- Route LLM work between Groq and OpenRouter with fallback behavior and audit records.
- Score job fit and produce a reviewable explanation.
- Draft a tailored resume and outreach message.
- Validate resume claims and generated PDFs before saving a final deliverable.
- Pause the workflow for explicit human approval.

## Privacy-safe repository

Real resumes, uploaded files, generated outputs, local vector data, environment files, and internal progress notes are excluded by `.gitignore`. The repository includes only the fictional [sample resume](examples/sample_resume.md).

If a private file was ever committed, adding it to `.gitignore` does **not** remove it from Git history. Rotate any exposed credentials and clean the history before publishing.

## Prerequisites

- Git
- Docker Desktop or another Docker Compose-compatible runtime
- Python 3.12 or 3.13
- Optional: a Groq API key and/or OpenRouter API key for real LLM workflows

Greenhouse and Lever scraping uses public APIs and needs no API key. LLM-backed profile extraction, evaluation, and generation require provider credentials and may incur charges.

## Quick start: local database and application

Clone the repository, create an isolated Python environment, and install dependencies. Use
an explicit supported interpreter: on macOS, `/usr/bin/python3` can still be Python 3.9 even
when a newer Homebrew Python is installed.

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/AI-Job-Search-Agent.git
cd AI-Job-Search-Agent

# macOS/Homebrew example (install first with: brew install python@3.13)
python3.13 --version
python3.13 -m venv .venv

source .venv/bin/activate
python --version  # must report 3.12.x or 3.13.x
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

On Linux, use an installed `python3.12` or `python3.13`. On Windows, use
`py -3.13 -m venv .venv`, then activate `.venv\Scripts\activate`.

If the environment was accidentally created with Python 3.9, recreate only that environment:

```bash
deactivate 2>/dev/null || true
rm -rf .venv
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Start PostgreSQL:

```bash
docker compose up -d postgres
docker compose ps
```

The first startup initializes the schema from `db/schema.sql`. That initialization runs only when the Docker volume is new. To inspect logs:

```bash
docker compose logs -f postgres
```

Start the API in one terminal:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Then start the dashboard in another terminal:

```bash
source .venv/bin/activate
streamlit run app/dashboard.py
```

Open:

- Dashboard: <http://localhost:8501>
- API documentation: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

## Configuration

`.env.example` contains the supported values. Never commit `.env` or paste real credentials into an issue, log, screenshot, test fixture, or sample file.

| Variable | Required | Purpose |
| --- | --- | --- |
| `APP_MODE` | No | `local` keeps the complete workflow; `demo` enables the read-only public showcase |
| `DATABASE_URL` | Yes | PostgreSQL connection used by the API, dashboard, and workflow |
| `FASTAPI_URL` | Custom dashboard deployments | Address used by Streamlit to reach FastAPI; defaults to localhost |
| `FASTAPI_HOSTPORT` | Render only | Private API host and port supplied automatically by the Blueprint |
| `OPENROUTER_API_KEY` | For OpenRouter or fallback | Credential for OpenRouter requests |
| `OPENROUTER_BASE_URL` | No | OpenRouter-compatible endpoint |
| `OPENROUTER_FALLBACK_MODEL` | No | Model used by the fallback route |
| `GROQ_API_KEY` | For Groq | Credential for Groq requests |
| `GROQ_BASE_URL` | No | Groq-compatible endpoint |
| `GROQ_ROUTINE_MODEL` | No | Routine task model |
| `GROQ_STRONG_MODEL` | No | Higher-capability task model |
| `LLM_PRIMARY_PROVIDER` | No | Preferred provider; defaults are shown in `.env.example` |
| `LLM_ENABLE_FALLBACK` | No | Whether a failed/weak primary result may use the fallback provider |
| `LLM_ROUTINE_CONFIDENCE_THRESHOLD` | No | Confidence threshold for escalation |
| `LLM_MAX_RETRIES` | No | Maximum provider retry count |

The current provider configuration expects an OpenRouter key as the fallback even when Groq is the primary provider. If you only want to inspect the scraper and dashboard, leave LLM actions unused.

## Import jobs

Use the dashboard's scrape action or call the API directly. The `board` value is the company slug used by the public job board.

Greenhouse example:

```bash
curl -X POST http://localhost:8000/scrape/trigger \
  -H 'Content-Type: application/json' \
  -d '{"source":"greenhouse","board":"openai"}'
```

Lever example:

```bash
curl -X POST http://localhost:8000/scrape/trigger \
  -H 'Content-Type: application/json' \
  -d '{"source":"lever","board":"netflix"}'
```

Board availability and slugs are controlled by those external services, so examples can change.

## Candidate profile and generation workflow

For a private local run, upload a resume from the **Candidate Profile** page or place your private source at `master_resume.md`. Both locations are ignored by Git. Review extracted facts and approve the profile before using generated output.

After importing and evaluating a job, the command-line review workflow can be run with its database job ID:

```bash
python -m app.agents.run_workflow 1
```

Playwright produces the PDF. Install its Chromium browser once for a non-containerized setup:

```bash
playwright install chromium
```

Generated artifacts are written under `outputs/`, which is intentionally ignored.

## Testing

Tests are grouped through pytest markers so the default test command stays deterministic and free:

```bash
pytest
```

Database-backed integration tests use a separate disposable PostgreSQL service:

```bash
docker compose -f docker-compose.test.yml up -d
TEST_DATABASE_URL=postgresql://job_search_test:job_search_test@127.0.0.1:5433/job_search_test \
  pytest -o addopts="-ra" -m "integration and not live"
docker compose -f docker-compose.test.yml down
```

Opt-in live tests can contact providers, require internet access, and may consume paid quota:

```bash
RUN_LIVE_TESTS=true pytest -o addopts="-ra" -m live
```

Real LLM integration tests can consume paid quota and require an additional explicit flag:

```bash
RUN_LIVE_TESTS=true pytest -o addopts="-ra" -m live tests/integration/test_real_llm.py -v
```

Never use a production database or a real candidate record as a test fixture.

## Deployment overview

For a small publicly accessible demonstration, the included deployment targets:

- **Render:** deploy the FastAPI service and Streamlit dashboard as two Python web services.
- **Neon:** host PostgreSQL and provide its pooled connection string through `DATABASE_URL`.

Render's free services have limited memory and sleep when idle. Neon scales idle databases down. Verify current quotas before deploying because free plans can change. The Blueprint sets `APP_MODE=demo`, seeds synthetic jobs, disables all write/LLM actions, and requires no provider key.

Suggested service commands:

| Service | Start command |
| --- | --- |
| FastAPI | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Streamlit | `streamlit run app/dashboard.py --server.address 0.0.0.0 --server.port $PORT` |

The included `render.yaml` defines both web services. After creating a Neon database, a typical deployment is:

1. Push the sanitized repository to GitHub.
2. In Render, create a Blueprint from the repository's `render.yaml`.
3. Set `DATABASE_URL` on both services to the same pooled Neon URL with `sslmode=require`.
4. Keep provider credentials unset for the public demo. Render wires the dashboard to the API over its private network.
5. Add the two Render deploy-hook URLs as GitHub repository secrets named `RENDER_API_DEPLOY_HOOK` and `RENDER_DASHBOARD_DEPLOY_HOOK`.

At service startup, `scripts/init_db.py` initializes a new external database exactly once. It is intentionally a bootstrap helper, not a schema-migration system.

The public demo is intentionally read-only. Its highest-scoring fictional job includes pre-generated resume and outreach previews so visitors can inspect the complete output shape without invoking a model. Do not change `APP_MODE` to `local` or add paid provider keys unless you first add authentication, authorization, rate limits, per-user data isolation, and cost controls. Render's filesystem is ephemeral; PostgreSQL data remains in Neon.

## Cost, accuracy, and security notes

- LLM providers may bill per token. Confirm provider limits and pricing before a batch run.
- Generated ATS scores and writing suggestions are heuristics, not hiring decisions.
- Always review generated claims; the validators reduce risk but do not guarantee correctness.
- Public job-board endpoints may change, throttle requests, or remove listings.
- Resume and profile content is sensitive personal data. Understand each provider's data policy before sending it to an external model.
- The project does not submit job applications automatically.

## Project layout

```text
app/
  agents/       # orchestration, evaluation, resume, and outreach agents
  candidate/    # evidence-backed candidate profile extraction and storage
  components/   # Streamlit UI components
  core/         # vector-store support
  llm/          # provider routing, schemas, audit, and safety behavior
  resume/       # tailoring, validation, HTML, and PDF generation
  scrapers/     # Greenhouse and Lever clients
  dashboard.py  # Streamlit entry point
  main.py       # FastAPI entry point
db/schema.sql   # initial PostgreSQL schema
examples/       # fictional public examples
tests/          # unit, DB, live-network, and opt-in provider checks
```

## Roadmap

- Database migrations instead of init-only SQL
- Authentication, rate limits, and per-user isolation for a hosted interactive mode
- Duplicate/stale-job detection and explainable ATS scoring
- Automated quality regression fixtures for generated resumes

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Report security or privacy issues using the private process in [SECURITY.md](SECURITY.md), not a public issue.

Licensed under the [MIT License](LICENSE).
