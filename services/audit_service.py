from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection

RECORD_TYPE = "roster_audit"

AUDIT_ACTION_APPROVED = "APPROVED"
AUDIT_ACTION_REJECTED = "REJECTED"
AUDIT_ACTION_UNLOCKED = "UNLOCKED"
AUDIT_ACTION_TIER_CHANGED = "TIER_CHANGED"
AUDIT_ACTION_CAP_SYNCED = "CAP_SYNCED"
AUDIT_ACTION_CAP_SYNC_SKIPPED = "CAP_SYNC_SKIPPED"


def record_staff_action(
    *,
    roster_id: Any,
    action: str,
    staff_discord_id: int,
    staff_display_name: str | None = None,
    staff_username: str | None = None,
    details: dict[str, Any] | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE)
    now = datetime.now(timezone.utc)
    doc = {
        "record_type": RECORD_TYPE,
        "roster_id": roster_id,
        "action": action,
        "staff_discord_id": staff_discord_id,
        "staff_display_name": staff_display_name,
        "staff_username": staff_username,
        "created_at": now,
    }
    if details:
        doc["details"] = details
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc
