# CI / GitHub Actions

This repo’s workflows run on a **self-hosted** runner to avoid GitHub-hosted runner billing blocks.

## Self-hosted runner requirement

- Workflows: `.github/workflows/ci.yml` and `.github/workflows/release.yml`
- Required runner labels: `self-hosted`, `Windows`, `X64`, `offside`

If the runner is offline, CI and tag releases will queue indefinitely.

## GitHub-managed “Automatic Dependency Submission (Python)”

You may see a failing check named `Automatic Dependency Submission (Python)` even when repo CI is green.

- This is a **GitHub-managed dynamic workflow** (it does not live in this repo).
- It attempts to run on **GitHub-hosted** runners and will fail if your account is blocked by billing/spending limits.

To stop it from failing:
- Disable it in the repo UI: `Settings → Code security and analysis → Dependency graph → Automatic dependency submission → Disable`

Notes:
- `docs/billing.md` is **Stripe** billing for the app, not GitHub billing.
