import mongomock

from services import recovery_service as rs
from services.roster_service import (
    ROSTER_STATUS_SUBMITTED,
    ROSTER_STATUS_UNLOCKED,
)


def _collection():
    client = mongomock.MongoClient()
    return client["test_db"]["col"]


def test_recover_rosters_unlocks_missing_submission_records():
    collection = _collection()
    roster_id = collection.insert_one(
        {
            "record_type": "team_roster",
            "status": ROSTER_STATUS_SUBMITTED,
            "cycle_id": 1,
            "coach_discord_id": 1,
        }
    ).inserted_id

    unlocked = rs.recover_rosters(collection)
    assert unlocked == 1
    roster = collection.find_one({"_id": roster_id})
    assert roster["status"] == ROSTER_STATUS_UNLOCKED


def test_prune_orphan_submissions_removes_entries():
    collection = _collection()
    # Submission references missing roster
    collection.insert_one(
        {"record_type": "submission_message", "roster_id": "missing"}
    )
    removed = rs.prune_orphan_submissions(collection)
    assert removed == 1
    assert collection.count_documents({"record_type": "submission_message"}) == 0
