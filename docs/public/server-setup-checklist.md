# Server Setup Checklist

Use this checklist when adding Offside Bot to a new Discord server.

## 1) Invite permissions

Invite the bot with:
- Scopes: `bot`, `applications.commands`
- Bot permissions (recommended):
  - `Manage Channels` (auto-creates the Offside categories/channels)
  - `Manage Roles` (auto-creates Offside roles and assigns tiers)
  - `Manage Messages` (optional; used for portal cleanup, pin/unpin Pro coaches)
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
2. Verify the bot creates `staff-monitor` under `--OFFSIDE REPORTS--`
3. Confirm all portal posts, listing posts, and forwarded logs route to `staff-monitor`
4. Flip to `TEST_MODE=false` and restart
5. Confirm `staff-monitor` is deleted (if bot-managed) and routing uses the normal channels

## 5) Verify auto-setup output

Categories:
- `--OFFSIDE DASHBOARD--`
- `--OFFSIDE REPORTS--`

Dashboard channels:
- `staff-portal`
- `managers-portal` (club managers portal)
- `coach-portal`
- `recruit-portal`

Report channels:
- `recruitment-boards`
- `club-listing`
- `pro-coaches`

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

This is the default intent for auto-created channels:

- `staff-portal`: staff-only (staff can post)
- `managers-portal`: staff-only (staff can post; club managers controls live here)
- `coach-portal`: coaches-only (read-only; use buttons)
- `recruit-portal`: public read-only (use buttons)
- `recruitment-boards`, `club-listing`, `pro-coaches`: public read-only (bot-managed listings)
- `staff-monitor`: staff-only (test mode only)

Notes:
- Listing channels include a pinned bot "About" embed explaining what appears there.
- `club-listing` includes approved rosters and club ads.
- Staff can moderate listing channels; chat is intentionally disabled to keep them clean.

## 7) Operational buttons

From `managers-portal`:
- Use **Sync Caps (Active Cycle)** after changing coach roles manually.
- Use **Toggle Pro Pin** to pin/unpin the Pro coaches embed (requires permissions).
- Use **Force Rebuild Pro** if the pro coaches channel has stale bot messages.

From any portal channel:
- Use **Repost Portal (staff)** to clean up and repost the portal messages.

From `staff-portal`:
- Use **Verify Setup (staff)** to re-run auto-setup for the current guild and see an action summary.
