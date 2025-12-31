# Data lifecycle (backups, retention, deletion)

This project stores guild data in MongoDB. For multi-tenant production, the recommended configuration is **per-guild databases** (`MONGODB_PER_GUILD_DB=true`) so each Discord server can be isolated and safely deleted.

## Backups

Recommended backup strategy (production):

- **Daily backups** of the MongoDB cluster (or the full set of databases).
- **Retention**: keep at least 7 daily + 4 weekly + 6 monthly (adjust for your risk tolerance).
- **Verify restores** regularly (at least monthly) by restoring to a temporary environment and running the smoke test suite.

### Atlas / managed MongoDB

If you’re using MongoDB Atlas or another managed provider:

- Enable continuous backups / point-in-time restore if available.
- Ensure backup retention matches your compliance needs.
- Restrict DB access (IP allowlists / private networking) and rotate credentials.

### Self-managed MongoDB (`mongodump`)

Example (single archive, gzip):

```bash
mongodump --uri "$MONGODB_URI" --archive=backup.archive.gz --gzip
```

Store the archive in durable storage (e.g., S3) and encrypt it at rest.

## Restore procedure

High-level restore runbook:

1. Restore the backup into a **new** MongoDB instance/cluster (preferred) or the existing one.
2. Point the app at the restored DB (`MONGODB_URI` + `MONGODB_DB_NAME` / `MONGODB_PER_GUILD_DB`).
3. Run migrations: `python -m scripts.migrate`.
4. Run tests/smoke checks (see `docs/release-playbook.md`).

## Retention policy (logs / audit)

Audit-style collections use a TTL index on `expires_at`:

- `audit_events`
- `roster_audits`
- `club_ad_audits`

Configure retention with:

- `AUDIT_LOG_RETENTION_DAYS` (default: `180`)
- `OPS_TASKS_RETENTION_DAYS` (default: `30`; ops history / background jobs)

Notes:

- Existing docs written before this policy may not have `expires_at` (they won’t auto-expire until backfilled).
- Decreasing retention affects **new** documents immediately; existing documents keep their precomputed `expires_at`.

## Guild data deletion (GDPR-style request)

From the web dashboard:

1. Go to `Ops` for the guild.
2. Under **Data deletion**, type `DELETE <guild_id>` and submit.
3. The bot schedules an ops task that irreversibly deletes the guild’s stored data after the grace window.

Configuration:

- `GUILD_DATA_DELETE_GRACE_HOURS` (default: `24`)

Implementation details:

- Requires `MONGODB_PER_GUILD_DB=true`.
- Deletes global cross-guild records where applicable (e.g., subscription + Stripe webhook events).
- Drops the guild database to remove all per-guild collections irreversibly.

## Export guild data (optional)

Use the export script to capture a snapshot before deletion:

```bash
python -m scripts.export_guild_data --guild-id 123456789012345678
```

Outputs NDJSON files per collection plus `manifest.json` into `./exports/`.
