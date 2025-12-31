# Offside Discord Bot

Roster management and staff review bot for Discord tournaments.

## Getting Started (Tournament Operators)

1. Set up Discord channels and roles:
   - Invite the bot with permissions to manage channels/roles, send messages, read message history, and use slash commands.
   - On join/startup, the bot auto-creates the `--OFFSIDE DASHBOARD--` / `--OFFSIDE REPORTS--` layout, required channels (including Club Managers + Premium Coaches), and the coach roles (`Coach`, `Coach Premium`, `Coach Premium+`).
   - Assign the coach roles to your coaches (premium tiers control roster caps).
   - Checklist: `docs/server-setup-checklist.md`
2. Configure the bot:
   - Copy `.env.example` to `.env` and fill in the required IDs and tokens.
   - Keep `TEST_MODE=true` while validating in a staging guild (routes all portal/listing posts + forwarded logs to the staff monitor channel).
3. Deploy and verify:
   - Run locally (`python -m offside_bot`) or deploy to your host (e.g., Heroku worker).
   - Maintainers: release + rollback checklist: `docs/release-playbook.md`
   - Confirm the coach and staff portal embeds appear in their channels (or run the portal refresh buttons).
   - Submit a test roster, approve/reject, and confirm approved rosters flow to the roster listing channel.

## Features (current)

- Ephemeral roster workflow with role-based caps and min-8 submission rule; identity checks enforce no duplicates and required player fields.
- Staff review with approve/reject/unlock; decisions DM coaches with reasons; staff cards cleaned after action.
- Portals auto-post on startup: coach portal (dashboard/help), staff portal (controls/review), roster portal (approved only); bot cleans prior portal embeds before posting new ones.
- Premium coaches report channel auto-updates with roster name, openings, and practice times.
- Listing channels are read-only and include pinned "About" instructions (bot-managed).
- Audit trail for staff actions; unlock clears stale submissions for resubmission.
- Tournament scaffold with staff-only commands, bracket preview/publish, match/dispute flows, and leaderboard stats.
- Optional Google Sheets ban list checks.
- Test mode routing with Discord log forwarding and structured command logging (guild/channel/user/command).
- Startup migrations + recovery run automatically; Mongo client closes cleanly on shutdown.
- Backoff + timeouts on Discord HTTP calls to reduce rate-limit impact; retries respect `retry_after`.
- Command registry validation prevents duplicate slash names or missing descriptions at startup.
- Command docs are generated from shared metadata (`docs/commands.md`); CI checks they stay in sync.
- Per-guild config overrides (staff-only) and mass-mention guard on inputs; allowed mentions restrict @everyone/@here/roles by default.
- Optional sharding (`USE_SHARDING`, `SHARD_COUNT`) for scale-out; channel lookups cached to reduce Discord API pressure.
- Dependabot + `pip-audit` keep dependencies healthy; release workflow builds artifacts on tags.

## Portals (auto-posted on startup)

- **Staff Portal** (`channel_staff_portal_id`): staff review (approve/reject) + quick-reference panel.
- **Club Managers Portal** (`channel_manager_portal_id`): coach tiers (Coach/Premium/Premium+), roster unlock/delete, premium coaches refresh, and cap sync tools.
- **Coach Portal** (`channel_coach_portal_id`): roster dashboard + coach help (buttons; responses are ephemeral). Channel is coaches-only.
- **Recruit Portal** (`channel_recruit_portal_id`): recruit profile register/edit/preview/unregister (buttons; responses are ephemeral).
- **Club Portal** (`channel_club_portal_id`): club ad register/edit/preview/unregister (buttons; responses are ephemeral).
- **Roster Listing** (`channel_roster_listing_id`): approved roster embeds reposted here after staff approval.
- **Recruit Listing** (`channel_recruit_listing_id`): recruit profile listing embeds.
- **Club Listing** (`channel_club_listing_id`): club ad listing embeds.
- **Premium Coaches** (`channel_premium_coaches_id`): premium coach roster listings (openings + practice times).

### Dashboard embeds & buttons
- Coach portal: intro embed + roster portal embed. Buttons open the roster dashboard (add/remove/view/submit, rename) and coach help. Responses are ephemeral; portal is idempotent and cleans prior portal embeds.
- Staff portal: intro embed + admin control panel. Buttons for Tournaments, Club Managers portal link, Players, DB/Analytics, and Verify Setup. Staff actions are ephemeral; the submission review message is cleaned after approve/reject.
- Club Managers portal: intro embed + control panel. Buttons for Set Coach Tier, Unlock Roster, Refresh Premium Coaches, Toggle Premium Pin, Force Rebuild Premium, Sync Caps (Active Cycle), and Delete Roster (admin-only).
- All portals include a staff-only "Repost Portal" action for quick cleanup/repost.
- Help command: `/help` returns an embed with coach/staff/tournament/ops categories and submission steps; all responses are ephemeral.

## Commands

Roster & Staff
- `/roster [tournament]` opens the roster dashboard (create/add/remove/view/submit). Example: `/roster tournament:"Summer Cup"`.
- `/unlock_roster <coach> [tournament]` staff-only unlock; uses latest roster if tournament omitted. Example: `/unlock_roster @Coach`.
- `/help` command catalog + coach/staff steps.
- `/ping` health check.

Tournament (staff-only)
- `/tournament_dashboard` staff quick-reference embed for tournament ops.
- `/tournament_create <name> [format] [rules]`
- `/tournament_state <name> <DRAFT|REG_OPEN|IN_PROGRESS|COMPLETED>`
- `/tournament_register <tournament> <team_name> <coach_id> [seed]`
- `/tournament_bracket <tournament>` publish round-1 bracket and advance state.
- `/tournament_bracket_preview <tournament>` dry-run preview of round-1 pairings (no DB writes).
- `/advance_round <tournament>` create next round from winners.
- `/tournament_stats <tournament>` leaderboard (wins/loss/GD) from completed matches.
- `/match_report <tournament> <match_id> <reporter_team_id> <score_for> <score_against>`
- `/match_confirm <tournament> <match_id> <confirming_team_id>`
- `/match_deadline <tournament> <match_id> <deadline note>`
- `/match_forfeit <tournament> <match_id> <winner_team_id>`
- `/match_reschedule <tournament> <match_id> <reason>`
- `/dispute_add <tournament> <match_id> <reason>`
- `/dispute_resolve <tournament> <match_id> <resolution>`
- Groups: `/group_create`, `/group_register`, `/group_generate_fixtures [double_round]`, `/group_match_report`, `/group_standings`, `/group_advance <top_n>`

Operations (staff-only)
- `/config_view` snapshot of non-secret runtime settings.
- `/config_set <field> <value>` runtime override (no persistence; restart to reset).
- `/config_guild_view` / `/config_guild_set <field> <value>` per-guild overrides (staff).
- `/rules_template` starter rules template to copy/paste.
- `/help` command catalog (coach/staff/tournament/ops) and step-by-step submission guidance; all responses are ephemeral.
- Command registration:
  - `python -m scripts.register_commands --guild <id>` to sync to a dev guild.
  - `python -m scripts.register_commands --global` to sync globally after validation.

## Configuration

Use `.env.example` as the template for your `.env`. Required fields are listed below; keep secrets out of version control.

Required (startup):
- `DISCORD_TOKEN`
- `DISCORD_APPLICATION_ID`

Required for persistence:
- `MONGODB_URI`

Recommended:
- `MONGODB_DB_NAME` (shared DB mode; defaults to `OffsideDiscordBot`)
- `MONGODB_PER_GUILD_DB` (optional; when `true`, each guild uses its own MongoDB database named `<MONGODB_GUILD_DB_PREFIX><guild_id>`)
- `MONGODB_GUILD_DB_PREFIX` (optional; defaults to empty string)

Optional:
- `MONGODB_COLLECTION` (legacy single-collection mode; e.g., `Isaac_Elera`)
- `STAFF_ROLE_IDS` (comma-separated role IDs)
- `TEST_MODE` (defaults to `true`, set `false` for production)
- Role env overrides (optional; primary source is per-guild config created by auto-setup):
  - `ROLE_COACH_ID` (or legacy `ROLE_SUPER_LEAGUE_COACH_ID`)
  - `ROLE_COACH_PREMIUM_ID`
  - `ROLE_COACH_PREMIUM_PLUS_ID`
- Channel env overrides (optional; primary source is per-guild config created by auto-setup):
  - `CHANNEL_STAFF_PORTAL_ID`, `CHANNEL_MANAGER_PORTAL_ID`, `CHANNEL_CLUB_PORTAL_ID`, `CHANNEL_COACH_PORTAL_ID`, `CHANNEL_RECRUIT_PORTAL_ID`
  - `CHANNEL_STAFF_MONITOR_ID` (test-mode sink)
  - `CHANNEL_ROSTER_LISTING_ID` (fallback to legacy `CHANNEL_ROSTER_PORTAL_ID`)
  - `CHANNEL_RECRUIT_LISTING_ID`, `CHANNEL_CLUB_LISTING_ID`, `CHANNEL_PREMIUM_COACHES_ID`

Optional (billing / Pro plan):
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_PRO_ID`
- Setup guide: `docs/billing.md`

Optional (ops):
- `LOG_LEVEL` (default INFO)
- `SENTRY_DSN` (error reporting for bot + dashboard)
  - `SENTRY_ENVIRONMENT` (default `production`)
  - `SENTRY_TRACES_SAMPLE_RATE` (default `0`)
- `BANLIST_SHEET_ID`
- `BANLIST_RANGE`
- `BANLIST_CACHE_TTL_SECONDS` (default 300)
- `GOOGLE_SHEETS_CREDENTIALS_JSON`
- `USE_SHARDING` (default false) and optional `SHARD_COUNT` for scale-out.
- `FEATURE_FLAGS` (comma-separated; e.g., `metrics_log` for scheduler demo).
- FC25 stats (optional; requires `FEATURE_FLAGS=fc25_stats`, see `docs/fc25-stats-policy.md`; includes a scheduled refresh worker).
  - `FC25_STATS_CACHE_TTL_SECONDS` (default 900)
  - `FC25_STATS_HTTP_TIMEOUT_SECONDS` (default 7)
  - `FC25_STATS_MAX_CONCURRENCY` (default 3)
  - `FC25_STATS_RATE_LIMIT_PER_GUILD` (default 20)
  - `FC25_DEFAULT_PLATFORM` (default `common-gen5`)
- Club ad approvals (optional; requires `FEATURE_FLAGS=club_ads_approval` to gate first-time public posting behind staff approve/reject).

## Migrations

- Run automatically at startup and can be run manually: `python -m scripts.migrate`
- Schema version stored in Mongo `_meta.schema_version`; primary indexes ensured.
- Docs generation: `python -m scripts.generate_docs` (CI enforces freshness with `--check`).

## Test mode

When `TEST_MODE=true`, all portal posts, listing posts, and forwarded logs are routed to the
staff monitor channel (`channel_staff_monitor_id`) only.
- The staff monitor channel is created automatically under `--OFFSIDE REPORTS--`.
- When `TEST_MODE=false`, the bot will delete the staff monitor channel if it is marked as bot-managed.

## Roster rules

- Minimum 8 players required to submit a roster; no duplicate players.
- Each player must include a gamertag and EA ID; entries are validated before submission.
- Rosters lock on submit/approve/reject; staff can unlock from the admin portal. Unlocking clears stale submissions so the coach can resubmit.
- Staff review occurs in the staff portal; approved rosters are reposted to the roster portal only, and the staff review message is cleaned up after a decision.

## Local run

1. Create a `.env` file with the required settings.
2. Install dependencies:
   - `python -m pip install -r requirements.txt`
3. Start the bot:
   - `python -m offside_bot`

## Docker

- Build: `docker build -t offside-bot .` (or `docker build --platform linux/amd64 -t offside-bot .`)
- Run: `docker run --env-file .env --restart unless-stopped offside-bot`
- Compose: `docker-compose up --build` (uses `docker-compose.yml`)

## Development

- Install dev tools: `python -m pip install -r requirements.txt -r requirements-dev.txt`
- Lint/format: `ruff check .` (and `ruff format .` if you want formatting).
- Type check: `mypy .`
- Tests: `python -m pytest`
- Seed demo data: `python -m scripts.seed_test_data --env-file .env --collection Isaac_Elera --guild-id <id> --purge`
- Dashboard (optional): `python -m offside_bot.dashboard` (requires `DISCORD_CLIENT_SECRET`, `DASHBOARD_REDIRECT_URI`, and `MONGODB_URI` for durable sessions)
- Register commands: `python -m scripts.register_commands --guild <id>` during dev; use `--global` for production sync after validation.
- Logging: structured key/value logging with command context (guild/channel/user/command); set `LOG_LEVEL=DEBUG` for verbose output in staging.
- Signals & shutdown: SIGTERM/SIGINT trigger a graceful shutdown and close the Mongo client; Discord backoff helpers use timeouts and honor `retry_after`.
- Docs/Help sync: `python -m scripts.generate_docs` refreshes `docs/commands.md`; `/help` pulls from the same catalog.
- Per-guild config: staff can use `/config_guild_set` to override settings per guild; stored in Mongo `guild_settings`.
- Releases: pushing a `v*` tag runs the release workflow to build and attach wheel/sdist artifacts.
- Dev watch: `python -m scripts.dev_watch` (requires `watchfiles`) restarts the bot on Python file changes.
- Profiling: `python -m scripts.profile --module offside_bot.__main__ --func main` for quick CPU profiling (non-production).
- Feature flags: use `FEATURE_FLAGS=metrics_log` to enable sample scheduler job; extend via `utils/flags.py`.

### Embed style guide
- Use `utils.embeds.make_embed` to keep colors/icons consistent.
- Colors: `DEFAULT_COLOR` (info), `SUCCESS_COLOR` (confirmations), `WARNING_COLOR` (attention), `ERROR_COLOR` (errors).
- Prefer concise descriptions and ephemeral responses to reduce channel noise.

## Testing

- Run the full suite: `python -m pytest` (or `py -3.12 -m pytest` on Windows).
- Tests use `mongomock` by default and do not hit live services.
- Optional live MongoDB smoke test: `LIVE_MONGO_SMOKE=1 python -m pytest -q tests/e2e/test_live_mongo_smoke.py`

## Notes

- The one-time member export helper was removed after use; current repo contains only bot/runtime code.
- Migrations and recovery run automatically at startup:
  - Schema version is tracked in `_meta.schema_version`; indexes are ensured each boot.
  - Recovery unlocks rosters that were submitted but lost their submission message record and prunes orphan submission docs.
- Timezones: timestamps are treated as UTC by default. Use `utils.time_utils.format_dt(dt, tz="Your/Zone")` to render friendly times in a specific timezone, and supply scheduling/deadline inputs in UTC to avoid ambiguity.

## Heroku deploy

1. Ensure the repo includes a `Procfile` with a worker process.
2. Add required config vars in the Heroku dashboard or CLI.
3. Scale the worker dyno:
   - `heroku ps:scale worker=1 -a <app-name>`

## Deployment Hardening (Recommended)
- Enable Privileged Intents (Server Members) in the Discord developer portal if you need member exports or eligibility checks.
- Lock down secrets: use Heroku config vars or `.env` locally; never commit tokens/URIs/keys.
- Limit MongoDB access (IP allowlist / auth) and enforce strong credentials.
- Use test mode in staging guilds before toggling `TEST_MODE=false` for production.
- CI already runs ruff/mypy/pytest; keep it green before deploys.

## Documentation

- Security policy: `SECURITY.md`
- License: `LICENSING.md`
- Changelog: `CHANGELOG.md`
- Release playbook: `docs/release-playbook.md`
- Data lifecycle (backups/retention/deletion): `docs/data-lifecycle.md`
