from __future__ import annotations

import logging

import mongomock

from config.settings import Settings
from database import close_client
from migrations import apply_migrations


def _fake_settings() -> Settings:
    return Settings(
        discord_token="token",
        discord_application_id=1,
        discord_client_id=None,
        discord_public_key=None,
        interactions_endpoint_url=None,
        test_mode=True,
        role_broskie_id=1,
        role_coach_id=2,
        role_coach_premium_id=3,
        role_coach_premium_plus_id=4,
        channel_staff_portal_id=7,
        channel_club_portal_id=None,
        channel_manager_portal_id=None,
        channel_coach_portal_id=6,
        channel_recruit_portal_id=None,
        channel_staff_monitor_id=None,
        channel_roster_listing_id=5,
        channel_recruit_listing_id=None,
        channel_club_listing_id=None,
        channel_premium_coaches_id=None,
        staff_role_ids=set(),
        mongodb_uri="mongodb://localhost",
        mongodb_db_name="testdb",
        mongodb_collection="testcol",
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )


def test_apply_migrations_with_mongomock(monkeypatch) -> None:
    """
    Ensure migrations run and set schema version using mongomock.
    """
    import database

    # Force mongomock client in place of pymongo.MongoClient
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    settings = _fake_settings()

    logger = logging.getLogger("test_migrations")
    latest = apply_migrations(settings=settings, logger=logger)
    assert latest == 4

    client = database.get_client(settings)
    meta = client[settings.mongodb_db_name]["_meta"].find_one({"_id": "schema_version"})
    assert meta and meta["version"] == 4

    close_client()
