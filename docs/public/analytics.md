# Analytics

Offside can emit funnel analytics events to PostHog. Analytics is disabled by
default and only enabled when `POSTHOG_API_KEY` is set. You can override the
host with `POSTHOG_HOST` (defaults to `https://app.posthog.com`).

## Event schema

Events are emitted with a `path` property and additional properties when
available.

- `cta_click` (properties: `cta` = `add_to_discord` or `open_dashboard`, `guild_id` when known)
- `login_success` (properties: `guild_count`, `owner_guild_count`, `installed_guild_id` when known)
- `connect_discord_success` (properties: `flow`)
- `guild_selected` (properties: `guild_id`)
- `setup_completed` (properties: `guild_id`, `plan`)
- `upgrade_click` (properties: `guild_id`, `source`, `section` when known)
- `upgrade_success` (properties: `guild_id`)

## Configuration

- `POSTHOG_API_KEY`: enable analytics when set.
- `POSTHOG_HOST`: optional override for the PostHog instance host.
