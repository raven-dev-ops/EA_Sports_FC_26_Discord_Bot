from __future__ import annotations

from datetime import datetime, timezone

import mongomock

import database
from config.settings import Settings
from services import entitlements_service, subscription_service


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


def test_defaults_to_free(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    entitlements_service.invalidate_all()

    settings = _settings()
    assert entitlements_service.get_guild_plan(settings, guild_id=123) == entitlements_service.PLAN_FREE


def test_pro_subscription_is_pro(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    entitlements_service.invalidate_all()

    settings = _settings()
    subscription_service.ensure_subscription_indexes(settings)
    subscription_service.upsert_guild_subscription(
        settings,
        guild_id=123,
        plan="pro",
        status="active",
        period_end=datetime(2030, 1, 1, tzinfo=timezone.utc),
        customer_id="cus_123",
        subscription_id="sub_123",
    )

    assert entitlements_service.get_guild_plan(settings, guild_id=123) == entitlements_service.PLAN_PRO


def test_enterprise_subscription_is_paid(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    entitlements_service.invalidate_all()

    settings = _settings()
    subscription_service.ensure_subscription_indexes(settings)
    subscription_service.upsert_guild_subscription(
        settings,
        guild_id=124,
        plan="enterprise",
        status="active",
        period_end=datetime(2030, 1, 1, tzinfo=timezone.utc),
        customer_id="cus_124",
        subscription_id="sub_124",
    )

    plan = entitlements_service.get_guild_plan(settings, guild_id=124)
    assert plan == entitlements_service.PLAN_ENTERPRISE
    assert entitlements_service.is_paid_plan(plan)


def test_canceled_subscription_is_free(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    entitlements_service.invalidate_all()

    settings = _settings()
    subscription_service.ensure_subscription_indexes(settings)
    subscription_service.upsert_guild_subscription(
        settings,
        guild_id=123,
        plan="pro",
        status="canceled",
        period_end=datetime(2030, 1, 1, tzinfo=timezone.utc),
        customer_id="cus_123",
        subscription_id="sub_123",
    )

    assert entitlements_service.get_guild_plan(settings, guild_id=123) == entitlements_service.PLAN_FREE


def test_cache_invalidation(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    entitlements_service.invalidate_all()

    settings = _settings()
    subscription_service.ensure_subscription_indexes(settings)
    subscription_service.upsert_guild_subscription(
        settings,
        guild_id=123,
        plan="pro",
        status="active",
        period_end=datetime(2030, 1, 1, tzinfo=timezone.utc),
        customer_id="cus_123",
        subscription_id="sub_123",
    )

    assert entitlements_service.get_guild_plan(settings, guild_id=123) == entitlements_service.PLAN_PRO

    subscription_service.upsert_guild_subscription(
        settings,
        guild_id=123,
        plan="pro",
        status="canceled",
        period_end=datetime(2030, 1, 1, tzinfo=timezone.utc),
        customer_id="cus_123",
        subscription_id="sub_123",
    )

    assert entitlements_service.get_guild_plan(settings, guild_id=123) == entitlements_service.PLAN_PRO
    entitlements_service.invalidate_guild_plan(123)
    assert entitlements_service.get_guild_plan(settings, guild_id=123) == entitlements_service.PLAN_FREE


def test_force_pro_override(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    entitlements_service.invalidate_all()
    monkeypatch.setenv("ENTITLEMENTS_FORCE_PRO_GUILDS", "555")

    settings = _settings()
    assert entitlements_service.get_guild_plan(settings, guild_id=555) == entitlements_service.PLAN_PRO

    # Make sure the override doesn't leak to other guilds.
    entitlements_service.invalidate_all()
    assert entitlements_service.get_guild_plan(settings, guild_id=556) == entitlements_service.PLAN_FREE
