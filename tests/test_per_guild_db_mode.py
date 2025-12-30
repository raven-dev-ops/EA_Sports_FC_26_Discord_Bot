from __future__ import annotations

import mongomock
import pytest

import database
from config.settings import Settings
from services.analytics_service import get_guild_analytics


def _settings(*, per_guild: bool) -> Settings:
    return Settings(
        discord_token="token",
        discord_application_id=1,
        discord_client_id=None,
        discord_public_key=None,
        interactions_endpoint_url=None,
        test_mode=True,
        role_broskie_id=None,
        role_coach_id=None,
        role_coach_premium_id=None,
        role_coach_premium_plus_id=None,
        channel_staff_portal_id=None,
        channel_club_portal_id=None,
        channel_manager_portal_id=None,
        channel_coach_portal_id=None,
        channel_recruit_portal_id=None,
        channel_staff_monitor_id=None,
        channel_roster_listing_id=None,
        channel_recruit_listing_id=None,
        channel_club_listing_id=None,
        channel_premium_coaches_id=None,
        staff_role_ids=set(),
        mongodb_uri="mongodb://localhost",
        mongodb_db_name="OffsideDiscordBot",
        mongodb_collection=None,
        mongodb_per_guild_db=per_guild,
        mongodb_guild_db_prefix="",
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )


def test_per_guild_db_routing_and_analytics(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    settings = _settings(per_guild=True)

    guild_a = 111
    guild_b = 222

    col_a = database.get_collection(settings, record_type="guild_settings", guild_id=guild_a)
    col_b = database.get_collection(settings, record_type="guild_settings", guild_id=guild_b)

    col_a.insert_one({"record_type": "guild_settings", "guild_id": guild_a, "settings": {"a": True}})
    col_b.insert_one({"record_type": "guild_settings", "guild_id": guild_b, "settings": {"b": True}})

    assert col_a.count_documents({}) == 1
    assert col_b.count_documents({}) == 1
    assert col_a.find_one({"guild_id": guild_b}) is None
    assert col_b.find_one({"guild_id": guild_a}) is None

    analytics_a = get_guild_analytics(settings, guild_id=guild_a)
    assert analytics_a.db_name == str(guild_a)
    assert analytics_a.record_type_counts["guild_settings"] == 1

    analytics_b = get_guild_analytics(settings, guild_id=guild_b)
    assert analytics_b.db_name == str(guild_b)
    assert analytics_b.record_type_counts["guild_settings"] == 1


def test_per_guild_db_requires_guild_id(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    settings = _settings(per_guild=True)
    with pytest.raises(RuntimeError):
        database.get_database(settings)

