from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from config import Settings
from database import get_client, get_database, get_global_collection, get_global_database
from services import entitlements_service
from services.stripe_webhook_service import (
    STRIPE_DEAD_LETTERS_COLLECTION,
    STRIPE_EVENTS_COLLECTION,
)
from services.subscription_service import COLLECTION_NAME as SUBSCRIPTIONS_COLLECTION


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _delete_stripe_dead_letters(dead_letters: Collection, *, guild_id: int) -> int:
    deleted = 0
    for value in (guild_id, str(guild_id)):
        result = dead_letters.delete_many({"payload.data.object.metadata.guild_id": value})
        deleted += int(result.deleted_count or 0)
    return deleted


def delete_guild_data(settings: Settings, *, guild_id: int) -> dict[str, Any]:
    """
    Irreversibly delete all stored data for a guild.

    This is only supported when MONGODB_PER_GUILD_DB is enabled (multi-tenant safe).
    """
    if not settings.mongodb_uri:
        raise RuntimeError("MongoDB is not configured.")
    if not settings.mongodb_per_guild_db:
        raise RuntimeError("Guild data deletion requires MONGODB_PER_GUILD_DB=true.")

    guild_id_int = int(guild_id)
    global_deleted: dict[str, int] = {}

    subscriptions = get_global_collection(settings, name=SUBSCRIPTIONS_COLLECTION)
    global_deleted[SUBSCRIPTIONS_COLLECTION] = int(
        subscriptions.delete_one({"_id": guild_id_int}).deleted_count or 0
    )

    stripe_events = get_global_collection(settings, name=STRIPE_EVENTS_COLLECTION)
    global_deleted[STRIPE_EVENTS_COLLECTION] = int(
        stripe_events.delete_many({"guild_id": guild_id_int}).deleted_count or 0
    )

    stripe_dead_letters = get_global_collection(settings, name=STRIPE_DEAD_LETTERS_COLLECTION)
    global_deleted[STRIPE_DEAD_LETTERS_COLLECTION] = _delete_stripe_dead_letters(
        stripe_dead_letters,
        guild_id=guild_id_int,
    )

    db = get_database(settings, guild_id=guild_id_int)
    db_name = db.name
    global_db_name = get_global_database(settings).name
    if db_name == global_db_name:
        raise RuntimeError(
            "Refusing to drop global database; check MONGODB_DB_NAME/MONGODB_GUILD_DB_PREFIX configuration."
        )

    client = get_client(settings)
    client.drop_database(db_name)

    try:
        entitlements_service.invalidate_guild_plan(guild_id_int)
    except Exception:
        pass

    return {
        "guild_id": guild_id_int,
        "db_dropped": db_name,
        "global_deleted": global_deleted,
        "deleted_at": _utc_now(),
    }

