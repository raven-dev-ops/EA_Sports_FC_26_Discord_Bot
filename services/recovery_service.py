from __future__ import annotations

import logging
from datetime import datetime, timezone

from pymongo.collection import Collection

from config import load_settings
from database import ensure_indexes, ensure_offside_indexes, get_collection, get_database
from services.roster_service import (
    ROSTER_STATUS_SUBMITTED,
    ROSTER_STATUS_UNLOCKED,
)
from services.submission_service import (
    delete_submission_by_roster,
)


def _now():
    return datetime.now(timezone.utc)


def recover_indexes(collection: Collection | None = None) -> None:
    """
    Recreate required indexes; safe to run on every startup.
    """
    if collection is not None:
        ensure_indexes(collection)
        return
    ensure_offside_indexes(get_database())


def recover_rosters(collection: Collection | None = None) -> int:
    """
    Unlock rosters that are marked submitted but have no submission message record.
    This avoids perma-locked rosters after an unexpected shutdown.
    Returns the number of rosters unlocked.
    """
    if collection is None:
        team_rosters = get_collection(record_type="team_roster")
        submission_messages = get_collection(record_type="submission_message")
    else:
        team_rosters = collection
        submission_messages = collection
    unlocked = 0
    cursor = team_rosters.find({"record_type": "team_roster", "status": ROSTER_STATUS_SUBMITTED})
    for roster in cursor:
        if submission_messages.find_one(
            {"record_type": "submission_message", "roster_id": roster["_id"]}
        ):
            continue
        team_rosters.update_one(
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
        submission_messages = get_collection(record_type="submission_message")
        team_rosters = get_collection(record_type="team_roster")
    else:
        submission_messages = collection
        team_rosters = collection
    removed = 0
    cursor = submission_messages.find({"record_type": "submission_message"})
    for doc in cursor:
        roster = team_rosters.find_one({"record_type": "team_roster", "_id": doc["roster_id"]})
        if roster is None:
            if collection is not None:
                delete_submission_by_roster(doc["roster_id"], collection=collection)
            else:
                submission_messages.delete_one({"_id": doc["_id"]})
            removed += 1
    return removed


def run_startup_recovery(logger: logging.Logger | None = None) -> None:
    """
    Run non-destructive recovery tasks to heal state after restart.
    """
    log = logger or logging.getLogger(__name__)
    settings = load_settings()
    collection = get_collection(settings) if settings.mongodb_collection else None
    recover_indexes(collection)
    unlocked = recover_rosters(collection)
    removed = prune_orphan_submissions(collection)
    if unlocked:
        log.warning("Unlocked %s rosters that were submitted without submission messages.", unlocked)
    if removed:
        log.warning("Pruned %s orphan submission records.", removed)
    if not unlocked and not removed:
        log.info("Recovery check: no actions needed.")
