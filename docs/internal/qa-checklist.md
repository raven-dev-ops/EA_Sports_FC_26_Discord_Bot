# QA Checklist (Staging Guild)

See also: `docs/public/server-setup-checklist.md`

## Setup
- Start bot with `TEST_MODE=true`
- Confirm auto-setup creates `--OFFSIDE DASHBOARD--` and `--OFFSIDE REPORTS--`
- Verify portals are posted:
  - `staff-portal`, `club-managers-portal`, `club-portal`, `coach-portal`, `recruit-portal`
- Verify reports channels exist:
  - `staff-monitor` (test mode only), `roster-listing`, `recruitment-boards`, `club-listing`, `pro-coaches`
- With `TEST_MODE=false`, confirm `coach-portal` is only visible to coaches + staff
- Confirm listing channels have a pinned "About" embed (instructions + no-chat policy)
- In `staff-portal`, run **Verify Setup (staff)** and confirm the report is clean

## Test Mode Routing
- With `TEST_MODE=true`, confirm all dashboards/posts/logs route to `staff-monitor`
- Restart with `TEST_MODE=false`, confirm `staff-monitor` is deleted and routing uses normal channels

## Accessibility spot checks
- Keyboard-only: use Tab to reach topbar links, server picker, and primary action buttons.
- Confirm focus ring is visible on links, buttons, and form fields.
- In the dashboard sidebar, active item should announce as the current page.
- Commands page: search + filters update with screen reader announcements.

## Recruitment Portal
- Register profile via `recruit-portal`:
  - Submit the 2-step modal
  - If availability is not set, confirm the bot instructs you to set it before publishing
- Set availability via `Availability`:
  - Confirm listing is posted/updated in `recruitment-boards`
  - Confirm staff copy is posted/updated (staff portal channel in production; staff-monitor in test mode)
- Edit profile:
  - Confirm existing listing message is edited (not duplicated)
  - Confirm rapid edits hit the cooldown message
- Unregister:
  - Confirm DB record deleted and posts removed when possible

## FC25 Stats Link/Unlink (If enabled)
- Ensure feature flag `fc25_stats` is enabled and guild override allows it
- Link:
  - Use `Link FC25 Stats` button in `recruit-portal`
  - Confirm verification checks member name and saves a snapshot
- Confirm recruitment boards show the verified stats section
  - Confirm staff log message includes user mention + platform + club ID + status
- Unlink:
  - Use `Unlink FC25 Stats`
  - Confirm verified stats section is removed from the listing
  - Confirm staff log message is emitted

## Club Portal
- Register club ad via `club-portal`:
  - Confirm min description length is enforced
  - Confirm listing is posted/updated in `club-listing`
- Edit ad:
  - Confirm existing listing message is edited (not duplicated)
  - Confirm rapid edits hit the cooldown message
- Unregister:
  - Confirm DB record deleted and posts removed when possible

## Coach Portal / Rosters
- Create roster:
  - Confirm roster dashboard appears and cap is correct for the coach role
- Add player (manual):
  - Confirm ban list check is enforced
  - Confirm cap checks work
- Add from player pool:
  - Confirm filter selects work (position/archetype/server)
  - Confirm results are paginated
  - Selecting a player opens add-player modal with Discord ID prefilled
- Submit roster:
  - Confirm staff review flow posts to staff portal and decisions are logged
