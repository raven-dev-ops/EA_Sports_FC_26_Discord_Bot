from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection

RECORD_TYPE = "submission_message"


def create_submission_record(
    *,
    roster_id: Any,
    staff_channel_id: int,
    staff_message_id: int,
    status: str,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE)
    now = datetime.now(timezone.utc)
    doc = {
        "record_type": RECORD_TYPE,
        "roster_id": roster_id,
        "staff_channel_id": staff_channel_id,
        "staff_message_id": staff_message_id,
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_submission_by_roster(
    roster_id: Any, *, collection: Collection | None = None
) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE)
    return collection.find_one({"record_type": RECORD_TYPE, "roster_id": roster_id})


def update_submission_status(
    *,
    roster_id: Any,
    status: str,
    collection: Collection | None = None,
) -> None:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE)
    collection.update_one(
        {"record_type": RECORD_TYPE, "roster_id": roster_id},
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}},
    )


def delete_submission_by_roster(
    roster_id: Any, *, collection: Collection | None = None
) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection(record_type=RECORD_TYPE)
    doc = collection.find_one({"record_type": RECORD_TYPE, "roster_id": roster_id})
    if doc:
        collection.delete_one({"_id": doc["_id"]})
    return doc
