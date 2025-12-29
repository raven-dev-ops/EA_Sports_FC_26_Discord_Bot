"""
Run database migrations.

Usage:
  python -m scripts.migrate
"""
from __future__ import annotations

import logging

from config import load_settings
from migrations import apply_migrations


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    latest = apply_migrations(settings=settings, logger=logging.getLogger(__name__))
    logging.info("Migrations complete. Current version: %s", latest)


if __name__ == "__main__":
    main()
