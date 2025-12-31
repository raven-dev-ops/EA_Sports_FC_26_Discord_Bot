# Environments (dev, staging, production)

Use separate configs for each environment so staging cannot touch production data.

## APP_ENV

Set `APP_ENV` to one of:
- `development`
- `staging`
- `production`

This value is used to gate billing keys and to document where a deployment is running.

## Discord app separation

Use separate Discord applications for staging and production:
- `DISCORD_TOKEN`
- `DISCORD_APPLICATION_ID`
- `DISCORD_CLIENT_SECRET`
- `DASHBOARD_REDIRECT_URI`

Ensure each app has its own redirect URI and bot token to prevent cross-environment traffic.

## Stripe separation

Use `STRIPE_MODE` to enforce test vs live keys:
- `STRIPE_MODE=test` for development and staging (use `sk_test_*` keys)
- `STRIPE_MODE=live` for production (use `sk_live_*` keys)

The dashboard refuses to start if a live key is configured outside production.

## Recommended staging defaults

- `TEST_MODE=true`
- `APP_ENV=staging`
- `STRIPE_MODE=test`
- Use a staging MongoDB cluster or database prefix.
