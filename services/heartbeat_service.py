from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from config import Settings, load_settings
from database import get_global_collection

COLLECTION_NAME = "worker_heartbeats"


def _settings_or_default(settings: Settings | None) -> Settings:
    return settings or load_settings()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_heartbeat_collection(settings: Settings | None = None) -> Collection:
    settings = _settings_or_default(settings)
    return get_global_collection(settings, name=COLLECTION_NAME)


def upsert_worker_heartbeat(settings: Settings | None, *, worker: str) -> None:
    settings = _settings_or_default(settings)
    doc: dict[str, Any] = {
        "_id": worker,
        "worker": worker,
        "updated_at": _now(),
        "dyno": os.environ.get("DYNO"),
    }
    get_heartbeat_collection(settings).update_one({"_id": worker}, {"$set": doc}, upsert=True)


def get_worker_heartbeat(settings: Settings | None, *, worker: str) -> dict[str, Any] | None:
    settings = _settings_or_default(settings)
    doc = get_heartbeat_collection(settings).find_one({"_id": worker})
    return doc if isinstance(doc, dict) else None

