from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection
from services.audit_log_service import AUDIT_LOG_RETENTION_DAYS, record_audit_event

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
    guild_id: int | None = None,
    source: str = "unknown",
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
    if AUDIT_LOG_RETENTION_DAYS > 0:
        doc["expires_at"] = now + timedelta(days=AUDIT_LOG_RETENTION_DAYS)
    if details:
        doc["details"] = details
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id

    if guild_id is not None:
        try:
            normalized_action = "_".join(str(action or "").strip().lower().split()) or "unknown"
            audit_details: dict[str, Any] = {"roster_id": roster_id}
            if details:
                audit_details.update(details)
            record_audit_event(
                guild_id=guild_id,
                category="roster",
                action=normalized_action,
                source=source,
                actor_discord_id=staff_discord_id,
                actor_display_name=staff_display_name,
                actor_username=staff_username,
                details=audit_details,
            )
        except Exception:
            pass
    return doc
