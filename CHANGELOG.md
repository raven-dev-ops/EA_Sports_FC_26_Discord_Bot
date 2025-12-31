# Changelog

All notable changes to this project will be documented in this file.

## [0.2.47] - 2025-12-31

### Changed
- Web: `/` is always the public landing page; dashboard home moved to `/app` (requires login, supports `next=` redirects).

## [0.2.46] - 2025-12-31

### Added
- Web: minimum branding pack (logo/favicon/OG image) under `offside_bot/static/brand/` and wired into templates.

## [0.2.45] - 2025-12-31

### Added
- QA: E2E dashboard smoke test (`tests/e2e/test_dashboard_smoke.py`) for critical web flows.

## [0.2.44] - 2025-12-31

### Docs
- Release checklist + env/migration checklist + rollback plan: `docs/release-playbook.md`.

## [0.2.43] - 2025-12-31

### Added
- Web: `/features` page with module breakdowns and a “Compare plans” CTA.

## [0.2.42] - 2025-12-31

### Added
- Web: `/commands` page generated from `docs/commands.md` with client-side search + category filters.

## [0.2.41] - 2025-12-31

### Added
- Web: dark theme styling (Discord-adjacent) across landing/pricing/dashboard pages.
- Web: responsive app shell with a mobile hamburger menu for sidebar navigation.

## [0.2.40] - 2025-12-30

### Added
- Dashboard: protected pages now redirect to `/login?next=...` so you return to the page you originally requested after Discord auth.
- Dashboard: friendly OAuth callback errors (cancelled login, expired state, token/API failures) with a retry link.

## [0.2.39] - 2025-12-30

### Added
- Web: improved public support page (`/support`) with bug/feature links and optional support Discord/email config.
- GitHub: enhanced issue templates with version/environment prompts and cross-links.

## [0.2.38] - 2025-12-30

### Docs
- `.env.example`: added `PRICING_PRO_MONTHLY_USD` for marketing pricing display.

## [0.2.37] - 2025-12-30

### Added
- Web: pricing page (`/pricing`) with plan cards and a feature comparison table aligned to entitlements feature keys.

## [0.2.36] - 2025-12-30

### Added
- Web: landing page sections (hero, how-it-works, modules, FAQ) for logged-out visitors.
- Web: public support page (`/support`) and footer link.

## [0.2.35] - 2025-12-30

### Added
- Web: Jinja2 templates (`offside_bot/templates/*`) with shared layouts/partials/macros.
- Web: static assets served under `/static/*` (CSS: `/static/app.css`).

### Changed
- Dashboard: base page wrapper + app shell now render via templates; inline CSS moved into static stylesheet.

## [0.2.34] - 2025-12-30

### Added
- Billing: checkout success now syncs subscription from Stripe so Pro is enabled immediately after upgrade.
- Dashboard: shows a “Pro expired / payment issue” banner with upgrade + billing links when a subscription is inactive.

## [0.2.33] - 2025-12-30

### Added
- Dashboard: Setup Wizard (`/guild/{guild_id}/setup`) with step-by-step readiness checks and one-click setup.
- Ops: `run_full_setup` endpoint queues `run_setup` then `repost_portals` from the dashboard.

### Changed
- Dashboard nav: added Setup module link.

## [0.2.32] - 2025-12-30

### Added
- Dashboard: Pro-locked screens (Audit Log) with upgrade CTA and benefit list.
- Dashboard: `/app/upgrade` redirect that records upgrade clicks (audit event `billing/upgrade.clicked`).

### Changed
- Dashboard nav: hides Pro-only modules for Free guilds.
- Settings: Pro-only controls are disabled on Free and rejected on save (Premium tiers, Premium Coaches pin, FC25 stats override).

## [0.2.31] - 2025-12-30

### Added
- Dashboard: guild overview page (`/guild/{guild_id}/overview`) with setup checklist, quick actions, and key stats.

### Changed
- Dashboard: server cards and install flow default to Overview.

## [0.2.30] - 2025-12-30

### Added
- Dashboard: Ops page (`/guild/{guild_id}/ops`) to queue “run setup” and “repost portals” actions.
- Worker: DB-backed ops task consumer job with audit events for enqueue/start/complete/fail.

## [0.2.29] - 2025-12-30

### Added
- Dashboard: shared app shell (topbar + sidebar) with server selector, plan badge, and install CTA.

### Changed
- Dashboard pages now share consistent navigation/layout across modules.

## [0.2.28] - 2025-12-30

### Added
- Dashboard: permissions validator UI (`/guild/{guild_id}/permissions`) with role hierarchy + channel access checks.

## [0.2.27] - 2025-12-30

### Added
- Ops: audit log events (`audit_events`) for config changes, billing webhooks, and staff actions.
- Dashboard: audit log viewer (`/guild/{guild_id}/audit`) with CSV export (`/guild/{guild_id}/audit.csv`).

### Changed
- Migrations: schema version bumped to 5 to ensure new indexes.

## [0.2.26] - 2025-12-30

### Added
- Dashboard: legal pages (`/terms`, `/privacy`) rendered from markdown with footer links.

## [0.2.25] - 2025-12-30

### Added
- Ops: optional Sentry error reporting for bot + web dashboard (`SENTRY_DSN`, `SENTRY_ENVIRONMENT`).

### Security
- Error reports: scrub token/secret-like fields before sending to Sentry.

## [0.2.24] - 2025-12-30

### Added
- Billing: Stripe Billing Portal integration (self-serve subscription management) in the web dashboard.
- Docs: Stripe billing configuration guide (`docs/billing.md`).

### Fixed
- Typing: widened Discord channel permission overwrites typing for newer discord.py stubs.

## [0.2.23] - 2025-12-30

### Added
- MongoDB: optional per-guild database mode (`MONGODB_PER_GUILD_DB`, `MONGODB_GUILD_DB_PREFIX`) for stronger multi-tenant isolation.
- MongoDB: new core entity collections + record types (`coaches`, `managers`, `players`, `leagues`, `stats`) with indexes.
- Dashboard: `python -m offside_bot.dashboard` (Discord OAuth2 login + guild analytics).
- Analytics: `services/analytics_service.py` and tests for per-guild DB routing.
- Scripts: `python -m scripts.migrate --guild-id <id>` support for per-guild DB mode.

### Changed
- Bot startup: when per-guild DB mode is enabled, migrations/recovery are applied per guild on startup/join.

## [0.2.22] - 2025-12-30

### Added
- Seed tooling: `scripts.seed_test_data` supports `--env-file`, `--db-name`, and `--collection` overrides.
- Testing: optional live MongoDB smoke test (`tests/e2e/test_live_mongo_smoke.py`) gated by `LIVE_MONGO_SMOKE=1`.

### Fixed
- Services: avoid `pymongo.collection.Collection` truthiness checks when passing explicit collection handles.

## [0.2.21] - 2025-12-30

### Added
- Dev tooling: `python -m scripts.seed_test_data` to seed demo data across all MongoDB collections/record types.

## [0.2.20] - 2025-12-30

### Changed
- MongoDB: defaults database name to `OffsideDiscordBot` when `MONGODB_DB_NAME` is unset.
- MongoDB: defaults to a multi-collection schema (one collection per record type); `MONGODB_COLLECTION` enables legacy single-collection mode.
- Migrations: schema version bumped to 4; indexes are ensured per collection.

### Updated
- Docs: clarified MongoDB configuration in `.env.example`, `README.md`, and `docs/server-setup-checklist.md`.

## [0.2.19] - 2025-12-30

### Added
- Staff portal: "Verify Setup" button to re-run auto-setup and report changes for the current guild.
- Listing channels: pinned "About" instruction embeds (prod only; idempotent).

### Changed
- Auto-setup order: coach tier roles are ensured before channel permissions are applied.
- Channel permissions: `coach-portal` is coaches-only; public portals and listing channels are read-only (staff can still moderate).

## [0.2.18] - 2025-12-30

### Added
- Premium Coaches report improvements: Premium vs Premium+ sections, last-updated timestamp, optional pin, and a manager "force rebuild" cleanup action.
- Club Managers portal: Sync Caps (Active Cycle) action and audit events for tier changes/cap syncs.
- Portal UX: standardized intro/control panel formatting, "Last refreshed" footers, and a staff-only "Repost Portal" action on each portal.
- Server onboarding checklist: `docs/server-setup-checklist.md`.

### Changed
- Recruit and club listing embeds: improved field ordering/icons, "Updated" footers, and safer long-text handling (split/truncate with guidance).
- Dependencies: add `tzdata` for cross-platform `zoneinfo` support (Windows/dev environments).

## [0.2.17] - 2025-12-30

### Added
- Auto-setup: bot now provisions Offside categories/channels/roles on guild join and on startup.
- Guild-scoped portal posting helpers (used for guild-join auto-deploy).

### Changed
- `/setup_channels` removed; docs and user-facing copy now refer to auto-setup instead of a manual setup command.
- `.env.example` updated to clarify that channel/role IDs are normally created + stored by auto-setup.

### Removed
- `futwiz_player_evolution_github_issues.md` after importing issues into GitHub.

## [0.2.16] - 2025-12-30

### Added
- Club Managers portal: `/setup_channels` now creates `club-managers-portal` and the bot auto-posts a control panel for coach tier management and roster unlocks.
- Staff portal now links to the Club Managers portal for coach-management actions.
- Approved rosters now post as rich embeds in the roster listing channel (mentions suppressed).
- New backlog file: `futwiz_player_evolution_github_issues.md` (repurposed for Offside bot issue planning).

### Changed
- Added optional `CHANNEL_MANAGER_PORTAL_ID` env override (primary source remains per-guild config written by `/setup_channels`).

## [0.2.15] - 2025-12-30

### Added
- `/setup_channels` now also ensures coach roles (`Coach`, `Coach Premium`, `Coach Premium+`) and stores per-guild role IDs in Mongo.
- Offside Reports: `premium-coaches` channel and an auto-updating Premium Coaches embed (roster name, openings, practice times).
- Roster dashboard: Practice Times button + modal; premium listings refresh on roster changes.

### Changed
- Coach role IDs are no longer required env vars; `ROLE_COACH_ID` (or legacy `ROLE_SUPER_LEAGUE_COACH_ID`) is supported as an optional override.
- Added optional `CHANNEL_PREMIUM_COACHES_ID` env override (primary source remains per-guild config written by `/setup_channels`).

## [0.2.14] - 2025-12-29

### Fixed
- CI packaging build now succeeds via explicit setuptools package discovery in `pyproject.toml`.
- CI type checking now passes after aligning Discord channel helpers/types.

### Changed
- Dependency updates: discord.py 2.6.4, gspread 6.2.1, google-auth 2.45.0, pymongo 4.15.5, mypy 1.19.1.
- GitHub Actions updates: actions/checkout v6, actions/setup-python v6.
- Admin portal no longer offers ad-hoc test mode toggles (test mode is controlled via config and `/setup_channels`).

## [0.2.13] - 2025-12-29

### Added
- `/setup_channels` to create/repair the `--OFFSIDE DASHBOARD--` and `--OFFSIDE REPORTS--` categories + channels and store per-guild IDs in Mongo.
- Centralized channel resolver (per-guild config + env fallback) so portal/listing posts respect test mode automatically.
- Recruitment portal: player profile register/edit, preview, availability selector, unregister; idempotent listing + staff-copy upserts.
- Club portal: club ad register/edit, preview, unregister; idempotent listing + staff-copy upserts.
- FC25 Clubs verified stats (optional; `FEATURE_FLAGS=fc25_stats`): policy docs, Mongo records + indexes, async HTTP client + typed errors, caching/rate limits/circuit breaker, link/unlink/refresh, scheduled refresh worker, and embed rendering.
- Roster tools: coach "Add From Player Pool" flow with filters (position/archetype/server) + pagination; selection pre-fills the add-player modal.
- Staff tools: `/player_pool`, `/player_pool_index` (pinned index), and `/me` (ephemeral profile preview).
- Abuse/quality controls: cooldowns on profile/ad edits, minimum publish requirements, and club ad minimum description length.
- Optional club ad approvals (`FEATURE_FLAGS=club_ads_approval`) with approve/reject actions and audit logging.
- QA checklist (`docs/qa-checklist.md`) and additional parsing/fixture tests for FC25 helpers.

### Changed
- `TEST_MODE=true` routes all portal posts, listing posts, and forwarded logs to the staff monitor channel (`channel_staff_monitor_id`) only.
- Channel env vars are optional overrides; approved rosters post to `CHANNEL_ROSTER_LISTING_ID` (fallback to legacy `CHANNEL_ROSTER_PORTAL_ID`).
- Recruitment/club listing posts use safe `allowed_mentions` defaults to avoid pings.

### Removed
- `/dev_on` and `/dev_off` test-mode toggle commands.
- `DISCORD_TEST_CHANNEL` config (no longer required or used).

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
