# Offside Discord Layout - GitHub Issues (Project-Tailored)

This backlog is specific to **Offside Bot** and its **auto-provisioned Discord layout**.
Imported into GitHub as issues `#137`-`#140` and completed in `v0.2.19`.

Auto-setup sources:
- `services/channel_setup_service.py` (categories/channels + permissions)
- `services/role_setup_service.py` (coach roles)
- `offside_bot/__main__.py` (`guild_join` / startup auto-deploy)

Expected auto-created layout:
- Categories:
  - `--OFFSIDE DASHBOARD--`
  - `--OFFSIDE REPORTS--`
- Dashboard channels (in order):
  - `staff-portal` (staff-only)
  - `club-managers-portal` (staff-only)
  - `club-portal` (public read-only)
  - `coach-portal` (**coaches-only**, read-only)
  - `recruit-portal` (public read-only)
- Report channels (in order; plus conditional test-mode sink):
  - `staff-monitor` (staff-only; **only created when `TEST_MODE=true`**, deleted when test mode is off)
  - `roster-listing` (public read-only)
  - `recruit-listing` (public read-only)
  - `club-listing` (public read-only)
  - `premium-coaches` (public read-only; bot-managed report)
- Roles:
  - `Coach`
  - `Coach Premium`
  - `Coach Premium+`

---

## Issue L1 - Harden channel permissions (auto-setup)
**Labels:** `priority:p0` `area:discord` `area:permissions` `type:chore`

**Goal**
Make auto-created channels consistently **read-only** (no chat), and ensure `coach-portal` is **not visible** to non-coaches.

**Definition of Done**
- `coach-portal` is visible to `Coach`/`Coach Premium`/`Coach Premium+` + staff only.
- Public portal channels (`club-portal`, `recruit-portal`) are read-only for everyone except the bot.
- Listing channels (`roster-listing`, `recruit-listing`, `club-listing`, `premium-coaches`) are read-only (including for staff) to keep them clean; staff can still moderate.
- Staff-only channels (`staff-portal`, `club-managers-portal`, `staff-monitor`) remain hidden from non-staff.
- Auto-setup applies/repairs overwrites when channels already exist.

### Subtasks
- [ ] Reorder auto-setup to ensure roles exist before channels (so coach-only overwrites can be applied on first deploy).
- [ ] Add dedicated overwrite templates:
  - [ ] staff-only
  - [ ] public portal (read-only)
  - [ ] coach portal (coach + staff read-only)
  - [ ] listing channels (read-only + staff moderation)
- [ ] Add/adjust docs describing the permission matrix.

---

## Issue L2 - Add a staff "Verify Setup" action (UX)
**Labels:** `priority:p1` `area:discord` `area:interactions` `ux` `type:feature`

**Goal**
Give staff a one-click way to verify (and optionally repair) roles/channels/permissions for the current guild.

**Definition of Done**
- A staff-only button exists in `staff-portal` (Admin/Staff portal).
- On click, the bot reports:
  - Missing permissions (`Manage Channels`, `Manage Roles`, `Manage Messages` where relevant)
  - Any channels/roles it created/reused/updated (same action list style as auto-setup)
  - Test-mode sink status (`staff-monitor` present/absent and whether bot-managed)
- The action is safe in prod (no destructive changes beyond the existing "ensure" behavior).

### Subtasks
- [ ] Add the button + handler (staff-only).
- [ ] Reuse the existing auto-setup ensure functions and return the action summary as an embed.

---

## Issue L3 - Listing channel "About" embeds (pin + style)
**Labels:** `priority:p2` `area:discord` `area:interactions` `ux` `type:enhancement`

**Goal**
Keep listing channels self-explanatory and clean with a pinned "About this channel" embed.

**Definition of Done**
- Each listing channel has a pinned bot embed explaining:
  - What appears there
  - That chat is disabled
  - Where to go for actions (portal channels)
- Posting is idempotent (no repeated spam on restarts).

### Subtasks
- [ ] Add a small helper to upsert+pin these instruction embeds.
- [ ] Wire it into startup posting (after channels are ensured).

---

## Issue L4 - Docs + version bump for layout changes
**Labels:** `priority:p2` `docs` `area:docs` `type:chore`

**Goal**
Ensure docs match the new permissions/layout behavior.

**Definition of Done**
- `README.md` and `docs/server-setup-checklist.md` include the current layout + permission intent.
- `CHANGELOG.md` + `VERSION` updated.
