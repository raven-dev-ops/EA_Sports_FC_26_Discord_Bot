from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from config import Settings
from database import get_collection, get_database, list_record_types


@dataclass(frozen=True)
class GuildAnalytics:
    guild_id: int
    db_name: str
    generated_at: datetime
    record_type_counts: dict[str, int]
    collections: dict[str, dict[str, Any]]


def _count_record_type(settings: Settings, *, guild_id: int, record_type: str) -> int:
    col = get_collection(settings, record_type=record_type, guild_id=guild_id)
    return int(col.count_documents({"record_type": record_type}))


def _safe_collection_stats(col: Collection) -> dict[str, Any]:
    """
    Best-effort stats for a collection without requiring admin privileges.
    """
    stats: dict[str, Any] = {"name": str(getattr(col, "name", ""))}
    try:
        stats["count"] = int(col.estimated_document_count())
    except Exception:
        try:
            stats["count"] = int(col.count_documents({}))
        except Exception:
            stats["count"] = None
    return stats


def get_guild_analytics(settings: Settings, *, guild_id: int) -> GuildAnalytics:
    """
    Compute high-level analytics for a single guild.

    Works in both shared-DB and per-guild-DB modes.
    """
    db = get_database(settings, guild_id=guild_id)
    now = datetime.now(timezone.utc)

    record_type_counts: dict[str, int] = {}
    for record_type in list_record_types():
        try:
            record_type_counts[record_type] = _count_record_type(
                settings, guild_id=guild_id, record_type=record_type
            )
        except Exception:
            record_type_counts[record_type] = 0

    collections: dict[str, dict[str, Any]] = {}
    try:
        for name in sorted(db.list_collection_names()):
            try:
                collections[name] = _safe_collection_stats(db[name])
            except Exception:
                collections[name] = {"name": name, "count": None}
    except Exception:
        collections = {}

    return GuildAnalytics(
        guild_id=guild_id,
        db_name=str(db.name),
        generated_at=now,
        record_type_counts=record_type_counts,
        collections=collections,
    )

