# Changelog

All notable changes to this project will be documented in this file.

## [0.2.12] - 2025-12-29

### Added
- Global permission guard for staff-facing cogs and friendly denial messaging.
- Asyncio exception handler with error IDs for interaction responses.
- CI secret scanning via gitleaks with expanded `.gitignore` and security guidance.
- Startup config summary logging (non-secret) to verify env wiring quickly.
- Structured command logging (guild/channel/user/command) and command registration script (`scripts/register_commands.py`) for guild/global sync.
- Discord HTTP helpers now honor `retry_after` with bounded exponential backoff and timeouts; graceful shutdown closes Mongo client.
- Command registry validation (duplicate name/description checks) and standalone migration runner with mongomock-tested schema versioning.
- In-memory channel caching to reduce Discord API calls.
- Shared command catalog powering `/help` and generated docs (`docs/commands.md`) via `scripts.generate_docs` with CI check.
- Command metrics (duration/status) logged per command for basic observability.
- Per-guild config overrides with staff commands to view/set; mass-mention guard on inputs and safer allowed mentions on sends.
- Dependency hygiene: dependabot config, pip-audit in CI, and release workflow builds artifacts on tags.
- Optional scheduler scaffold with feature-flagged jobs (`metrics_log`) and dev hot-reload/watch + profiling scripts for DX.

## [0.2.11] - 2025-12-29

### Added
- Staff-only guard for all tournament/config commands using a shared permissions helper.
- Roster submission identity checks (min 8, no duplicate players, required gamertag/EA ID) before locking.
- `/tournament_stats` leaderboard (wins/loss/GD) and `/tournament_dashboard` quick-reference embed for staff.
- Timezone formatter helper and guidance for rendering timestamps.
- Integration test for tournament dashboard and an E2E validation guide.

### Changed
- Tournament flows consistently sanitize input and reuse idempotent bracket generation.

## [0.2.10] - 2025-12-29

### Added
- Input sanitization helper `sanitize_text` applied across tournament commands to trim/cap fields.
- Tournament tests for bracket preview, idempotent bracket generation, and match concurrency guards.
- New unit tests for validation helpers; added tournament service test coverage.
- Startup migrations runner with schema version tracking; recovery job to heal stuck rosters and prune orphan submission records.

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
