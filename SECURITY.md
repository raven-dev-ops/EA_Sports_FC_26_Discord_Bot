# Security Policy

## Supported Versions

Only the latest release and the `main` branch receive security updates.

## Reporting a Vulnerability

Please report security issues using GitHub's private security advisories:

1. Go to the repository's Security tab.
2. Click "Report a vulnerability".
3. Provide steps to reproduce and any relevant logs or screenshots.

If private reporting is not available, contact the maintainers directly and
avoid filing a public issue.

## Secrets and Deployments

- Keep `.env` and Heroku config vars private; rotate Discord tokens and API keys immediately if exposed.
- Do not post tokens, MongoDB URIs, or Google credentials in issues, logs, or screenshots.
- If a secret leak is suspected, revoke the credential and open a private advisory with the timestamp and impacted environment.
- CI runs automated secret scanning (gitleaks). Please resolve any findings before merging.
- Avoid logging secrets; redact tokens/URIs from debugging output and screenshots.

## Response Targets

- Acknowledgement: within 3 business days.
- Initial assessment: within 7 business days.
- Fix timeline: based on severity and impact.
