from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any, Final

from pymongo import ReturnDocument
from pymongo.collection import Collection

from config import Settings
from database import get_global_collection

OPS_TASKS_COLLECTION: Final[str] = "ops_tasks"
OPS_TASKS_RETENTION_DAYS = int(os.environ.get("OPS_TASKS_RETENTION_DAYS", "30").strip() or "30")

OPS_TASK_STATUS_QUEUED: Final[str] = "queued"
OPS_TASK_STATUS_RUNNING: Final[str] = "running"
OPS_TASK_STATUS_SUCCEEDED: Final[str] = "succeeded"
OPS_TASK_STATUS_FAILED: Final[str] = "failed"
OPS_TASK_STATUS_CANCELED: Final[str] = "canceled"

OPS_TASK_ACTION_RUN_SETUP: Final[str] = "run_setup"
OPS_TASK_ACTION_REPOST_PORTALS: Final[str] = "repost_portals"
OPS_TASK_ACTION_DELETE_GUILD_DATA: Final[str] = "delete_guild_data"
OPS_TASK_ACTION_EXPORT_GUILD_DATA: Final[str] = "export_guild_data"

OPS_TASK_ACTIONS: set[str] = {
    OPS_TASK_ACTION_RUN_SETUP,
    OPS_TASK_ACTION_REPOST_PORTALS,
    OPS_TASK_ACTION_DELETE_GUILD_DATA,
    OPS_TASK_ACTION_EXPORT_GUILD_DATA,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_ops_task_indexes(settings: Settings) -> None:
    col = get_global_collection(settings, name=OPS_TASKS_COLLECTION)
    col.create_index([("status", 1), ("created_at", 1)], name="idx_status_created_at")
    col.create_index([("guild_id", 1), ("created_at", -1)], name="idx_guild_created_at")
    col.create_index([("run_after", 1), ("created_at", 1)], name="idx_run_after_created_at", sparse=True)
    if OPS_TASKS_RETENTION_DAYS > 0:
        ttl_seconds = OPS_TASKS_RETENTION_DAYS * 24 * 60 * 60
        col.create_index("created_at", expireAfterSeconds=ttl_seconds, name="ttl_created_at")
    col.create_index(
        [("guild_id", 1), ("action", 1)],
        unique=True,
        name="uniq_active_task",
        partialFilterExpression={"active": True},
    )


def enqueue_ops_task(
    settings: Settings,
    *,
    guild_id: int,
    action: str,
    requested_by_discord_id: int | None,
    requested_by_username: str | None,
    run_after: datetime | None = None,
    source: str = "dashboard",
    collection: Collection | None = None,
) -> dict[str, Any]:
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in OPS_TASK_ACTIONS:
        raise ValueError(f"Unsupported ops task action: {action!r}")

    col = collection or get_global_collection(settings, name=OPS_TASKS_COLLECTION)
    now = _utc_now()
    task_id = secrets.token_urlsafe(18)
    doc: dict[str, Any] = {
        "_id": task_id,
        "guild_id": int(guild_id),
        "action": normalized_action,
        "status": OPS_TASK_STATUS_QUEUED,
        "active": True,
        "created_at": now,
        "updated_at": now,
        "requested_by_discord_id": requested_by_discord_id,
        "requested_by_username": requested_by_username,
        "source": source,
    }
    if run_after is not None:
        if run_after.tzinfo is None:
            run_after = run_after.replace(tzinfo=timezone.utc)
        doc["run_after"] = run_after

    result = col.find_one_and_update(
        {"guild_id": int(guild_id), "action": normalized_action, "active": True},
        {"$setOnInsert": doc},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if not isinstance(result, dict):
        raise RuntimeError("MongoDB did not return an ops task document.")
    return result


def list_ops_tasks(
    settings: Settings,
    *,
    guild_id: int,
    limit: int = 25,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    col = collection or get_global_collection(settings, name=OPS_TASKS_COLLECTION)
    safe_limit = max(1, min(100, int(limit)))
    cursor = col.find({"guild_id": int(guild_id)}).sort("created_at", -1).limit(safe_limit)
    return [doc for doc in cursor if isinstance(doc, dict)]


def claim_next_ops_task(
    settings: Settings,
    *,
    worker: str,
    collection: Collection | None = None,
) -> dict[str, Any] | None:
    col = collection or get_global_collection(settings, name=OPS_TASKS_COLLECTION)
    now = _utc_now()
    doc = col.find_one_and_update(
        {
            "status": OPS_TASK_STATUS_QUEUED,
            "active": True,
            "$or": [{"run_after": {"$exists": False}}, {"run_after": {"$lte": now}}],
        },
        {"$set": {"status": OPS_TASK_STATUS_RUNNING, "started_at": now, "updated_at": now, "worker": worker}},
        sort=[("run_after", 1), ("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )
    return doc if isinstance(doc, dict) else None


def mark_ops_task_succeeded(
    settings: Settings,
    *,
    task_id: str,
    result: dict[str, Any] | None = None,
    collection: Collection | None = None,
) -> None:
    col = collection or get_global_collection(settings, name=OPS_TASKS_COLLECTION)
    now = _utc_now()
    update: dict[str, Any] = {
        "status": OPS_TASK_STATUS_SUCCEEDED,
        "active": False,
        "finished_at": now,
        "updated_at": now,
    }
    if result is not None:
        update["result"] = result
    col.update_one({"_id": str(task_id)}, {"$set": update})


def mark_ops_task_failed(
    settings: Settings,
    *,
    task_id: str,
    error: str,
    collection: Collection | None = None,
) -> None:
    col = collection or get_global_collection(settings, name=OPS_TASKS_COLLECTION)
    now = _utc_now()
    col.update_one(
        {"_id": str(task_id)},
        {
            "$set": {
                "status": OPS_TASK_STATUS_FAILED,
                "active": False,
                "finished_at": now,
                "updated_at": now,
                "error": str(error or "unknown_error")[:2000],
            }
        },
    )


def get_active_ops_task(
    settings: Settings,
    *,
    guild_id: int,
    action: str,
    collection: Collection | None = None,
) -> dict[str, Any] | None:
    normalized_action = str(action or "").strip().lower()
    col = collection or get_global_collection(settings, name=OPS_TASKS_COLLECTION)
    doc = col.find_one({"guild_id": int(guild_id), "action": normalized_action, "active": True})
    return doc if isinstance(doc, dict) else None


def cancel_ops_task(
    settings: Settings,
    *,
    guild_id: int,
    action: str,
    collection: Collection | None = None,
) -> bool:
    normalized_action = str(action or "").strip().lower()
    col = collection or get_global_collection(settings, name=OPS_TASKS_COLLECTION)
    now = _utc_now()
    result = col.update_one(
        {"guild_id": int(guild_id), "action": normalized_action, "active": True, "status": OPS_TASK_STATUS_QUEUED},
        {
            "$set": {
                "status": OPS_TASK_STATUS_CANCELED,
                "active": False,
                "canceled_at": now,
                "updated_at": now,
            }
        },
    )
    return result.matched_count > 0
