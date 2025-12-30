# Server Setup Checklist

Use this checklist when adding Offside Bot to a new Discord server.

## 1) Invite permissions

Invite the bot with:
- Scopes: `bot`, `applications.commands`
- Bot permissions (recommended):
  - `Manage Channels` (auto-creates the Offside categories/channels)
  - `Manage Roles` (auto-creates coach tier roles and assigns tiers)
  - `Manage Messages` (optional; used for portal cleanup, pin/unpin Premium Coaches)
  - `Read Message History`, `Send Messages`, `Embed Links`, `Attach Files`

Role hierarchy:
- Ensure the bot's top role is **above** the coach tier roles it needs to manage.

## 2) Configure MongoDB (required)

Auto-setup and per-guild IDs require MongoDB:
- `MONGODB_URI`
- `MONGODB_DB_NAME`
- `MONGODB_COLLECTION`

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
- `club-managers-portal`
- `club-portal`
- `coach-portal`
- `recruit-portal`

Report channels:
- `roster-listing`
- `recruit-listing`
- `club-listing`
- `premium-coaches`

Roles:
- `Coach`
- `Coach Premium`
- `Coach Premium+`

## 6) Permissions intent (recommended)

This is the default intent for auto-created channels:

- `staff-portal`: staff-only (staff can post)
- `club-managers-portal`: staff-only (staff can post)
- `coach-portal`: coaches-only (read-only; use buttons)
- `recruit-portal`, `club-portal`: public read-only (use buttons)
- `roster-listing`, `recruit-listing`, `club-listing`, `premium-coaches`: public read-only (bot-managed listings)
- `staff-monitor`: staff-only (test mode only)

Notes:
- Listing channels include a pinned bot "About" embed explaining what appears there.
- Staff can moderate listing channels; chat is intentionally disabled to keep them clean.

## 7) Operational buttons

From `club-managers-portal`:
- Use **Sync Caps (Active Cycle)** after changing coach roles manually.
- Use **Toggle Premium Pin** to pin/unpin the Premium Coaches embed (requires permissions).
- Use **Force Rebuild Premium** if the premium channel has stale bot messages.

From any portal channel:
- Use **Repost Portal (staff)** to clean up and repost the portal messages.

From `staff-portal`:
- Use **Verify Setup (staff)** to re-run auto-setup for the current guild and see an action summary.
