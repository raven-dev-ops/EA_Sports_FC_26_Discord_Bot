# Offside Discord Bot

Roster management and staff review bot for Discord tournaments.

## Features

- Ephemeral roster workflow with role-based caps.
- Staff review with approve/reject and unlock flows.
- Multi-tournament cycle selection for rosters.
- Audit trail for staff actions.
- Optional Google Sheets ban list checks.
- Test mode routing with Discord log forwarding.

## Commands

- `/roster [tournament]` - Opens the roster creation modal (uses tournament if provided). How it works: prompts for team name and optional tournament name, then shows the roster dashboard buttons for add/remove/view/submit. Example: `/roster` or `/roster tournament:"Summer Cup"`.
- `/unlock_roster <coach> [tournament]` - Staff-only unlock command (optional tournament). How it works: unlocks the coach's roster for edits; uses the latest roster if no tournament is provided. Example: `/unlock_roster @Coach` or `/unlock_roster @Coach tournament:"Summer Cup"`.
- `/dev_on` - Staff-only toggle to force test-mode routing. How it works: routes staff submissions and bot logs to `DISCORD_TEST_CHANNEL` for this session. Example: `/dev_on`.
- `/dev_off` - Staff-only toggle to disable test-mode routing. How it works: routes messages back to configured channels for this session. Example: `/dev_off`.
- `/ping` - Health check. How it works: replies with `pong`. Example: `/ping`.
- `/help` - Command list and examples. How it works: shows step-by-step roster submission guidance and command usage. Example: `/help`.

## Configuration

Required (startup):
- `DISCORD_TOKEN`
- `DISCORD_APPLICATION_ID`
- `ROLE_BROSKIE_ID`
- `ROLE_SUPER_LEAGUE_COACH_ID`
- `ROLE_COACH_PREMIUM_ID`
- `ROLE_COACH_PREMIUM_PLUS_ID`
- `CHANNEL_ROSTER_PORTAL_ID`
- `CHANNEL_STAFF_SUBMISSIONS_ID`

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

When `TEST_MODE=true`, staff submissions and log messages are routed to
`DISCORD_TEST_CHANNEL`. Use `/dev_on` and `/dev_off` to toggle routing
at runtime (session-scoped).

## Local run

1. Create a `.env` file with the required settings.
2. Install dependencies:
   - `python -m pip install -r requirements.txt`
3. Start the bot:
   - `python -m offside_bot`

## Heroku deploy

1. Ensure the repo includes a `Procfile` with a worker process.
2. Add required config vars in the Heroku dashboard or CLI.
3. Scale the worker dyno:
   - `heroku ps:scale worker=1 -a <app-name>`

## Documentation

- Security policy: `SECURITY.md`
- License: `LICENSING.md`
- Changelog: `CHANGELOG.md`
