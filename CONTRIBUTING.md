# Contributing

Thanks for helping improve AI Job Application Agent. Contributions should keep the project truthful, privacy-conscious, and easy to run locally.

## Before opening a pull request

1. Fork and clone the repository.
2. Create a focused branch from `main`.
3. Create a virtual environment and install `requirements.txt`.
4. Copy `.env.example` to `.env`; never commit the resulting file.
5. Start PostgreSQL with `docker compose up -d postgres` when your change needs it.
6. Add or update tests for the behavior you changed.
7. Run the relevant checks and document any check you could not run.

Example:

```bash
git switch -c feat/short-description
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d postgres
python -m pytest tests/test_llm_router.py
```

## Test boundaries

Keep the default contribution path deterministic and free:

- Mock LLM clients in normal tests.
- Mock Greenhouse/Lever responses unless a test is explicitly a live-network check.
- Use fictional candidate data and an isolated test database.
- Do not turn on paid or live integrations in CI.
- Real provider checks belong under `tests/integration/` and must require the explicit `RUN_LIVE_TESTS=true` environment flag.

The existing suite still contains some local end-to-end tests that need live services or local database state. Do not add new dependencies on private local files.

## Privacy and generated content

Never contribute:

- resumes, contact details, profile URLs, or application records belonging to a real person;
- `.env` files, API keys, database credentials, logs containing prompts, or provider responses with personal data;
- generated PDFs or local vector/database data;
- fabricated candidate claims presented as facts.

Use `examples/sample_resume.md` or another clearly fictional fixture. Before committing, inspect both staged content and ignored status:

```bash
git status --short
git diff --cached
git check-ignore -v .env master_resume.md resume_uploads/example.pdf
```

## Pull requests

Keep each pull request small enough to review. Include:

- what changed and why;
- how you tested it;
- database or environment changes;
- screenshots for visible dashboard changes;
- privacy, cost, or compatibility implications.

Do not include drive-by formatting or unrelated generated files. Maintainers may request changes when a contribution weakens evidence tracking, human review, or provider safety controls.

## Reporting security issues

Do not open a public issue for a suspected vulnerability or data exposure. Follow [SECURITY.md](SECURITY.md).
