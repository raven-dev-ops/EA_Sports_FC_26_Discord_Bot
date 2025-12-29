from __future__ import annotations

import logging
from datetime import datetime, timezone

from pymongo.collection import Collection

from database import get_collection, ensure_indexes
from services.roster_service import (
    ROSTER_STATUS_SUBMITTED,
    ROSTER_STATUS_UNLOCKED,
)
from services.submission_service import (
    get_submission_by_roster,
    delete_submission_by_roster,
)


def _now():
    return datetime.now(timezone.utc)


def recover_indexes(collection: Collection | None = None) -> None:
    """
    Recreate required indexes; safe to run on every startup.
    """
    if collection is None:
        collection = get_collection()
    ensure_indexes(collection)


def recover_rosters(collection: Collection | None = None) -> int:
    """
    Unlock rosters that are marked submitted but have no submission message record.
    This avoids perma-locked rosters after an unexpected shutdown.
    Returns the number of rosters unlocked.
    """
    if collection is None:
        collection = get_collection()
    unlocked = 0
    cursor = collection.find(
        {"record_type": "team_roster", "status": ROSTER_STATUS_SUBMITTED}
    )
    for roster in cursor:
        if get_submission_by_roster(roster["_id"], collection=collection):
            continue
        collection.update_one(
            {"_id": roster["_id"]},
            {
                "$set": {
                    "status": ROSTER_STATUS_UNLOCKED,
                    "submitted_at": None,
                    "updated_at": _now(),
                }
            },
        )
        unlocked += 1
    return unlocked


def prune_orphan_submissions(collection: Collection | None = None) -> int:
    """
    Remove submission records that reference missing rosters.
    """
    if collection is None:
        collection = get_collection()
    removed = 0
    cursor = collection.find({"record_type": "submission_message"})
    for doc in cursor:
        roster = collection.find_one({"record_type": "team_roster", "_id": doc["roster_id"]})
        if roster is None:
            delete_submission_by_roster(doc["roster_id"], collection=collection)
            removed += 1
    return removed


def run_startup_recovery(logger: logging.Logger | None = None) -> None:
    """
    Run non-destructive recovery tasks to heal state after restart.
    """
    log = logger or logging.getLogger(__name__)
    collection = get_collection()
    recover_indexes(collection)
    unlocked = recover_rosters(collection)
    removed = prune_orphan_submissions(collection)
    if unlocked:
        log.warning("Unlocked %s rosters that were submitted without submission messages.", unlocked)
    if removed:
        log.warning("Pruned %s orphan submission records.", removed)
    if not unlocked and not removed:
        log.info("Recovery check: no actions needed.")
