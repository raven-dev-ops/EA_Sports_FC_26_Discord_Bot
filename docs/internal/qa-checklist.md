# QA Checklist (Staging Guild)

See also: `docs/public/server-setup-checklist.md`

## Setup
- Start bot with `TEST_MODE=true`
- Confirm auto-setup cleans up legacy Offside Discord channels/categories
- Verify roles are synced: Coach, Coach+, Club Manager, Club Manager+, League Staff, League Owner, Free Agent, Pro Player

## Test Mode Routing
- With `TEST_MODE=true`, verify only role automation + logs are active (no channel routing).

## Accessibility spot checks
- Keyboard-only: use Tab to reach topbar links, server picker, and primary action buttons.
- Confirm focus ring is visible on links, buttons, and form fields.
- In the dashboard sidebar, active item should announce as the current page.
- Commands page: search + filters update with screen reader announcements.

## Web Recruiting
- Register/edit profiles in the web app and confirm data persists.
- Verify availability and listings render on the website.

## FC25 Stats Link/Unlink (If enabled)
- Ensure feature flag `fc25_stats` is enabled and guild override allows it
- Link/unlink via the web app and confirm snapshots update.

## Web Rosters
- Create rosters in the web app and confirm caps match role tiers.
- Confirm staff review decisions are logged and persisted.
