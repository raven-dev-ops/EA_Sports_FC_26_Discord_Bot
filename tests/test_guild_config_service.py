from __future__ import annotations

import mongomock

import database
from config.settings import Settings
from services import guild_config_service as gcs


def _settings() -> Settings:
    return Settings(
        discord_token="token",
        discord_application_id=1,
        discord_client_id=None,
        discord_public_key=None,
        interactions_endpoint_url=None,
        test_mode=True,
        role_broskie_id=1,
        role_team_coach_id=2,
        role_club_manager_id=3,
        role_league_staff_id=4,
        role_league_owner_id=5,
        role_free_agent_id=6,
        role_pro_player_id=7,
        role_retired_id=8,
        channel_staff_portal_id=7,
        channel_club_portal_id=None,
        channel_manager_portal_id=None,
        channel_coach_portal_id=6,
        channel_recruit_portal_id=None,
        channel_staff_monitor_id=None,
        channel_recruit_listing_id=None,
        channel_club_listing_id=None,
        channel_premium_coaches_id=None,
        staff_role_ids=set(),
        mongodb_uri="mongodb://localhost",
        mongodb_db_name="testdb",
        mongodb_collection="testcol",
        mongodb_per_guild_db=False,
        mongodb_guild_db_prefix="",
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )


def test_guild_config_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    settings = _settings()

    # Ensure index creation succeeds
    col = database.get_collection(settings)
    gcs.set_guild_config(123, {"foo": "bar"}, collection=col)
    cfg = gcs.get_guild_config(123, collection=col)
    assert cfg["foo"] == "bar"
