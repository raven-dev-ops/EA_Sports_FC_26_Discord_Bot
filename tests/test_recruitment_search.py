from __future__ import annotations

from datetime import datetime, timezone

import mongomock

from services.recruitment_service import list_recruit_profile_distinct, search_recruit_profiles


def _collection():
    client = mongomock.MongoClient()
    return client["testdb"]["testcol"]


def test_search_recruit_profiles_filters_and_distinct() -> None:
    col = _collection()
    now = datetime.now(timezone.utc)

    col.insert_many(
        [
            {
                "record_type": "recruit_profile",
                "guild_id": 123,
                "user_id": 1,
                "display_name": "PlayerOne",
                "user_tag": "PlayerOne#0001",
                "main_position": "ST",
                "secondary_position": "RW",
                "main_archetype": "target man",
                "secondary_archetype": "inverted winger",
                "server_name": "na east",
                "timezone": "UTC",
                "availability_days": [0],
                "availability_start_hour": 18,
                "availability_end_hour": 22,
                "updated_at": now,
            },
            {
                "record_type": "recruit_profile",
                "guild_id": 123,
                "user_id": 2,
                "display_name": "PlayerTwo",
                "user_tag": "PlayerTwo#0002",
                "main_position": "CB",
                "secondary_position": None,
                "main_archetype": "ball playing defender",
                "secondary_archetype": None,
                "server_name": "eu",
                "timezone": "UTC",
                "availability_days": [1, 2],
                "availability_start_hour": 19,
                "availability_end_hour": 23,
                "updated_at": now,
            },
            {
                # Different guild should not match
                "record_type": "recruit_profile",
                "guild_id": 999,
                "user_id": 3,
                "display_name": "OtherGuild",
                "main_position": "ST",
                "main_archetype": "target man",
                "server_name": "na east",
                "timezone": "UTC",
                "availability_days": [0],
                "availability_start_hour": 18,
                "availability_end_hour": 22,
                "updated_at": now,
            },
            {
                # Missing availability should not match (not listing-ready)
                "record_type": "recruit_profile",
                "guild_id": 123,
                "user_id": 4,
                "display_name": "NoAvailability",
                "main_position": "ST",
                "main_archetype": "target man",
                "server_name": "na east",
                "timezone": "UTC",
                "updated_at": now,
            },
        ]
    )

    positions = list_recruit_profile_distinct(123, "main_position", limit=10, collection=col)
    assert positions == ["CB", "ST"]

    servers = list_recruit_profile_distinct(123, "server_name", limit=10, collection=col)
    assert servers == ["eu", "na east"]

    results = search_recruit_profiles(123, position="st", collection=col)
    assert [r["user_id"] for r in results] == [1]

    results = search_recruit_profiles(123, position="rw", collection=col)
    assert [r["user_id"] for r in results] == [1]

    results = search_recruit_profiles(123, archetype="ball playing defender", collection=col)
    assert [r["user_id"] for r in results] == [2]

    results = search_recruit_profiles(123, server_name="EU", collection=col)
    assert [r["user_id"] for r in results] == [2]

    results = search_recruit_profiles(123, text_query="playerone", collection=col)
    assert [r["user_id"] for r in results] == [1]

