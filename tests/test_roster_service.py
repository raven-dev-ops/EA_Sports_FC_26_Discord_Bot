import mongomock
import pytest

from services.roster_service import (
    ROSTER_STATUS_DRAFT,
    ROSTER_STATUS_SUBMITTED,
    ROSTER_STATUS_UNLOCKED,
    add_player,
    create_roster,
    get_roster_by_id,
    set_roster_status,
)


def _collection():
    client = mongomock.MongoClient()
    return client["test_db"]["test_collection"]


def test_duplicate_player_rejected() -> None:
    collection = _collection()
    roster = create_roster(
        coach_discord_id=1,
        team_name="TeamOne",
        cap=2,
        collection=collection,
    )

    add_player(
        roster_id=roster["_id"],
        player_discord_id=100,
        gamertag="PlayerOne",
        ea_id="EA1",
        console="PS",
        cap=2,
        collection=collection,
    )

    with pytest.raises(RuntimeError, match="already on this roster"):
        add_player(
            roster_id=roster["_id"],
            player_discord_id=100,
            gamertag="PlayerOne",
            ea_id="EA1",
            console="PS",
            cap=2,
            collection=collection,
        )


def test_cap_enforced() -> None:
    collection = _collection()
    roster = create_roster(
        coach_discord_id=2,
        team_name="TeamTwo",
        cap=1,
        collection=collection,
    )

    add_player(
        roster_id=roster["_id"],
        player_discord_id=200,
        gamertag="PlayerTwo",
        ea_id="EA2",
        console="XBOX",
        cap=1,
        collection=collection,
    )

    with pytest.raises(RuntimeError, match="Roster cap reached"):
        add_player(
            roster_id=roster["_id"],
        player_discord_id=201,
        gamertag="PlayerThree",
        ea_id="EA3",
        console="PC",
        cap=1,
        collection=collection,
    )


def test_submitted_at_reset_on_unlock_and_draft() -> None:
    collection = _collection()
    roster = create_roster(
        coach_discord_id=3,
        team_name="TeamThree",
        cap=5,
        collection=collection,
    )

    set_roster_status(roster["_id"], ROSTER_STATUS_SUBMITTED, collection=collection)
    submitted = get_roster_by_id(roster["_id"], collection=collection)
    assert submitted["submitted_at"] is not None

    set_roster_status(roster["_id"], ROSTER_STATUS_UNLOCKED, collection=collection)
    unlocked = get_roster_by_id(roster["_id"], collection=collection)
    assert unlocked["submitted_at"] is None

    set_roster_status(roster["_id"], ROSTER_STATUS_DRAFT, collection=collection)
    draft = get_roster_by_id(roster["_id"], collection=collection)
    assert draft["submitted_at"] is None
