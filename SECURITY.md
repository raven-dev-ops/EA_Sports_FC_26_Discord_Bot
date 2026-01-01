# Security Policy

## Supported Versions

Only the latest release and the `main` branch receive security updates.

## Reporting a Vulnerability

Please use GitHub's private vulnerability reporting:

1. Go to the repository's Security tab.
2. Click "Report a vulnerability".
3. Include repro steps, affected version(s), and any relevant logs or screenshots.

If the Security tab does not show "Report a vulnerability", private reporting is not enabled
for the repo. In that case, contact the maintainers via the support channels published on
the `/support` page for the deployment (SUPPORT_EMAIL or SUPPORT_DISCORD_INVITE_URL) and
do not open a public issue.

## Security Automation

- Dependabot updates should be enabled for Python dependencies and GitHub Actions.
- Code scanning should be enabled (CodeQL) to catch common issues early.
- CI runs secret scanning (gitleaks); resolve any findings before merging.

## Secrets and Deployments

- Keep `.env` and Heroku config vars private; rotate Discord tokens and API keys immediately if exposed.
- Do not post tokens, MongoDB URIs, or Google credentials in issues, logs, or screenshots.
- If a secret leak is suspected, revoke the credential and open a private advisory with the timestamp and impacted environment.
- Avoid logging secrets; redact tokens/URIs from debugging output and screenshots.

## Response Targets

- Acknowledgement: within 3 business days.
- Initial assessment: within 7 business days.
- Fix timeline: based on severity and impact.
