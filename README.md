# Offside Discord Bot

Roster management and staff review bot for Discord tournaments.

## Local run

1. Create a `.env` file with the required settings:
   - `DISCORD_TOKEN`
   - `DISCORD_APPLICATION_ID`
   - `ROLE_BROSKIE_ID`
   - `ROLE_SUPER_LEAGUE_COACH_ID`
   - `ROLE_COACH_PREMIUM_ID`
   - `ROLE_COACH_PREMIUM_PLUS_ID`
   - `CHANNEL_ROSTER_PORTAL_ID`
   - `CHANNEL_STAFF_SUBMISSIONS_ID`
2. Install dependencies:
   - `python -m pip install -r requirements.txt`
3. Start the bot:
   - `python -m offside_bot`

## Heroku deploy

1. Ensure the repo includes a `Procfile` with a worker process.
2. Add required config vars in the Heroku dashboard or CLI.
3. Scale the worker dyno:
   - `heroku ps:scale worker=1 -a <app-name>`

## Configuration

Required environment variables are validated at startup. See `config/constants.py`
and `config/settings.py` for the full list and types.
