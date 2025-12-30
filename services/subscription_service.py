from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from config import Settings, load_settings
from database import get_global_collection

COLLECTION_NAME = "guild_subscriptions"
SCHEMA_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _settings_or_default(settings: Settings | None) -> Settings:
    return settings or load_settings()


def get_subscription_collection(settings: Settings | None = None) -> Collection:
    settings = _settings_or_default(settings)
    return get_global_collection(settings, name=COLLECTION_NAME)


def ensure_subscription_indexes(settings: Settings | None = None) -> list[str]:
    col = get_subscription_collection(settings)
    indexes: list[str] = []
    indexes.append(col.create_index([("guild_id", 1)], unique=True, name="uniq_guild_id"))
    indexes.append(col.create_index([("customer_id", 1)], name="idx_customer_id", sparse=True))
    indexes.append(
        col.create_index(
            [("subscription_id", 1)],
            unique=True,
            name="uniq_subscription_id",
            sparse=True,
        )
    )
    return indexes


def get_guild_subscription(settings: Settings | None, *, guild_id: int) -> dict[str, Any] | None:
    col = get_subscription_collection(settings)
    doc = col.find_one({"_id": guild_id})
    return doc if isinstance(doc, dict) else None


def upsert_guild_subscription(
    settings: Settings | None,
    *,
    guild_id: int,
    plan: str,
    status: str,
    period_end: datetime | None,
    customer_id: str | None,
    subscription_id: str | None,
) -> dict[str, Any]:
    col = get_subscription_collection(settings)
    now = _now()
    doc: dict[str, Any] = {
        "_id": guild_id,
        "schema_version": SCHEMA_VERSION,
        "guild_id": guild_id,
        "plan": plan,
        "status": status,
        "period_end": period_end,
        "customer_id": customer_id,
        "subscription_id": subscription_id,
        "updated_at": now,
    }
    col.update_one({"_id": guild_id}, {"$set": doc}, upsert=True)
    return doc

