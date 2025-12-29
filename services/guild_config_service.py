from __future__ import annotations

from typing import Any, Optional

from pymongo.collection import Collection

from database import get_collection

RECORD_TYPE = "guild_settings"


def _collection(collection: Optional[Collection] = None) -> Collection:
    return collection or get_collection()


def get_guild_config(guild_id: int, *, collection: Optional[Collection] = None) -> dict[str, Any]:
    col = _collection(collection)
    doc = col.find_one({"record_type": RECORD_TYPE, "guild_id": guild_id}) or {}
    return doc.get("settings", {})


def set_guild_config(
    guild_id: int,
    settings: dict[str, Any],
    *,
    collection: Optional[Collection] = None,
) -> None:
    col = _collection(collection)
    col.update_one(
        {"record_type": RECORD_TYPE, "guild_id": guild_id},
        {"$set": {"settings": settings}},
        upsert=True,
    )
