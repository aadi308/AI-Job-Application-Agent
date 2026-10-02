# AI Job Application Agent

An evidence-first workspace for finding jobs, evaluating fit, tailoring a resume, and preparing outreach without inventing candidate claims.

The project combines public Greenhouse and Lever job-board APIs, PostgreSQL, FastAPI, Streamlit, and reviewable AI-assisted workflows. It supports a full private local workspace and a safe, read-only public demo.

> **Status:** active prototype. Generated scores and documents require human review. The project does not submit applications automatically.

## Features

- Import jobs from public Greenhouse and Lever JSON APIs.
- Track posting, discovery, last-seen, and last-checked timestamps in PostgreSQL.
- Browse every imported job family—not only DevOps or MLOps roles.
- Filter by keyword, location, work mode, employment type, experience level, sponsorship or work-authorization language, status, and ATS score.
- Extract an evidence-backed candidate profile and require approval before generation.
- Evaluate job fit with auditable Groq/OpenRouter routing.
- Tailor resumes using only approved candidate evidence.
- Validate generated claims and PDFs before saving final output.
- Prepare reviewable outreach drafts.
- Publish a daily refreshed, allowlisted US AI/ML job feed in demo mode.

## How it works

```text
Greenhouse / Lever APIs
          |
          v
   FastAPI import layer ----> PostgreSQL
                                  |
                    +-------------+-------------+
                    |             |             |
                 Job UI      ATS evaluation   Profile evidence
                                                |
                                                v
                                      Resume + outreach drafts
                                                |
                                                v
                                           Human review
```

## Application modes

| Mode | Intended use | Behavior |
| --- | --- | --- |
| `APP_MODE=local` | Private development and personal use | Enables imports, profile editing, evaluation, resume tailoring, and status updates |
| `APP_MODE=demo` | Publicly hosted showcase | Shows the allowlisted employer-board feed and disables user-triggered database writes and paid-model actions |

Do not expose local mode publicly without authentication, authorization, per-user data isolation, rate limits, and model-cost controls.

## Prerequisites

- Git
- Docker Desktop or another Docker Compose-compatible runtime
- Python 3.12 or 3.13
- Optional: a Groq API key, an OpenRouter API key, or both for AI-assisted workflows

Greenhouse and Lever imports use public APIs and do not require API keys.

## Quick start

```bash
git clone https://github.com/aadi308/AI-Job-Application-Agent.git
cd AI-Job-Application-Agent

python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows, create the environment with `py -3.13 -m venv .venv` and activate it with `.venv\Scripts\activate`.

Start PostgreSQL and apply the schema:

```bash
docker compose up -d postgres
python scripts/init_db.py
```

Start the API:

```bash
uvicorn app.main:app --reload
```

In another terminal, start the private local dashboard:

```bash
source .venv/bin/activate
APP_MODE=local streamlit run app/dashboard.py
```

Or run the privacy-safe demo interface locally:

```bash
source .venv/bin/activate
APP_MODE=demo streamlit run app/dashboard.py
```

Open the dashboard at <http://localhost:8501>, API documentation at <http://localhost:8000/docs>, or the health check at <http://localhost:8000/health>.

## Configuration

Copy `.env.example` to `.env` and edit only the local copy. `.env` is ignored by Git.

| Variable | Required | Purpose |
| --- | --- | --- |
| `APP_MODE` | No | Selects `local` or `demo`; defaults are documented in `.env.example` |
| `DATABASE_URL` | Yes | PostgreSQL connection used by the application |
| `DEMO_DATABASE_URL` | Hosted sync only | Write-capable hosted database URL stored as a GitHub environment secret |
| `SEED_DEMO_DATA` | No | Enables fictional fixtures; keep `false` for the real public feed |
| `FASTAPI_URL` | Custom dashboard deployments | Public API address used by Streamlit |
| `FASTAPI_HOSTPORT` | Render Blueprint | Private API host and port supplied by Render |
| `GROQ_API_KEY` | Groq workflows | Groq credential; sufficient for Groq-only operation |
| `OPENROUTER_API_KEY` | OpenRouter workflows | OpenRouter credential; optional when Groq is used without fallback |
| `LLM_PRIMARY_PROVIDER` | No | Preferred provider, `groq` or `openrouter` |
| `LLM_ENABLE_FALLBACK` | No | Allows the configured secondary provider after a primary failure |
| `LLM_ROUTINE_CONFIDENCE_THRESHOLD` | No | Minimum confidence before escalation |
| `LLM_MAX_RETRIES` | No | Maximum provider retry count |

At least one provider key is required for ATS evaluation and resume generation. Keep provider keys out of public demo deployments.

## Import jobs

Use the dashboard import action or the API. The board value is the company slug used by the public job board.

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

The local importer stores every role returned by a selected board. Work mode, sponsorship, and authorization terms are often absent or ambiguous, so the dashboard labels uncertain values instead of guessing. Always verify details on the original employer page.

## Candidate profile and tailored resumes

In local mode:

1. Open **Candidate Profile** and upload a resume, or create a private `master_resume.md`.
2. Review extracted facts and approve the profile.
3. Import a job with its complete description.
4. Evaluate the job and confirm that the reliability gate passes.
5. Generate the tailored resume from the selected job.
6. Review the claim-validation and PDF-validation results before using the output.

The tailoring workflow selects relevant approved skills, roles, projects, certifications, and bullets. It does not intentionally invent or rewrite factual evidence. Generated files are saved under the ignored `outputs/` directory.

For command-line use:

```bash
python -m app.agents.run_workflow 1
```

Replace `1` with the database job ID. For local PDF generation, install the browser once:

```bash
python -m playwright install chromium
```

## Daily public job feed

The hosted demo reads its employer allowlist from [`config/demo_boards.json`](config/demo_boards.json). The [`Sync public demo jobs`](.github/workflows/sync-demo-jobs.yml) workflow runs daily and can also be started manually.

The sync applies idempotent migrations, reads public employer APIs, keeps deterministic US AI/ML title and location matches, and upserts demo-visible jobs. Successful checks update freshness fields. A listing closes only after two consecutive successful misses; failed or anomalous board responses do not count as misses.

To run the same sync locally against a disposable database:

```bash
export DEMO_DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require'
DATABASE_URL="$DEMO_DATABASE_URL" SEED_DEMO_DATA=false python scripts/init_db.py
DATABASE_URL="$DEMO_DATABASE_URL" APP_MODE=demo SEED_DEMO_DATA=false python scripts/sync_demo_jobs.py
```

## Testing

The default suite is deterministic and does not use the network, paid models, or a developer database:

```bash
python -m pytest
```

Run isolated PostgreSQL and PDF integration tests with the test Compose service:

```bash
docker compose -f docker-compose.test.yml up -d
TEST_DATABASE_URL=postgresql://job_search_test:job_search_test@127.0.0.1:5433/job_search_test \
  python -m pytest -o addopts="-ra" -m "integration and not live"
docker compose -f docker-compose.test.yml down
```

Opt-in live checks can contact external services and may consume paid quota:

```bash
RUN_LIVE_TESTS=true python -m pytest -o addopts="-ra" -m live
```

Never point tests at a production database or use a real candidate record as a fixture.

## Public deployment

The repository includes a Render Blueprint for the FastAPI and Streamlit services. A practical free-tier demo setup is:

- Render for the two web services.
- Neon for PostgreSQL.
- GitHub Actions for CI, gated deployment hooks, and daily job synchronization.

Free plans and quotas change; verify the current provider terms before deployment.

### Configure the GitHub environment

1. Open the repository on GitHub.
2. Go to **Settings → Environments → New environment**.
3. Name the environment `production`.
4. Optionally restrict deployment branches to `main`. Do not require manual reviewers if the daily scheduled sync must run unattended.
5. Under **Environment secrets**, add:

| Secret | Value |
| --- | --- |
| `DEMO_DATABASE_URL` | Write-capable Neon connection string used by the trusted sync workflow |
| `RENDER_API_DEPLOY_HOOK` | Render deploy-hook URL for the API service |
| `RENDER_DASHBOARD_DEPLOY_HOOK` | Render deploy-hook URL for the dashboard service |

Do not add `GROQ_API_KEY`, `OPENROUTER_API_KEY`, candidate data, or resume content to the public-demo environment.

### Deploy

1. Create a Neon database and retain its TLS-enabled pooled connection string.
2. In Render, create a Blueprint from `render.yaml`.
3. Set `DATABASE_URL` for both Render services to the Neon connection string.
4. Add the three GitHub environment secrets above.
5. Run **Actions → Sync public demo jobs → Run workflow** once to initialize and populate the feed.
6. Push to `main`. A successful CI run triggers both Render deploy hooks when they are configured.

The public interface remains behaviorally read-only in `APP_MODE=demo`. The current containers run idempotent schema initialization at startup, so their database credential must support schema and data writes even though browser-triggered mutations are disabled.

For a manually created Render dashboard service, set **Docker Command** to:

```text
/app/scripts/start_dashboard.sh
```

## Privacy and security

- Never commit `.env`, real resumes, uploaded files, generated outputs, local databases, or vector data.
- Never include API keys or personal data in issues, logs, screenshots, examples, or test fixtures.
- Review LLM provider data policies before sending private resume content.
- Treat ATS scores and generated writing as suggestions, not hiring decisions.
- Verify job availability and employment terms on the original employer page.
- If a secret or private file was committed previously, rotate the credential and remove it from Git history; `.gitignore` alone cannot erase history.

See [SECURITY.md](SECURITY.md) for vulnerability reporting and deployment cautions.

## Project structure

```text
app/                    FastAPI, Streamlit, agents, providers, and resume tools
config/                 Public demo board allowlist
db/                     Initial schema and idempotent migrations
examples/               Fictional public fixtures
scripts/                Database initialization and demo synchronization
tests/                  Unit, integration, and opt-in live tests
.github/workflows/       CI, deployment, and scheduled synchronization
```

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Contributions should preserve evidence tracking, privacy boundaries, deterministic tests, and human approval.

Licensed under the [MIT License](LICENSE).
