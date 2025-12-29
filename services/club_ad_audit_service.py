from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection

CLUB_AD_ACTION_APPROVED = "APPROVED"
CLUB_AD_ACTION_REJECTED = "REJECTED"


def record_club_ad_action(
    *,
    guild_id: int,
    owner_id: int,
    action: str,
    staff_discord_id: int,
    reason: str | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    now = datetime.now(timezone.utc)
    doc = {
        "record_type": "club_ad_audit",
        "guild_id": guild_id,
        "owner_id": owner_id,
        "action": action,
        "staff_discord_id": staff_discord_id,
        "reason": reason,
        "created_at": now,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc

