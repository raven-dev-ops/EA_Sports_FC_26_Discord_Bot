import mongomock

from services.submission_service import (
    create_submission_record,
    delete_submission_by_roster,
    get_submission_by_roster,
    update_submission_status,
)


def _collection():
    client = mongomock.MongoClient()
    return client["test_db"]["test_collection"]


def test_create_and_delete_submission_record() -> None:
    collection = _collection()
    doc = create_submission_record(
        roster_id="r1",
        staff_channel_id=123,
        staff_message_id=456,
        status="PENDING",
        collection=collection,
    )

    fetched = get_submission_by_roster("r1", collection=collection)
    assert fetched is not None
    assert fetched["status"] == "PENDING"

    update_submission_status(roster_id="r1", status="APPROVED", collection=collection)
    updated = get_submission_by_roster("r1", collection=collection)
    assert updated["status"] == "APPROVED"

    removed = delete_submission_by_roster("r1", collection=collection)
    assert removed is not None
    assert removed["_id"] == doc["_id"]
    assert get_submission_by_roster("r1", collection=collection) is None
