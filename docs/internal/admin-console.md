# Admin console

The admin console is an internal dashboard for the SaaS owner. It is gated by an allowlist.

## Configuration

- Set `ADMIN_DISCORD_IDS` to a comma-separated list of Discord user IDs.
- Admins must sign in via the dashboard OAuth flow.

Example:

```
ADMIN_DISCORD_IDS=123456789012345678,987654321098765432
```

## Capabilities

- View subscriptions (plan, status, period end).
- Inspect recent Stripe webhook events and dead letters.
- Review ops tasks across guilds.
- Manually resync Stripe subscription data to entitlements.

## Safety

- Admin actions are audited (category: `admin`).
- Stripe resync requires CSRF and uses the allowlist check.
