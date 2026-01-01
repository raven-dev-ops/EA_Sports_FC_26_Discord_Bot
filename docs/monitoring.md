# Monitoring

## Production endpoints

- ![Web health](https://img.shields.io/website?url=https%3A%2F%2Fofficial-offside-bot-214b205fba71.herokuapp.com%2Fhealth&label=web&up_message=up&down_message=down)
- ![DB + worker](https://img.shields.io/website?url=https%3A%2F%2Fofficial-offside-bot-214b205fba71.herokuapp.com%2Fready&label=db%2Bworker&up_message=passing&down_message=failing)

## Web health

- `GET /health` returns `200` when the web process is alive.
- `GET /healthz` is an alias for load balancers and uptime checks.

## Readiness (DB + worker)

- `GET /ready` returns:
  - `200` when MongoDB is reachable **and** the bot worker heartbeat is fresh.
  - `503` when MongoDB is down, heartbeat is missing, or heartbeat is stale.

The worker heartbeat freshness threshold is controlled by:

- `WORKER_HEARTBEAT_MAX_AGE_SECONDS` (default: `120`)

## Bot worker heartbeat

The bot worker writes a heartbeat every ~30 seconds to MongoDB:

- DB: the global DB (same one used for dashboard sessions)
- Collection: `worker_heartbeats`
- Document id: `bot`

`/ready` reads this heartbeat to detect partial outages where the web is up but the bot worker is down.

## Dashboards and alerts

Suggested log-derived metrics (Grafana/Loki/Datadog):
- Web requests: `event=http_request` with `status` and `duration_ms` for req/s, error rate, and latency.
- Bot commands: `command metric name=...` from `utils.metrics` for success/failure rates.
- Discord API errors: `event=discord_api_error` with `operation` + `status`.
- Stripe webhooks: `stripe_webhook_processed` / `stripe_webhook_failed` / `stripe_webhook_in_progress`.

Dashboard panels (baseline):
- Web: requests per minute, 95p latency, 4xx/5xx error rate.
- Bot: command success rate, command latency buckets.
- Billing: Stripe webhook failures and dead letters per hour.
- Discord: API error rate by operation and status code.

Alert starters (link to runbooks):
- Web 5xx > 2% for 5 minutes (see `docs/qa-checklist.md`).
- Stripe webhook failures > 0 in 5 minutes (see `docs/billing.md`).
- Discord API errors spike (see `docs/release-playbook.md`).
- Worker heartbeat stale (see `docs/monitoring.md` + `docs/release-playbook.md`).

## Logging hygiene

- Do not log secrets (tokens, auth headers, cookies) or PII (emails, raw payloads).
- Use `utils.redaction.scrub` / `utils.redaction.redact_text` when logging untrusted data.
- Include structured fields when possible: `request_id`, `interaction_id`, `guild_id`, `user_id`.
- Optional check: `python -m scripts.check_log_hygiene` flags logging calls that include sensitive variable names.
