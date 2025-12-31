# Monitoring

## Web health

- `GET /health` returns `200` when the web process is alive.

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

## Logging hygiene

- Do not log secrets (tokens, auth headers, cookies) or PII (emails, raw payloads).
- Use `utils.redaction.scrub` / `utils.redaction.redact_text` when logging untrusted data.
- Include structured fields when possible: `request_id`, `guild_id`, `user_id`.
- Optional check: `python -m scripts.check_log_hygiene` flags logging calls that include sensitive variable names.
