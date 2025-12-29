from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection

LINK_RECORD_TYPE = "fc25_stats_link"
SNAPSHOT_RECORD_TYPE = "fc25_stats_snapshot"


def get_link(
    guild_id: int,
    user_id: int,
    *,
    collection: Collection | None = None,
) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection()
    return collection.find_one(
        {"record_type": LINK_RECORD_TYPE, "guild_id": guild_id, "user_id": user_id}
    )


def list_links(
    guild_id: int,
    *,
    verified_only: bool = True,
    limit: int = 200,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    query: dict[str, Any] = {"record_type": LINK_RECORD_TYPE, "guild_id": guild_id}
    if verified_only:
        query["verified"] = True
    cursor = collection.find(query).sort("updated_at", -1).limit(int(limit))
    return list(cursor)


def upsert_link(
    guild_id: int,
    user_id: int,
    *,
    platform_key: str,
    club_id: int,
    club_name: str | None,
    member_name: str,
    verified: bool,
    verified_at: datetime | None = None,
    last_fetched_at: datetime | None = None,
    last_fetch_status: str | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    now = datetime.now(timezone.utc)
    filter_doc = {"record_type": LINK_RECORD_TYPE, "guild_id": guild_id, "user_id": user_id}
    update_doc = {
        "$set": {
            "platform_key": platform_key,
            "club_id": club_id,
            "club_name": club_name,
            "member_name": member_name,
            "verified": bool(verified),
            "verified_at": verified_at,
            "last_fetched_at": last_fetched_at,
            "last_fetch_status": last_fetch_status,
            "updated_at": now,
        },
        "$setOnInsert": {
            "record_type": LINK_RECORD_TYPE,
            "guild_id": guild_id,
            "user_id": user_id,
            "created_at": now,
        },
    }
    collection.update_one(filter_doc, update_doc, upsert=True)
    doc = collection.find_one(filter_doc)
    if doc is None:
        raise RuntimeError("Failed to upsert FC25 stats link.")
    return doc


def delete_link(
    guild_id: int,
    user_id: int,
    *,
    collection: Collection | None = None,
) -> bool:
    if collection is None:
        collection = get_collection()
    result = collection.delete_one(
        {"record_type": LINK_RECORD_TYPE, "guild_id": guild_id, "user_id": user_id}
    )
    return result.deleted_count > 0


def delete_snapshots(
    guild_id: int,
    user_id: int,
    *,
    collection: Collection | None = None,
) -> int:
    if collection is None:
        collection = get_collection()
    result = collection.delete_many(
        {"record_type": SNAPSHOT_RECORD_TYPE, "guild_id": guild_id, "user_id": user_id}
    )
    return int(result.deleted_count or 0)


def save_snapshot(
    guild_id: int,
    user_id: int,
    *,
    platform_key: str,
    club_id: int,
    snapshot: dict[str, Any],
    fetched_at: datetime | None = None,
    retention_days: int = 30,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    if fetched_at is None:
        fetched_at = datetime.now(timezone.utc)
    doc = {
        "record_type": SNAPSHOT_RECORD_TYPE,
        "guild_id": guild_id,
        "user_id": user_id,
        "platform_key": platform_key,
        "club_id": club_id,
        "snapshot": snapshot,
        "fetched_at": fetched_at,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id

    if retention_days > 0:
        cutoff = fetched_at - timedelta(days=retention_days)
        collection.delete_many(
            {
                "record_type": SNAPSHOT_RECORD_TYPE,
                "guild_id": guild_id,
                "user_id": user_id,
                "fetched_at": {"$lt": cutoff},
            }
        )

    return doc


def get_latest_snapshot(
    guild_id: int,
    user_id: int,
    *,
    collection: Collection | None = None,
) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection()
    return collection.find_one(
        {"record_type": SNAPSHOT_RECORD_TYPE, "guild_id": guild_id, "user_id": user_id},
        sort=[("fetched_at", -1)],
    )
