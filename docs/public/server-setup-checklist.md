# Server Setup Checklist

Use this checklist when adding Offside Bot to a new Discord server.

## 1) Invite permissions

Invite the bot with:
- Scopes: `bot`, `applications.commands`
- Bot permissions (recommended):
  - `Manage Channels` (used once to clean up retired Offside channels)
  - `Manage Roles` (auto-creates Offside roles and assigns tiers)
  - `Read Message History`, `Send Messages`, `Embed Links`, `Attach Files`

Role hierarchy:
- Ensure the bot's top role is **above** the Offside roles it needs to manage.

## 2) Configure MongoDB (required)

Auto-setup and per-guild IDs require MongoDB:
- `MONGODB_URI`
- `MONGODB_DB_NAME` (optional; defaults to `OffsideDiscordBot`)
- `MONGODB_COLLECTION` (optional; legacy single-collection mode, e.g., `Isaac_Elera`)
- `MONGODB_PER_GUILD_DB` (optional; when true, each guild uses its own MongoDB database)
- `MONGODB_GUILD_DB_PREFIX` (optional; prefix for per-guild database names)

## 3) Configure staff access (recommended)

- Set `STAFF_ROLE_IDS` (comma-separated) so staff checks are consistent across servers.
- If unset, staff is inferred via Discord permissions (admin/manage server).

## 4) Test mode (staging)

Recommended staging flow:
1. Start with `TEST_MODE=true`
2. Confirm the bot is online and roles are synced
3. Flip to `TEST_MODE=false` and restart when ready

## 5) Verify auto-setup output

Discord channels:
- Offside no longer creates dashboard/report channels; all workflows live in the web app.

Roles:
- `Coach`
- `Coach+` (Pro)
- `Club Manager` (Pro)
- `Club Manager+` (Pro)
- `League Staff`
- `League Owner`
- `Free Agent`
- `Pro Player`

## 6) Permissions intent (recommended)

Offside does not manage Discord channels anymore. All dashboards and listings are served in the web app.

## 7) Operational buttons

Operational actions now live in the web dashboard (Ops + Settings pages).
