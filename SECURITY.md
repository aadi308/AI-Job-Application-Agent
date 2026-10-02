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

The FastAPI and Streamlit applications currently have no built-in authentication, authorization, or rate limiting. Public deployments must keep `APP_MODE=demo`, which exposes only the allowlisted public employer-board feed and disables user-triggered mutations and paid-model actions. Before exposing the full local workflow, add access control, per-user isolation, rate limits, provider cost caps, and appropriate network restrictions.

Secrets must be provided through environment variables or a deployment secret manager. Never commit `.env`, private resumes, uploaded files, generated output, local databases, or vector-store data.

## Scope

Security reports are welcome for the application, provider routing, upload handling, data exposure, prompt/log redaction, and deployment configuration. Third-party provider outages, pricing disputes, and vulnerabilities in external Greenhouse/Lever boards should be reported to those providers unless this project introduces the issue.
