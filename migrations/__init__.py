from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from database import get_collection, get_database, ensure_indexes

MigrationFunc = Callable[[dict], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _meta_collection(db):
    return db["_meta"]


def _get_current_version(db) -> int:
    meta = _meta_collection(db).find_one({"_id": "schema_version"})
    return int(meta["version"]) if meta and "version" in meta else 0


def _set_version(db, version: int, description: str | None = None) -> None:
    _meta_collection(db).update_one(
        {"_id": "schema_version"},
        {"$set": {"version": version, "description": description, "updated_at": _now()}},
        upsert=True,
    )


def _migration_1(context: dict) -> None:
    """
    Ensure primary indexes on the main collection for roster/tournament records.
    """
    collection = context["collection"]
    ensure_indexes(collection)


MIGRATIONS: list[tuple[int, str, MigrationFunc]] = [
    (1, "Ensure primary indexes", _migration_1),
]


def apply_migrations(*, settings=None, logger: logging.Logger | None = None) -> int:
    """
    Apply pending migrations in order. Returns the latest version after migration.
    """
    log = logger or logging.getLogger(__name__)
    db = get_database(settings)
    collection = get_collection(settings)
    current = _get_current_version(db)
    log.info("Current schema version: %s", current)
    for version, description, func in MIGRATIONS:
        if version <= current:
            continue
        log.info("Applying migration %s: %s", version, description)
        func({"db": db, "collection": collection, "settings": settings})
        _set_version(db, version, description)
        log.info("Migration %s applied.", version)
    return _get_current_version(db)
