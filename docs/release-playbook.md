# Release Playbook

This doc is the repeatable checklist for deploying and rolling back Offside.

See also:
- `docs/qa-checklist.md`
- `docs/billing.md`
- `docs/data-lifecycle.md`
- `.env.example`

## Release checklist

- [ ] CI is green on `main` (ruff, mypy, pytest, build).
- [ ] Review open PRs and Dependabot updates; merge or defer intentionally.
- [ ] Verify secrets are not committed (no `.env` changes, no tokens in git history).
- [ ] Update `VERSION` and `CHANGELOG.md` (add the new release section at the top).
- [ ] Run local gates:
  - `ruff check .`
  - `mypy .`
  - `pytest -q`
  - `python -m build --outdir dist`
- [ ] Run fast smoke tests:
  - Web dashboard: `pytest -q tests/e2e/test_dashboard_smoke.py`
  - Discord staging guild: `docs/qa-checklist.md`
- [ ] Confirm Discord developer portal settings are correct (redirect URIs, install link, bot perms).
- [ ] Deploy the release to production (see platform notes below).
- [ ] Watch logs for 5–10 minutes after deploy (startup migrations, setup tasks, dashboard health).

## Environment variable checklist

The source of truth is `.env.example`. Before a release, verify the production environment matches it.

At minimum, confirm:

- Discord
  - `DISCORD_TOKEN`
  - `DISCORD_APPLICATION_ID`
  - `DISCORD_CLIENT_SECRET` (web dashboard OAuth)
  - `DASHBOARD_REDIRECT_URI` (must match the production domain, ends with `/oauth/callback`)
- MongoDB
  - `MONGODB_URI`
  - `MONGODB_DB_NAME`
  - `MONGODB_COLLECTION`
  - `MONGODB_PER_GUILD_DB` / `MONGODB_GUILD_DB_PREFIX` (if using per-guild databases)
- Billing (if enabled; see `docs/billing.md`)
  - `STRIPE_SECRET_KEY`
  - `STRIPE_WEBHOOK_SECRET`
  - `STRIPE_PRICE_PRO_ID`

Optional but commonly used:
- `SUPPORT_DISCORD_INVITE_URL`, `SUPPORT_EMAIL`
- `PRICING_PRO_MONTHLY_USD`
- `FEATURE_FLAGS` (for gated features like FC25 stats)

## Database migration checklist

Offside runs Mongo migrations at startup (see `migrations/`), but releases should still follow a checklist:

- [ ] Confirm `MONGODB_URI` points at the intended cluster (staging vs prod).
- [ ] Ensure you have a recent backup/snapshot before deploying changes that mutate schema.
- [ ] If a release introduces a new record type/collection, add indexes in migrations and verify they are applied.
- [ ] After deploy, check logs for a successful migration run (schema version bump).
- [ ] Validate the critical flows write/read the expected collections (Roster/Recruit/Club/Tournament).

## Rollback playbook

When a release is broken, prioritize restoring service quickly.

### 1) Roll back the deploy

Choose the option your hosting platform supports:

- **Heroku** (typical):
  - Roll back to a previous release via the Heroku dashboard, or run `heroku releases:rollback -a <app>`.
- **Git-based deploys**
  - Revert the offending commit(s) on `main`, then redeploy.

### 2) Roll back config changes

If the break was caused by env var updates:

- Revert the config vars to the last known-good values.
- Confirm `DASHBOARD_REDIRECT_URI` still matches the deployed domain.

### 3) Roll back database changes (if needed)

MongoDB changes are not always reversible automatically. Options:

- Restore from the most recent backup/snapshot (fastest path if the schema change is disruptive).
- Manually repair:
  - Remove/ignore newly introduced fields.
  - Recreate dropped indexes/collections.
  - Re-run the previous version to repopulate derived data.

### 4) Re-verify

- Re-run the smoke test checklist (`docs/qa-checklist.md`).
- Confirm the dashboard works (login, select guild, open settings).
- Confirm portals/listings are posting correctly in Discord.
