from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection


def get_active_cycle(collection: Collection | None = None) -> dict[str, Any] | None:
    collection = collection or get_collection()
    return collection.find_one({"record_type": "tournament_cycle", "is_active": True})


def create_cycle(
    name: str,
    *,
    is_active: bool = True,
    collection: Collection | None = None,
) -> dict[str, Any]:
    collection = collection or get_collection()
    now = datetime.now(timezone.utc)

    if is_active:
        collection.update_many(
            {"record_type": "tournament_cycle", "is_active": True},
            {"$set": {"is_active": False, "updated_at": now}},
        )

    doc = {
        "record_type": "tournament_cycle",
        "name": name,
        "is_active": is_active,
        "created_at": now,
        "updated_at": now,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def ensure_active_cycle(
    *,
    default_name: str = "Current Tournament",
    collection: Collection | None = None,
) -> dict[str, Any]:
    collection = collection or get_collection()
    cycle = get_active_cycle(collection)
    if cycle:
        return cycle
    return create_cycle(default_name, is_active=True, collection=collection)
