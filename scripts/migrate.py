"""
Run database migrations.

Usage:
  python -m scripts.migrate
  python -m scripts.migrate --guild-id 123  # required when MONGODB_PER_GUILD_DB=true
"""
from __future__ import annotations

import argparse
import logging

from config import load_settings
from database import guild_db_context
from migrations import apply_migrations


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Offside MongoDB migrations.")
    parser.add_argument(
        "--guild-id",
        type=int,
        default=None,
        help="Guild ID to migrate when using per-guild DB mode.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()
    settings = load_settings()
    if settings.mongodb_per_guild_db:
        if args.guild_id is None:
            raise SystemExit("MONGODB_PER_GUILD_DB is enabled; pass --guild-id <id> to migrate.")
        with guild_db_context(int(args.guild_id)):
            latest = apply_migrations(settings=settings, logger=logging.getLogger(__name__))
    else:
        latest = apply_migrations(settings=settings, logger=logging.getLogger(__name__))
    logging.info("Migrations complete. Current version: %s", latest)


if __name__ == "__main__":
    main()
