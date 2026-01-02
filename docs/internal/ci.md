# CI / GitHub Actions

This repo's workflows run on a **self-hosted** runner to avoid GitHub-hosted runner billing blocks.

## Self-hosted runner requirement

- Workflows: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, and `.github/workflows/codeql.yml`
- Required runner labels: `self-hosted`, `Windows`, `X64`, `offside`

If the runner is offline, CI and tag releases will queue indefinitely.

## GitHub-managed "Automatic Dependency Submission (Python)"

You may see a failing check named `Automatic Dependency Submission (Python)` even when repo CI is green.

- This is a **GitHub-managed dynamic workflow** (it does not live in this repo).
- It runs on **GitHub-hosted** runners and will fail if your account is blocked by GitHub billing/spending limits.

How to fix:
- Preferred: Disable it in the repo UI: `Settings -> Code security and analysis -> Dependency graph -> Automatic dependency submission -> Disable`
- Alternative: Fix GitHub billing/spending limits so GitHub-hosted runners can start.

Notes:
- `docs/public/billing.md` is Stripe billing for the app, not GitHub billing.

## Release metadata checks

CI runs `python -m scripts.check_release_metadata` to verify:
- `VERSION` is valid SemVer.
- The top `CHANGELOG.md` entry matches `VERSION`.
- Tag releases use `vX.Y.Z` that matches `VERSION`.

## Log hygiene checks

CI runs `python -m scripts.check_log_hygiene` to flag logging calls that include sensitive variable names.

## A11y template checks

CI runs `python -m scripts.check_a11y_templates` to enforce skip links, aria-current, and live region markers.

## Visual regression checks

CI runs Playwright screenshot tests for key pages. To update baselines:
- `python -m playwright install chromium`
- `UPDATE_VISUAL_BASELINES=1 python -m pytest tests/visual/test_visual_regression.py`
