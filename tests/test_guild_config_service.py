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
        discord_test_channel_id=None,
        test_mode=True,
        role_broskie_id=1,
        role_super_league_coach_id=2,
        role_coach_premium_id=3,
        role_coach_premium_plus_id=4,
        channel_roster_portal_id=5,
        channel_coach_portal_id=6,
        channel_staff_portal_id=7,
        staff_role_ids=set(),
        mongodb_uri="mongodb://localhost",
        mongodb_db_name="testdb",
        mongodb_collection="testcol",
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
