from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection

RECORD_TYPE = "recruit_profile"


def _listing_ready_filter() -> dict[str, Any]:
    return {
        "availability_days": {"$exists": True, "$ne": []},
        "availability_start_hour": {"$exists": True},
        "availability_end_hour": {"$exists": True},
        "timezone": {"$exists": True, "$nin": [None, ""]},
    }


def recruit_profile_is_listing_ready(profile: dict[str, Any]) -> bool:
    days = profile.get("availability_days")
    if not isinstance(days, list) or not days:
        return False
    if profile.get("availability_start_hour") is None:
        return False
    if profile.get("availability_end_hour") is None:
        return False
    tz = profile.get("timezone")
    return bool(isinstance(tz, str) and tz.strip())


def get_recruit_profile(
    guild_id: int,
    user_id: int,
    *,
    collection: Collection | None = None,
) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE, guild_id=guild_id)
    return collection.find_one(
        {"record_type": RECORD_TYPE, "guild_id": guild_id, "user_id": user_id}
    )


def upsert_recruit_profile(
    guild_id: int,
    user_id: int,
    *,
    profile: dict[str, Any],
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE, guild_id=guild_id)
    now = datetime.now(timezone.utc)
    filter_doc = {"record_type": RECORD_TYPE, "guild_id": guild_id, "user_id": user_id}
    update_doc = {
        "$set": {**profile, "updated_at": now},
        "$setOnInsert": {"record_type": RECORD_TYPE, "guild_id": guild_id, "user_id": user_id, "created_at": now},
    }
    collection.update_one(filter_doc, update_doc, upsert=True)
    doc = collection.find_one(filter_doc)
    if doc is None:
        raise RuntimeError("Failed to upsert recruit profile.")
    return doc


def search_recruit_profiles(
    guild_id: int,
    *,
    position: str | None = None,
    archetype: str | None = None,
    platform: str | None = None,
    mic: bool | None = None,
    server_name: str | None = None,
    text_query: str | None = None,
    limit: int = 25,
    offset: int = 0,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE, guild_id=guild_id)

    position_value = position.strip().upper() if isinstance(position, str) and position.strip() else None
    archetype_value = (
        archetype.strip().lower() if isinstance(archetype, str) and archetype.strip() else None
    )
    platform_value = platform.strip().upper() if isinstance(platform, str) and platform.strip() else None
    server_value = (
        server_name.strip().lower() if isinstance(server_name, str) and server_name.strip() else None
    )
    search_value = text_query.strip() if isinstance(text_query, str) and text_query.strip() else None

    and_filters: list[dict[str, Any]] = [
        {"record_type": RECORD_TYPE, "guild_id": guild_id},
        _listing_ready_filter(),
    ]

    if position_value:
        and_filters.append(
            {"$or": [{"main_position": position_value}, {"secondary_position": position_value}]}
        )
    if archetype_value:
        and_filters.append(
            {"$or": [{"main_archetype": archetype_value}, {"secondary_archetype": archetype_value}]}
        )
    if platform_value:
        and_filters.append({"platform": platform_value})
    if mic is not None:
        and_filters.append({"mic": bool(mic)})
    if server_value:
        and_filters.append({"server_name": server_value})

    if search_value:
        escaped = re.escape(search_value)
        and_filters.append(
            {
                "$or": [
                    {"display_name": {"$regex": escaped, "$options": "i"}},
                    {"user_tag": {"$regex": escaped, "$options": "i"}},
                    {"notes": {"$regex": escaped, "$options": "i"}},
                ]
            }
        )

    query: dict[str, Any] = {"$and": and_filters} if len(and_filters) > 1 else and_filters[0]
    cursor = collection.find(query).sort("updated_at", -1).skip(int(offset)).limit(int(limit))
    return list(cursor)


def list_recruit_profile_distinct(
    guild_id: int,
    field: str,
    *,
    limit: int = 24,
    collection: Collection | None = None,
) -> list[str]:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE, guild_id=guild_id)
    query = {"record_type": RECORD_TYPE, "guild_id": guild_id, **_listing_ready_filter()}
    values = [v for v in collection.distinct(field, query) if isinstance(v, str) and v.strip()]
    values = sorted(set(values), key=lambda v: v.casefold())
    return values[: max(0, int(limit))]


def update_recruit_profile_posts(
    guild_id: int,
    user_id: int,
    *,
    listing_channel_id: int | None,
    listing_message_id: int | None,
    staff_channel_id: int | None,
    staff_message_id: int | None,
    collection: Collection | None = None,
) -> None:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE, guild_id=guild_id)
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {
        "updated_at": now,
        "listing_channel_id": listing_channel_id,
        "listing_message_id": listing_message_id,
        "staff_channel_id": staff_channel_id,
        "staff_message_id": staff_message_id,
    }
    collection.update_one(
        {"record_type": RECORD_TYPE, "guild_id": guild_id, "user_id": user_id},
        {"$set": updates},
    )


def update_recruit_profile_availability(
    guild_id: int,
    user_id: int,
    *,
    availability_days: list[int],
    availability_start_hour: int,
    availability_end_hour: int,
    collection: Collection | None = None,
) -> None:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE, guild_id=guild_id)
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {
        "updated_at": now,
        "availability_days": availability_days,
        "availability_start_hour": availability_start_hour,
        "availability_end_hour": availability_end_hour,
    }
    collection.update_one(
        {"record_type": RECORD_TYPE, "guild_id": guild_id, "user_id": user_id},
        {"$set": updates},
    )


def delete_recruit_profile(
    guild_id: int,
    user_id: int,
    *,
    collection: Collection | None = None,
) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE, guild_id=guild_id)
    doc = get_recruit_profile(guild_id, user_id, collection=collection)
    if not doc:
        return None
    collection.delete_one({"record_type": RECORD_TYPE, "_id": doc["_id"]})
    return doc
