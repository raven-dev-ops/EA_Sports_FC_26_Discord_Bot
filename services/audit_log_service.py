from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection

RECORD_TYPE = "audit_event"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def record_audit_event(
    *,
    guild_id: int,
    category: str,
    action: str,
    source: str,
    actor_discord_id: int | None = None,
    actor_display_name: str | None = None,
    actor_username: str | None = None,
    details: dict[str, Any] | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE, guild_id=guild_id)

    doc: dict[str, Any] = {
        "record_type": RECORD_TYPE,
        "guild_id": guild_id,
        "category": str(category or "").strip() or "unknown",
        "action": str(action or "").strip() or "unknown",
        "source": str(source or "").strip() or "unknown",
        "created_at": _utc_now(),
    }
    if actor_discord_id is not None:
        doc["actor_discord_id"] = actor_discord_id
    if actor_display_name:
        doc["actor_display_name"] = str(actor_display_name)
    if actor_username:
        doc["actor_username"] = str(actor_username)
    if details:
        doc["details"] = details

    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def list_audit_events(
    *,
    guild_id: int,
    limit: int = 200,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE, guild_id=guild_id)

    safe_limit = max(1, min(500, int(limit)))
    cursor = (
        collection.find({"record_type": RECORD_TYPE, "guild_id": guild_id})
        .sort("created_at", -1)
        .limit(safe_limit)
    )
    return [doc for doc in cursor if isinstance(doc, dict)]

