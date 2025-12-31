from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from pymongo.collection import Collection

from config import Settings, load_settings
from database import get_global_collection

COLLECTION_NAME = "guild_installs"
SCHEMA_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _settings_or_default(settings: Settings | None) -> Settings:
    return settings or load_settings()


def get_guild_install_collection(settings: Settings | None = None) -> Collection:
    settings = _settings_or_default(settings)
    return get_global_collection(settings, name=COLLECTION_NAME)


def ensure_guild_install_indexes(settings: Settings | None = None) -> list[str]:
    col = get_guild_install_collection(settings)
    indexes: list[str] = []
    indexes.append(col.create_index([("guild_id", 1)], unique=True, name="uniq_guild_id"))
    indexes.append(col.create_index([("installed", 1)], name="idx_installed"))
    indexes.append(col.create_index([("updated_at", -1)], name="idx_updated_at"))
    return indexes


def mark_guild_install(
    settings: Settings | None,
    *,
    guild_id: int,
    installed: bool,
    guild_name: str | None = None,
) -> dict[str, Any]:
    col = get_guild_install_collection(settings)
    now = _now()
    doc: dict[str, Any] = {
        "_id": int(guild_id),
        "schema_version": SCHEMA_VERSION,
        "guild_id": int(guild_id),
        "installed": bool(installed),
        "updated_at": now,
    }
    if guild_name:
        doc["guild_name"] = str(guild_name)
    col.update_one({"_id": int(guild_id)}, {"$set": doc}, upsert=True)
    return doc


def refresh_guild_installs(
    settings: Settings | None,
    *,
    guilds: Iterable[tuple[int, str | None]],
) -> None:
    col = get_guild_install_collection(settings)
    now = _now()
    for guild_id, guild_name in guilds:
        doc: dict[str, Any] = {
            "_id": int(guild_id),
            "schema_version": SCHEMA_VERSION,
            "guild_id": int(guild_id),
            "installed": True,
            "updated_at": now,
        }
        if guild_name:
            doc["guild_name"] = str(guild_name)
        col.update_one({"_id": int(guild_id)}, {"$set": doc}, upsert=True)


def list_guild_installs(
    settings: Settings | None,
    *,
    guild_ids: Iterable[int],
) -> dict[int, dict[str, Any]]:
    ids = [int(gid) for gid in guild_ids if str(gid).isdigit()]
    if not ids:
        return {}
    col = get_guild_install_collection(settings)
    docs = col.find({"_id": {"$in": ids}})
    result: dict[int, dict[str, Any]] = {}
    for doc in docs:
        if isinstance(doc, dict):
            gid = doc.get("_id")
            if isinstance(gid, int):
                result[gid] = doc
    return result
