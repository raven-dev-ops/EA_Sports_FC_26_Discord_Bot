from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection

RECORD_TYPE = "club_ad"


def get_club_ad(
    guild_id: int,
    owner_id: int,
    *,
    collection: Collection | None = None,
) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE)
    return collection.find_one(
        {"record_type": RECORD_TYPE, "guild_id": guild_id, "owner_id": owner_id}
    )


def upsert_club_ad(
    guild_id: int,
    owner_id: int,
    *,
    ad: dict[str, Any],
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE)
    now = datetime.now(timezone.utc)
    filter_doc = {"record_type": RECORD_TYPE, "guild_id": guild_id, "owner_id": owner_id}
    update_doc = {
        "$set": {**ad, "updated_at": now},
        "$setOnInsert": {"record_type": RECORD_TYPE, "guild_id": guild_id, "owner_id": owner_id, "created_at": now},
    }
    collection.update_one(filter_doc, update_doc, upsert=True)
    doc = collection.find_one(filter_doc)
    if doc is None:
        raise RuntimeError("Failed to upsert club ad.")
    return doc


def update_club_ad_posts(
    guild_id: int,
    owner_id: int,
    *,
    listing_channel_id: int | None,
    listing_message_id: int | None,
    staff_channel_id: int | None,
    staff_message_id: int | None,
    collection: Collection | None = None,
) -> None:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE)
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {
        "updated_at": now,
        "listing_channel_id": listing_channel_id,
        "listing_message_id": listing_message_id,
        "staff_channel_id": staff_channel_id,
        "staff_message_id": staff_message_id,
    }
    collection.update_one(
        {"record_type": RECORD_TYPE, "guild_id": guild_id, "owner_id": owner_id},
        {"$set": updates},
    )


def set_club_ad_approval(
    guild_id: int,
    owner_id: int,
    *,
    status: str,
    staff_discord_id: int,
    reason: str | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE)
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {
        "updated_at": now,
        "approval_status": status,
        "approval_staff_discord_id": staff_discord_id,
        "approval_reason": reason,
        "approval_at": now,
    }
    collection.update_one(
        {"record_type": RECORD_TYPE, "guild_id": guild_id, "owner_id": owner_id},
        {"$set": updates},
    )
    doc = get_club_ad(guild_id, owner_id, collection=collection)
    if doc is None:
        raise RuntimeError("Club ad not found after approval update.")
    return doc


def delete_club_ad(
    guild_id: int,
    owner_id: int,
    *,
    collection: Collection | None = None,
) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE)
    doc = get_club_ad(guild_id, owner_id, collection=collection)
    if not doc:
        return None
    collection.delete_one({"record_type": RECORD_TYPE, "_id": doc["_id"]})
    return doc
