from __future__ import annotations

from datetime import datetime, timezone

import mongomock
import pytest

import database
from config.settings import Settings
from services.guild_data_service import delete_guild_data
from services.stripe_webhook_service import (
    STRIPE_DEAD_LETTERS_COLLECTION,
    STRIPE_EVENTS_COLLECTION,
)
from services.subscription_service import COLLECTION_NAME as SUBSCRIPTIONS_COLLECTION


def _settings(*, per_guild: bool) -> Settings:
    return Settings(
        discord_token="token",
        discord_application_id=1,
        discord_client_id=None,
        discord_public_key=None,
        interactions_endpoint_url=None,
        test_mode=True,
        role_broskie_id=None,
        role_team_coach_id=None,
        role_club_manager_id=None,
        role_league_staff_id=None,
        role_league_owner_id=None,
        role_free_agent_id=None,
        role_pro_player_id=None,
        role_retired_id=None,
        channel_staff_portal_id=None,
        channel_club_portal_id=None,
        channel_manager_portal_id=None,
        channel_coach_portal_id=None,
        channel_recruit_portal_id=None,
        channel_staff_monitor_id=None,
        channel_recruit_listing_id=None,
        channel_club_listing_id=None,
        channel_premium_coaches_id=None,
        staff_role_ids=set(),
        mongodb_uri="mongodb://localhost",
        mongodb_db_name="testdb",
        mongodb_collection=None,
        mongodb_per_guild_db=per_guild,
        mongodb_guild_db_prefix="",
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )


def test_delete_guild_data_requires_per_guild_db(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    settings = _settings(per_guild=False)
    with pytest.raises(RuntimeError, match="MONGODB_PER_GUILD_DB"):
        delete_guild_data(settings, guild_id=123)


def test_delete_guild_data_drops_guild_db_and_global_docs(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    settings = _settings(per_guild=True)

    guild_id = 123
    now = datetime.now(timezone.utc)

    global_db = database.get_global_database(settings)
    global_db["keepalive"].insert_one({"_id": "keep"})
    global_db[SUBSCRIPTIONS_COLLECTION].insert_one({"_id": guild_id, "guild_id": guild_id, "updated_at": now})
    global_db[STRIPE_EVENTS_COLLECTION].insert_one(
        {"_id": "evt_1", "guild_id": guild_id, "received_at": now, "status": "processed"}
    )
    global_db[STRIPE_DEAD_LETTERS_COLLECTION].insert_one(
        {
            "_id": "dead_1",
            "received_at": now,
            "payload": {"data": {"object": {"metadata": {"guild_id": str(guild_id)}}}},
        }
    )

    guild_db = database.get_database(settings, guild_id=guild_id)
    guild_db["players"].insert_one({"_id": 1, "guild_id": guild_id, "created_at": now})

    result = delete_guild_data(settings, guild_id=guild_id)
    assert result["guild_id"] == guild_id
    assert result["db_dropped"] == guild_db.name

    assert global_db[SUBSCRIPTIONS_COLLECTION].count_documents({"_id": guild_id}) == 0
    assert global_db[STRIPE_EVENTS_COLLECTION].count_documents({"guild_id": guild_id}) == 0
    assert (
        global_db[STRIPE_DEAD_LETTERS_COLLECTION].count_documents(
            {"payload.data.object.metadata.guild_id": str(guild_id)}
        )
        == 0
    )

    client = database.get_client(settings)
    assert guild_db.name not in client.list_database_names()
    assert global_db.name in client.list_database_names()

