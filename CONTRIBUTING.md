# Contributing Guide

Thanks for helping improve Offside! This guide covers local setup, coding standards, and how to contribute.

## Local Setup

1. Clone the repo and create a Python 3.12 virtualenv:
   - Windows: `py -3.12 -m venv .venv`
   - macOS/Linux: `python3.12 -m venv .venv`
2. Copy `.env.example` to `.env` and fill required values:
   - Required: `DISCORD_TOKEN`, `DISCORD_APPLICATION_ID`, `MONGODB_URI`
   - Optional (web dashboard OAuth): `DISCORD_CLIENT_SECRET`, `DASHBOARD_REDIRECT_URI`
   - Channel/role IDs are optional overrides; the bot auto-creates channels/roles on join/startup.
3. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt -r requirements-dev.txt
   ```
4. Run the bot locally:
   ```bash
   python -m offside_bot
   ```

## Development Workflow

- Lint/format: `ruff check .` (and `ruff format .` if you want formatting applied).
- Type check: `mypy .`
- Tests: `python -m pytest`
- Docs sync: `python -m scripts.generate_docs --check`
- Pre-commit (optional but recommended): `pre-commit install` then commits will run hooks automatically.

## Docker

Build and run locally:
```bash
docker build -t offside-bot .
docker run --env-file .env offside-bot
```

## Logging & Error Handling

- Structured logs are enabled by default; adjust `LOG_LEVEL` env if needed.
- Uncaught exceptions are logged; ensure errors surface rather than being swallowed.

## Secrets

- Never commit `.env` or secrets. Use `.env.example` as the reference.
- Keep Discord tokens, Mongo URIs, and API keys out of logs, issues, and PRs.

## Pull Requests

- Keep PRs small and focused; include tests for new logic.
- Update README/CHANGELOG when behavior or setup changes.
- Describe testing performed (e.g., `pytest`, `ruff`, `mypy`).
- If you touch commands, make sure `docs/commands.md` is up to date.
- For security issues, follow `SECURITY.md` and do not open a public issue.

## Contributions and Licensing

This repo is "all rights reserved." By submitting a pull request, you agree that
your contribution may be used, modified, and distributed by Raven Development Operations
and incorporated into this repository under the same "all rights reserved" terms.
