# Changelog

All notable changes to this project will be documented in this file.

## [0.2.9] - 2025-12-29

### Added
- Input sanitization helper `sanitize_text` applied across tournament commands to trim/cap fields.
- Tournament tests for bracket preview, idempotent bracket generation, and match concurrency guards.
- New unit tests for validation helpers; added tournament service test coverage.

### Changed
- Bracket generation is idempotent (reuses existing matches instead of duplicating).
- Match report/confirm concurrency now tested with `expected_updated_at`.

## [0.2.8] - 2025-12-29

### Added
- `/config_view` and `/config_set` (staff-only) to inspect/override safe runtime settings.
- `/tournament_bracket_preview` dry-run pairing preview (no DB writes) plus name-aware bracket/advance embeds.
- `/rules_template` starter rules generator and categorized `/help` with consistent embed styling via `utils.embeds`.
- Centralized embed colors (info/success/warning/error) for consistent UX.

### Changed
- Match report/confirm uses optimistic concurrency via `expected_updated_at` to avoid clobbering concurrent edits.
- Bracket and advance responses now use embeds and team names instead of raw IDs.

## [0.2.7] - 2025-12-29

### Added
- Privacy policy retention/deletion notes and deployment hardening guidance in README/CONTRIBUTING.
- VERSION file to track releases.
- Tournament channel routing stores message references for later edits; roster/tournament flows guarded with optimistic status checks.

## [0.2.0] - 2025-12-28

### Added
- Test mode routing to the Discord test channel with log forwarding.
- `/dev_on` and `/dev_off` commands for runtime test-mode toggling.
- Multi-tournament cycle selection for roster creation.
- Staff action audit trail for approve/reject/unlock events.
- Optional Google Sheets ban list checks.

### Changed
- `/roster` opens the roster creation modal.
- Staff review button responses are ephemeral while the staff post is updated.

## [0.2.1] - 2025-12-28

### Fixed
- Avoided pymongo `Collection` truthiness checks that crash `unlock_roster`.
- Normalized MongoDB database names with invalid characters (e.g., spaces).

## [0.2.2] - 2025-12-29

### Added
- Auto-posting admin/staff and coach portals to their configured channels; portals include action buttons.
- Admin portal unlock and delete roster modals; roster delete also removes submission messages.
- Coach team name edit modal; staff decision reasons with coach DM notification; minimum 8 players required to submit.
- Roster approvals repost to roster portal; submissions stay in staff portal.

### Changed
- Routing uses new channel envs: `CHANNEL_STAFF_PORTAL_ID` (staff portal), `CHANNEL_COACH_PORTAL_ID` (coach portal), `CHANNEL_ROSTER_PORTAL_ID` (approved roster embeds).
- Reduced Discord rate-limit risk by spacing portal posts on startup.

## [0.2.3] - 2025-12-29

### Fixed
- Approved rosters now post only to the roster portal; staff review messages are removed after a decision to avoid duplicates in the admin channel.
- Unlocked rosters clean up stale submission records, allowing resubmission without "already submitted" errors.

### Added
- Test suite coverage for submission lifecycle and roster status transitions; `python -m pytest` runs the suite.

## [0.2.4] - 2025-12-29

### Removed
- Temporary member export helper `scripts/export_members.py` (one-time use for capturing the guild roster to MongoDB).

## [0.2.5] - 2025-12-29

### Added
- Dockerfile and .dockerignore for containerized runs; README/CONTRIBUTING updated with Docker usage.
- Contributor guide with local setup, tooling, and secrets guidance.
- CI/dev tooling configs: Ruff/Mypy settings, pre-commit config, dev requirements.
- Structured logging config with env-based log level; `.env.example` for config template.

## [0.2.6] - 2025-12-29

### Added
- Tournament scaffold: slash commands for tournament create/state/register, bracket generation, and basic match report/confirm; Mongo-backed storage for tournaments, participants, matches.
- README updated with tournament commands.

## [0.1.0] - 2025-12-28

### Added
- Initial roster workflow with staff review and unlock controls.
- MongoDB persistence, roster validation, and tests.
