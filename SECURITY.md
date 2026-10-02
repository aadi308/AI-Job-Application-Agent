# Security Policy

## Supported version

This project is an active prototype. Security fixes are applied to the latest code on the `main` branch; older revisions are not maintained separately.

## Reporting a vulnerability

Please do not disclose vulnerabilities, exposed credentials, or personal data in a public issue or discussion.

Use GitHub's private vulnerability reporting feature for this repository. If that feature is unavailable, contact the repository owner privately through the contact method listed on their GitHub profile and include only enough information to reproduce the issue safely.

Useful reports include:

- the affected component and revision;
- impact and realistic attack scenario;
- minimal reproduction steps;
- suggested remediation, if known.

Do not include real resumes, API keys, access tokens, or unrelated personal information. Allow the maintainer reasonable time to investigate before public disclosure.

## Deployment warning

Public candidate workflows must use `APP_MODE=production`. Production mode uses Supabase Auth, derives ownership from verified bearer tokens, routes private operations through FastAPI, isolates personalized PostgreSQL rows by owner, and applies per-user daily model-call quotas. `APP_MODE=demo` remains anonymous and read-only; `APP_MODE=local` must never be exposed publicly.

The API service alone should receive `DATABASE_URL` and provider credentials. The Streamlit service receives only the Supabase project URL, its public anon key, and the private API address. Never provide a Supabase service-role key to either browser-facing code or this application.

Application quotas reduce accidental usage but are not a billing control. Configure spending caps and alerts with each model provider, use conservative limits, and monitor usage before inviting users.

Secrets must be provided through environment variables or a deployment secret manager. Never commit `.env`, private resumes, uploaded files, generated output, local databases, or vector-store data.

## Scope

Security reports are welcome for the application, provider routing, upload handling, data exposure, prompt/log redaction, and deployment configuration. Third-party provider outages, pricing disputes, and vulnerabilities in external Greenhouse/Lever boards should be reported to those providers unless this project introduces the issue.
