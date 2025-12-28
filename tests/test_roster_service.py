import mongomock
import pytest

from services.roster_service import add_player, create_roster


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
