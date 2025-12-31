# Disaster Recovery Checklist

This checklist covers MongoDB backups/restores, Stripe event replay, and credential rotation.
See `docs/data-lifecycle.md` for retention guidance and baseline backup policy.

## MongoDB backup and restore

### Managed Mongo (Atlas or equivalent)

- Enable continuous backups or point-in-time restore.
- Confirm retention aligns with your RPO/RTO targets.
- Limit database access (IP allowlist/private networking) and rotate DB credentials regularly.

### Self-managed Mongo (`mongodump`)

Backup (single archive, gzip):

```bash
mongodump --uri "$MONGODB_URI" --archive=backup.archive.gz --gzip
```

Restore into a new database/cluster:

```bash
mongorestore --uri "$MONGODB_URI" --archive=backup.archive.gz --gzip --drop
```

Post-restore steps:
- Run migrations: `python -m scripts.migrate`
- Run smoke tests: `pytest -q tests/e2e/test_dashboard_smoke.py`

### Dev/stage verification

- Restore the latest backup into a temporary staging DB.
- Point staging at the restored DB and run the smoke tests above.
- Record restore time (RTO) and the backup timestamp (RPO).

## Stripe event replay (entitlements resync)

Use the Stripe dashboard or CLI to resend events to the webhook endpoint.

Stripe CLI flow:

```bash
stripe login
stripe events resend evt_123 --webhook-endpoint we_123
```

Checklist:
- Identify the affected customer/subscription in Stripe.
- Replay `checkout.session.completed` and `customer.subscription.*` events if needed.
- Confirm `guild_subscriptions` reflects the correct plan/status in Mongo.
- Check the audit log for `stripe.*` entries.

## Credential rotation

Rotate credentials whenever compromise is suspected or on a routine schedule.

- Discord bot token:
  - Reset the token in the Discord Developer Portal.
  - Update `DISCORD_TOKEN` and restart the bot.
- Discord OAuth client secret:
  - Reset `DISCORD_CLIENT_SECRET` in the Developer Portal.
  - Update `DASHBOARD_REDIRECT_URI` if the domain changed.
  - Restart the web dashboard.
- Stripe secrets:
  - Rotate `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`.
  - Update config vars and restart the web dashboard.
- Verify no secrets leaked:
  - Run `gitleaks detect --source . --redact --no-banner`.

## DR validation checklist

- [ ] Backup exists and is restorable in dev/stage.
- [ ] Restore completes and smoke tests pass.
- [ ] Stripe event replay re-syncs entitlements successfully.
- [ ] Rotated credentials are deployed and old tokens are revoked.
