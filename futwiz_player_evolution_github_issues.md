# GitHub Issue Backlog — Offside Discord Bot

This file tracks planned GitHub issues for this repository (Offside Discord Bot).

---

## Epic 1 — Dashboards & Permissions

### Issue 1.1 — Club Managers portal (coach management) ✅
**Goal:** Move coach-management tools out of the Staff Portal and into a dedicated Club Managers dashboard.

**Sub-issues**
- [x] Add `club-managers-portal` channel under `--OFFSIDE DASHBOARD--` via `/setup_channels` (`channel_manager_portal_id`).
- [x] Post a Club Managers instruction embed + control panel embed on startup.
- [x] Add manager actions:
  - [x] Set Coach Tier (Coach / Coach Premium / Coach Premium+) and sync roster cap.
  - [x] Unlock roster (modal) for edits after rejection.
  - [x] Refresh Premium Coaches listing embed.
  - [x] Delete roster (admin-only; modal) and refresh premium listing when needed.
- [x] Update Staff Portal control panel to remove coach-management buttons and link to the Club Managers portal.

**Acceptance criteria**
- Club Managers channel exists after `/setup_channels` and has an up-to-date dashboard.
- Staff Portal no longer contains coach-management controls; it only links to Club Managers portal.

---

### Issue 1.2 — Portal UX polish (consistency + clarity)
**Goal:** Make all portals consistent in layout, copy, and button naming.

**Sub-issues**
- [ ] Standardize intro embed format (purpose, who should use it, key rules).
- [ ] Standardize control panel embed format (sections map 1:1 to buttons).
- [ ] Add “Last refreshed” footers to all portal/control embeds.
- [ ] Add a “Repost this portal” action (staff-only) for each portal channel.

---

## Epic 2 — Listing Channels UX (Rich Embeds)

### Issue 2.1 — Roster Listing as rich embed ✅
**Goal:** Approved rosters should post as readable embeds (not plain text) in roster listing channels.

**Sub-issues**
- [x] Replace roster listing text post with embed (team, coach, tournament, players, openings, practice times).
- [x] Disable all mentions in listing posts (`AllowedMentions.none()`).

---

### Issue 2.2 — Premium Coaches listing improvements
**Goal:** Keep the Premium Coaches channel “high signal” and easy to scan.

**Sub-issues**
- [ ] Add “Last updated” timestamp to the embed.
- [ ] Add optional pin behavior for the Premium Coaches embed (store pinned message id per guild).
- [ ] Add filters/sections in the embed (Premium vs Premium+).
- [ ] Add a manager-only “Force rebuild” button that also cleans older bot messages.

---

### Issue 2.3 — Recruit/Club listing embed polish
**Goal:** Improve readability and consistency across listing embeds.

**Sub-issues**
- [ ] Add consistent field ordering + icons.
- [ ] Add “Updated” footer for club ads (similar to recruit profiles).
- [ ] Clamp long text more gracefully (notes/description) and provide “See more” instructions.

---

## Epic 3 — Coach Tier & Roster Cap Lifecycle

### Issue 3.1 — Coach tier changes and existing rosters
**Goal:** Tier upgrades/downgrades should not cause confusing cap mismatches.

**Sub-issues**
- [ ] When a coach tier changes, optionally sync caps for all rosters in the active cycle (manager tool).
- [ ] Prevent cap downgrades below current roster size (warn + require manual removal first).
- [ ] Add audit trail events for tier changes and cap syncs.

---

## Epic 4 — Quality / Maintenance

### Issue 4.1 — Docs + onboarding updates
**Goal:** Keep docs current as portals/channels evolve.

**Sub-issues**
- [ ] Update `docs/commands.md` and README whenever new portals are added.
- [ ] Add a short “Server setup checklist” doc for operators.

