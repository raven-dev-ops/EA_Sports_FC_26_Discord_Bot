from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from config import load_settings
from database import ensure_indexes, ensure_offside_indexes, get_collection, get_database
from services.entitlements_service import ensure_entitlements_indexes
from services.stripe_webhook_service import ensure_stripe_webhook_indexes
from services.subscription_service import ensure_subscription_indexes

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
    collection = context.get("collection")
    if collection is None:
        return
    ensure_indexes(collection)


def _migration_2(context: dict) -> None:
    """
    Ensure indexes for recruit/club records and new record types.
    """
    collection = context.get("collection")
    if collection is None:
        return
    ensure_indexes(collection)


def _migration_3(context: dict) -> None:
    """
    Ensure indexes for FC25 stats records.
    """
    collection = context.get("collection")
    if collection is None:
        return
    ensure_indexes(collection)


def _migration_4(context: dict) -> None:
    """
    Ensure indexes for the recommended multi-collection Offside schema.
    """
    db = context["db"]
    ensure_offside_indexes(db)


def _migration_5(context: dict) -> None:
    """
    Ensure indexes for audit events and any newly-added collections.
    """
    collection = context.get("collection")
    if collection is not None:
        ensure_indexes(collection)
    db = context["db"]
    ensure_offside_indexes(db)


def _migration_6(context: dict) -> None:
    """
    Ensure indexes for Stripe webhooks and guild subscriptions (entitlements mapping).
    """
    settings = context["settings"]
    ensure_subscription_indexes(settings)
    ensure_stripe_webhook_indexes(settings)
    ensure_entitlements_indexes(settings)


MIGRATIONS: list[tuple[int, str, MigrationFunc]] = [
    (1, "Ensure primary indexes", _migration_1),
    (2, "Ensure recruit/club indexes", _migration_2),
    (3, "Ensure FC25 stats indexes", _migration_3),
    (4, "Ensure multi-collection Offside indexes", _migration_4),
    (5, "Ensure audit/index updates", _migration_5),
    (6, "Ensure billing/entitlements indexes", _migration_6),
]


def apply_migrations(*, settings=None, logger: logging.Logger | None = None) -> int:
    """
    Apply pending migrations in order. Returns the latest version after migration.
    """
    log = logger or logging.getLogger(__name__)
    if settings is None:
        settings = load_settings()
    db = get_database(settings)
    collection = get_collection(settings) if settings.mongodb_collection else None
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
