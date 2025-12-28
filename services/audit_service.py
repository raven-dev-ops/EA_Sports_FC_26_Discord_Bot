from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection


AUDIT_ACTION_APPROVED = "APPROVED"
AUDIT_ACTION_REJECTED = "REJECTED"
AUDIT_ACTION_UNLOCKED = "UNLOCKED"


def record_staff_action(
    *,
    roster_id: Any,
    action: str,
    staff_discord_id: int,
    staff_display_name: str | None = None,
    staff_username: str | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    collection = collection or get_collection()
    now = datetime.now(timezone.utc)
    doc = {
        "record_type": "roster_audit",
        "roster_id": roster_id,
        "action": action,
        "staff_discord_id": staff_discord_id,
        "staff_display_name": staff_display_name,
        "staff_username": staff_username,
        "created_at": now,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc
