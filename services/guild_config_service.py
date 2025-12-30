from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pymongo.collection import Collection

from database import get_collection
from services.audit_log_service import record_audit_event

RECORD_TYPE = "guild_settings"


def _collection(guild_id: int, collection: Optional[Collection] = None) -> Collection:
    if collection is not None:
        return collection
    return get_collection(record_type=RECORD_TYPE, guild_id=guild_id)


def get_guild_config(guild_id: int, *, collection: Optional[Collection] = None) -> dict[str, Any]:
    col = _collection(guild_id, collection)
    doc = col.find_one({"record_type": RECORD_TYPE, "guild_id": guild_id}) or {}
    return doc.get("settings", {})


def set_guild_config(
    guild_id: int,
    settings: dict[str, Any],
    *,
    actor_discord_id: int | None = None,
    actor_display_name: str | None = None,
    actor_username: str | None = None,
    source: str = "unknown",
    collection: Optional[Collection] = None,
) -> None:
    col = _collection(guild_id, collection)
    old_doc = col.find_one({"record_type": RECORD_TYPE, "guild_id": guild_id}) or {}
    old_settings = old_doc.get("settings", {}) if isinstance(old_doc, dict) else {}
    if not isinstance(old_settings, dict):
        old_settings = {}

    changed: list[dict[str, Any]] = []
    sentinel = object()
    keys = set(old_settings.keys()) | set(settings.keys())
    for key in sorted(keys):
        old_value = old_settings.get(key, sentinel)
        new_value = settings.get(key, sentinel)
        if old_value != new_value:
            changed.append(
                {
                    "key": key,
                    "old": None if old_value is sentinel else old_value,
                    "new": None if new_value is sentinel else new_value,
                }
            )

    col.update_one(
        {"record_type": RECORD_TYPE, "guild_id": guild_id},
        {"$set": {"settings": settings, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )

    if changed:
        try:
            record_audit_event(
                guild_id=guild_id,
                category="config",
                action="guild_settings.updated",
                source=source,
                actor_discord_id=actor_discord_id,
                actor_display_name=actor_display_name,
                actor_username=actor_username,
                details={"changed": changed},
            )
        except Exception:
            # Audit logging should never block config writes.
            pass
