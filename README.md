# Offside Discord Bot

Roster management and staff review bot for Discord tournaments.

## Getting Started (Tournament Operators)

1. Set up Discord channels and roles:
   - Create channels for coach portal, staff portal (reviews), and approved roster logs.
   - Create required roles (Broskie, Super League Coach, Coach Premium, Coach Premium Plus) and staff roles.
2. Configure the bot:
   - Copy `.env.example` to `.env` and fill in the required IDs and tokens.
   - Ensure `TEST_MODE=true` and `DISCORD_TEST_CHANNEL` are set while validating in a staging guild.
3. Deploy and verify:
   - Run locally (`python -m offside_bot`) or deploy to your host (e.g., Heroku worker).
   - Confirm the coach and staff portal embeds appear in their channels.
   - Submit a test roster, approve/reject, and confirm approved rosters flow to the roster portal.

## Features (current)

- Ephemeral roster workflow with role-based caps and min-8 submission rule.
- Staff review with approve/reject/unlock; decisions DM coaches with reasons; staff cards cleaned after action.
- Portals auto-post on startup: coach portal (dashboard/help), staff portal (controls/review), roster portal (approved only).
- Audit trail for staff actions; unlock clears stale submissions for resubmission.
- Optional Google Sheets ban list checks.
- Test mode routing with Discord log forwarding.

## Portals (auto-posted on startup)

- **Coach Roster Portal** (channel `CHANNEL_COACH_PORTAL_ID`): embed with buttons to open the roster dashboard (create/add/remove/view/submit) and to show the coach help guide. Responses are ephemeral.
- **Admin/Staff Control Panel** (channel `CHANNEL_STAFF_PORTAL_ID`): embed with buttons for Bot Controls, Tournaments, Coaches, Rosters, Players, DB/Analytics. Each button opens an ephemeral embed and action buttons (e.g., test-mode toggle, health check, roster unlock guidance). The bot deletes the previous portal embed before posting a new one.
- **Approved Roster Posts** (channel `CHANNEL_ROSTER_PORTAL_ID`): only approved rosters are reposted here after staff approval; submission reviews happen in the staff portal.

## Commands

Roster & Staff
- `/roster [tournament]` opens the roster dashboard (create/add/remove/view/submit). Example: `/roster tournament:"Summer Cup"`.
- `/unlock_roster <coach> [tournament]` staff-only unlock; uses latest roster if tournament omitted. Example: `/unlock_roster @Coach`.
- `/dev_on` / `/dev_off` staff-only test-mode routing toggle (routes portals/logs to test channel).
- `/help` command catalog + coach/staff steps.
- `/ping` health check.

Tournament
- `/tournament_create <name> [format] [rules]`
- `/tournament_state <name> <DRAFT|REG_OPEN|IN_PROGRESS|COMPLETED>`
- `/tournament_register <tournament> <team_name> <coach_id> [seed]`
- `/tournament_bracket <tournament>` publish round-1 bracket and advance state.
- `/tournament_bracket_preview <tournament>` dry-run preview of round-1 pairings (no DB writes).
- `/advance_round <tournament>` create next round from winners.
- `/match_report <tournament> <match_id> <reporter_team_id> <score_for> <score_against>`
- `/match_confirm <tournament> <match_id> <confirming_team_id>`
- `/match_deadline <tournament> <match_id> <deadline note>`
- `/match_forfeit <tournament> <match_id> <winner_team_id>`
- `/match_reschedule <tournament> <match_id> <reason>`
- `/dispute_add <tournament> <match_id> <reason>`
- `/dispute_resolve <tournament> <match_id> <resolution>`
- Groups: `/group_create`, `/group_register`, `/group_generate_fixtures [double_round]`, `/group_match_report`, `/group_standings`, `/group_advance <top_n>`

Operations
- `/config_view` staff-only snapshot of non-secret runtime settings.
- `/config_set <field> <value>` staff-only runtime override (no persistence; restart to reset).
- `/rules_template` returns a starter rules template to copy/paste.

## Configuration

Use `.env.example` as the template for your `.env`. Required fields are listed below; keep secrets out of version control.

Required (startup):
- `DISCORD_TOKEN`
- `DISCORD_APPLICATION_ID`
- `ROLE_BROSKIE_ID`
- `ROLE_SUPER_LEAGUE_COACH_ID`
- `ROLE_COACH_PREMIUM_ID`
- `ROLE_COACH_PREMIUM_PLUS_ID`
- `CHANNEL_COACH_PORTAL_ID` (coach portal/dashboard)
- `CHANNEL_STAFF_PORTAL_ID` (admin/staff portal and submission reviews)
- `CHANNEL_ROSTER_PORTAL_ID` (approved roster posts)

Required when `TEST_MODE=true`:
- `DISCORD_TEST_CHANNEL`

Required for persistence:
- `MONGODB_URI`
- `MONGODB_DB_NAME`
- `MONGODB_COLLECTION`

Optional:
- `STAFF_ROLE_IDS` (comma-separated role IDs)
- `TEST_MODE` (defaults to `true`, set `false` for production)
- `DISCORD_CLIENT_ID`
- `DISCORD_PUBLIC_KEY`
- `DISCORD_INTERACTIONS_ENDPOINT_URL`
- `BANLIST_SHEET_ID`
- `BANLIST_RANGE`
- `BANLIST_CACHE_TTL_SECONDS` (default 300)
- `GOOGLE_SHEETS_CREDENTIALS_JSON`

## Test mode

When `TEST_MODE=true`, staff portal messages and log messages are routed to
`DISCORD_TEST_CHANNEL`. Use `/dev_on` and `/dev_off` to toggle routing
at runtime (session-scoped).

## Roster rules

- Minimum 8 players required to submit a roster.
- Rosters lock on submit/approve/reject; staff can unlock from the admin portal. Unlocking clears stale submissions so the coach can resubmit.
- Staff review occurs in the staff portal; approved rosters are reposted to the roster portal only, and the staff review message is cleaned up after a decision.

## Local run

1. Create a `.env` file with the required settings.
2. Install dependencies:
   - `python -m pip install -r requirements.txt`
3. Start the bot:
   - `python -m offside_bot`

## Docker

- Build: `docker build -t offside-bot .`
- Run: `docker run --env-file .env offside-bot`

## Development

- Install dev tools: `python -m pip install -r requirements.txt -r requirements-dev.txt`
- Lint/format: `ruff check .` (and `ruff format .` if you want formatting).
- Type check: `mypy .`
- Tests: `python -m pytest`

### Embed style guide
- Use `utils.embeds.make_embed` to keep colors/icons consistent.
- Colors: `DEFAULT_COLOR` (info), `SUCCESS_COLOR` (confirmations), `WARNING_COLOR` (attention), `ERROR_COLOR` (errors).
- Prefer concise descriptions and ephemeral responses to reduce channel noise.

## Testing

- Run the full suite: `python -m pytest` (or `py -3.12 -m pytest` on Windows).
- Tests use `mongomock` and do not hit live services.

## Notes

- The one-time member export helper was removed after use; current repo contains only bot/runtime code.

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
