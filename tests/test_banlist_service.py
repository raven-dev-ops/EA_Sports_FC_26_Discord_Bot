from config.settings import Settings
from services import banlist_service


def _settings() -> Settings:
    return Settings(
        discord_token="token",
        discord_application_id=1,
        discord_client_id=None,
        discord_public_key=None,
        interactions_endpoint_url=None,
        test_mode=False,
        role_broskie_id=1,
        role_coach_id=2,
        role_coach_premium_id=3,
        role_coach_premium_plus_id=4,
        channel_staff_portal_id=6,
        channel_club_portal_id=None,
        channel_manager_portal_id=None,
        channel_coach_portal_id=5,
        channel_recruit_portal_id=None,
        channel_staff_monitor_id=None,
        channel_roster_listing_id=5,
        channel_recruit_listing_id=None,
        channel_club_listing_id=None,
        channel_premium_coaches_id=None,
        staff_role_ids=set(),
        mongodb_uri=None,
        mongodb_db_name=None,
        mongodb_collection=None,
        banlist_sheet_id="sheet",
        banlist_range="Sheet1!A1:B2",
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json="{}",
    )


def test_ban_reason_lookup(monkeypatch) -> None:
    def fake_fetch_rows(settings):
        return [
            ["discord_id", "reason_for_ban"],
            ["123456789", "Match-fixing"],
        ]

    monkeypatch.setattr(banlist_service, "_fetch_rows", fake_fetch_rows)
    settings = _settings()

    reason = banlist_service.get_ban_reason(settings, 123456789)
    assert reason == "Match-fixing"


def test_banlist_cache(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_fetch_rows(settings):
        calls["count"] += 1
        return [["discord_id", "reason_for_ban"], ["111", "Toxic"]]

    monkeypatch.setattr(banlist_service, "_fetch_rows", fake_fetch_rows)
    settings = _settings()

    banlist_service.get_banlist(settings, force_refresh=True)
    banlist_service.get_banlist(settings)

    assert calls["count"] == 1


def test_missing_banlist_config_returns_none() -> None:
    settings = Settings(
        discord_token="token",
        discord_application_id=1,
        discord_client_id=None,
        discord_public_key=None,
        interactions_endpoint_url=None,
        test_mode=False,
        role_broskie_id=1,
        role_coach_id=2,
        role_coach_premium_id=3,
        role_coach_premium_plus_id=4,
        channel_staff_portal_id=6,
        channel_club_portal_id=None,
        channel_manager_portal_id=None,
        channel_coach_portal_id=5,
        channel_recruit_portal_id=None,
        channel_staff_monitor_id=None,
        channel_roster_listing_id=5,
        channel_recruit_listing_id=None,
        channel_club_listing_id=None,
        channel_premium_coaches_id=None,
        staff_role_ids=set(),
        mongodb_uri=None,
        mongodb_db_name=None,
        mongodb_collection=None,
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )

    reason = banlist_service.get_ban_reason(settings, 123456789)
    assert reason is None
