from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection
from services.audit_log_service import AUDIT_LOG_RETENTION_DAYS, record_audit_event

RECORD_TYPE = "club_ad_audit"

CLUB_AD_ACTION_APPROVED = "APPROVED"
CLUB_AD_ACTION_REJECTED = "REJECTED"


def record_club_ad_action(
    *,
    guild_id: int,
    owner_id: int,
    action: str,
    staff_discord_id: int,
    staff_display_name: str | None = None,
    staff_username: str | None = None,
    source: str = "unknown",
    reason: str | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE, guild_id=guild_id)
    now = datetime.now(timezone.utc)
    doc = {
        "record_type": RECORD_TYPE,
        "guild_id": guild_id,
        "owner_id": owner_id,
        "action": action,
        "staff_discord_id": staff_discord_id,
        "reason": reason,
        "created_at": now,
    }
    if AUDIT_LOG_RETENTION_DAYS > 0:
        doc["expires_at"] = now + timedelta(days=AUDIT_LOG_RETENTION_DAYS)
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id

    try:
        normalized_action = "_".join(str(action or "").strip().lower().split()) or "unknown"
        details: dict[str, Any] = {"owner_id": owner_id}
        if reason:
            details["reason"] = reason
        record_audit_event(
            guild_id=guild_id,
            category="club_ad",
            action=normalized_action,
            source=source,
            actor_discord_id=staff_discord_id,
            actor_display_name=staff_display_name,
            actor_username=staff_username,
            details=details,
        )
    except Exception:
        pass

    return doc
