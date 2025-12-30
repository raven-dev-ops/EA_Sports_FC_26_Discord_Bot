from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import mongomock
import pytest

import database
from config.settings import Settings
from offside_bot import dashboard


def _settings() -> Settings:
    return Settings(
        discord_token="token",
        discord_application_id=1,
        discord_client_id=None,
        discord_public_key=None,
        interactions_endpoint_url=None,
        test_mode=True,
        role_broskie_id=None,
        role_coach_id=2,
        role_coach_premium_id=3,
        role_coach_premium_plus_id=4,
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
        mongodb_db_name="testdb",
        mongodb_collection="testcol",
        mongodb_per_guild_db=False,
        mongodb_guild_db_prefix="",
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )


@pytest.mark.asyncio
async def test_oauth_callback_records_manage_guild_as_eligible(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DASHBOARD_REDIRECT_URI", "http://localhost:8080/oauth/callback")

    async def fake_exchange_code(*_args, **_kwargs):
        return {"access_token": "access_token"}

    async def fake_discord_get_json(*_args, url: str, **_kwargs):
        if url == dashboard.ME_URL:
            return {"id": "1", "username": "alice", "discriminator": "0001"}
        if url == dashboard.MY_GUILDS_URL:
            return [
                {"id": "123", "name": "Managed", "owner": False, "permissions": str(1 << 5)},
                {"id": "999", "name": "Ineligible", "owner": False, "permissions": "0"},
            ]
        raise AssertionError(f"Unexpected Discord URL: {url}")

    monkeypatch.setattr(dashboard, "_exchange_code", fake_exchange_code)
    monkeypatch.setattr(dashboard, "_discord_get_json", fake_discord_get_json)

    app = dashboard.create_app(settings=_settings())
    states = app["state_collection"]
    states.insert_one(
        {
            "_id": "state1",
            "issued_at": time.time(),
            "next": "/",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/oauth/callback?code=abc&state=state1", allow_redirects=False)
        assert resp.status == 302
        cookie = resp.cookies.get(dashboard.COOKIE_NAME)
        assert cookie is not None

        session_id = cookie.value
        sessions = app["session_collection"]
        doc = sessions.find_one({"_id": session_id})
        assert isinstance(doc, dict)

        owner_guilds = doc.get("owner_guilds")
        assert isinstance(owner_guilds, list)
        assert [g.get("id") for g in owner_guilds] == ["123"]

        billing = await client.get("/app/billing?guild_id=123", allow_redirects=False)
        assert billing.status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_billing_checkout_requires_csrf(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    app = dashboard.create_app(settings=_settings())
    sessions = app["session_collection"]
    sessions.insert_one(
        {
            "_id": "sess1",
            "created_at": time.time(),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=6),
            "user": {"id": "1", "username": "alice"},
            "owner_guilds": [{"id": "123", "name": "Managed"}],
            "all_guilds": [{"id": "123", "name": "Managed"}],
            "csrf_token": "csrf_good",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.post(
            "/app/billing/checkout",
            data={"csrf": "csrf_bad", "guild_id": "123", "plan": "pro"},
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 400
        text = await resp.text()
        assert "CSRF" in text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_billing_portal_requires_csrf(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    app = dashboard.create_app(settings=_settings())
    sessions = app["session_collection"]
    sessions.insert_one(
        {
            "_id": "sess1",
            "created_at": time.time(),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=6),
            "user": {"id": "1", "username": "alice"},
            "owner_guilds": [{"id": "123", "name": "Managed"}],
            "all_guilds": [{"id": "123", "name": "Managed"}],
            "csrf_token": "csrf_good",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.post(
            "/app/billing/portal",
            data={"csrf": "csrf_bad", "guild_id": "123"},
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 400
        text = await resp.text()
        assert "CSRF" in text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_settings_blocks_when_bot_not_installed(monkeypatch) -> None:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    async def fake_bot_get_json(*_args, url: str, **_kwargs):
        if url.endswith("/guilds/123"):
            raise web.HTTPNotFound(text="Discord API error (404): Unknown Guild")
        raise AssertionError(f"Unexpected bot Discord URL: {url}")

    monkeypatch.setattr(dashboard, "_discord_bot_get_json", fake_bot_get_json)

    app = dashboard.create_app(settings=_settings())
    sessions = app["session_collection"]
    sessions.insert_one(
        {
            "_id": "sess1",
            "created_at": time.time(),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=6),
            "user": {"id": "1", "username": "alice"},
            "owner_guilds": [{"id": "123", "name": "Managed"}],
            "all_guilds": [{"id": "123", "name": "Managed"}],
            "csrf_token": "csrf_good",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(
            "/guild/123/settings",
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 200
        html = await resp.text()
        assert "Invite bot to this server" in html
        assert "/install?guild_id=123" in html
        assert "<form" not in html

        save = await client.post(
            "/guild/123/settings",
            data={},
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert save.status == 400
        text = await save.text()
        assert "Invite" in text or "installed" in text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_permissions_page_renders(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    async def fake_bot_get_json(*_args, url: str, **_kwargs):
        if url.endswith("/guilds/123"):
            return {"id": "123", "name": "Managed"}
        if url.endswith("/guilds/123/roles"):
            bot_perms = (
                (1 << 4)
                | (1 << 10)
                | (1 << 11)
                | (1 << 13)
                | (1 << 14)
                | (1 << 16)
                | (1 << 28)
            )
            return [
                {"id": "123", "name": "@everyone", "permissions": "0", "position": 0},
                {"id": "10", "name": "Offside Bot", "permissions": str(bot_perms), "position": 10},
                {"id": "11", "name": "Coach", "permissions": "0", "position": 1},
                {"id": "12", "name": "Coach Premium", "permissions": "0", "position": 2},
                {"id": "13", "name": "Coach Premium+", "permissions": "0", "position": 3},
            ]
        if url.endswith("/guilds/123/channels"):
            return [
                {
                    "id": "20",
                    "type": 0,
                    "name": "staff-portal",
                    "position": 1,
                    "permission_overwrites": [],
                }
            ]
        if url.endswith("/guilds/123/members/1"):
            return {"roles": ["10"], "user": {"id": "1"}}
        raise AssertionError(f"Unexpected bot Discord URL: {url}")

    monkeypatch.setattr(dashboard, "_discord_bot_get_json", fake_bot_get_json)
    monkeypatch.setattr(
        dashboard,
        "get_guild_config",
        lambda _gid: {
            "role_coach_id": 11,
            "role_coach_premium_id": 12,
            "role_coach_premium_plus_id": 13,
            "channel_staff_portal_id": 20,
        },
    )

    app = dashboard.create_app(settings=_settings())
    sessions = app["session_collection"]
    sessions.insert_one(
        {
            "_id": "sess1",
            "created_at": time.time(),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=6),
            "user": {"id": "1", "username": "alice"},
            "owner_guilds": [{"id": "123", "name": "Managed"}],
            "all_guilds": [{"id": "123", "name": "Managed"}],
            "csrf_token": "csrf_good",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(
            "/guild/123/permissions",
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 200
        html = await resp.text()
        assert "Permissions Check" in html
        assert "Guild-level permissions" in html
        assert "staff-portal" in html
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_overview_page_renders(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    async def fake_bot_get_json(*_args, url: str, **_kwargs):
        if url.endswith("/guilds/123"):
            return {"id": "123", "name": "Managed"}
        if url.endswith("/guilds/123/roles"):
            return [
                {"id": "123", "name": "@everyone", "permissions": "0", "position": 0},
                {"id": "11", "name": "Coach", "permissions": "0", "position": 1},
                {"id": "12", "name": "Coach Premium", "permissions": "0", "position": 2},
                {"id": "13", "name": "Coach Premium+", "permissions": "0", "position": 3},
            ]
        if url.endswith("/guilds/123/channels"):
            return [
                {"id": "20", "type": 0, "name": "staff-portal", "position": 1, "permission_overwrites": []},
                {"id": "21", "type": 0, "name": "club-managers-portal", "position": 2, "permission_overwrites": []},
                {"id": "22", "type": 0, "name": "club-portal", "position": 3, "permission_overwrites": []},
                {"id": "23", "type": 0, "name": "coach-portal", "position": 4, "permission_overwrites": []},
                {"id": "24", "type": 0, "name": "recruit-portal", "position": 5, "permission_overwrites": []},
                {"id": "30", "type": 0, "name": "staff-monitor", "position": 6, "permission_overwrites": []},
                {"id": "31", "type": 0, "name": "roster-listing", "position": 7, "permission_overwrites": []},
                {"id": "32", "type": 0, "name": "recruit-listing", "position": 8, "permission_overwrites": []},
                {"id": "33", "type": 0, "name": "club-listing", "position": 9, "permission_overwrites": []},
                {"id": "34", "type": 0, "name": "premium-coaches", "position": 10, "permission_overwrites": []},
            ]
        if "/channels/" in url and "/messages" in url:
            return [{"id": "m1", "author": {"id": "1"}}]
        raise AssertionError(f"Unexpected bot Discord URL: {url}")

    monkeypatch.setattr(dashboard, "_discord_bot_get_json", fake_bot_get_json)
    monkeypatch.setattr(
        dashboard,
        "get_guild_config",
        lambda _gid: {
            "role_coach_id": 11,
            "role_coach_premium_id": 12,
            "role_coach_premium_plus_id": 13,
            "channel_staff_portal_id": 20,
            "channel_manager_portal_id": 21,
            "channel_club_portal_id": 22,
            "channel_coach_portal_id": 23,
            "channel_recruit_portal_id": 24,
            "channel_staff_monitor_id": 30,
            "channel_roster_listing_id": 31,
            "channel_recruit_listing_id": 32,
            "channel_club_listing_id": 33,
            "channel_premium_coaches_id": 34,
        },
    )

    app = dashboard.create_app(settings=_settings())
    sessions = app["session_collection"]
    sessions.insert_one(
        {
            "_id": "sess1",
            "created_at": time.time(),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=6),
            "user": {"id": "1", "username": "alice"},
            "owner_guilds": [{"id": "123", "name": "Managed"}],
            "all_guilds": [{"id": "123", "name": "Managed"}],
            "csrf_token": "csrf_good",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(
            "/guild/123/overview",
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 200
        html = await resp.text()
        assert "Setup checklist" in html
        assert "Quick actions" in html
        assert "/api/guild/123/ops/run_setup" in html
        assert "/api/guild/123/ops/repost_portals" in html
        assert "Dashboard and listing embeds detected." in html
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_audit_page_is_locked_for_free_plan(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    async def fake_bot_get_json(*_args, url: str, **_kwargs):
        if url.endswith("/guilds/123"):
            return {"id": "123", "name": "Managed"}
        raise AssertionError(f"Unexpected bot Discord URL: {url}")

    monkeypatch.setattr(dashboard, "_discord_bot_get_json", fake_bot_get_json)

    app = dashboard.create_app(settings=_settings())
    sessions = app["session_collection"]
    sessions.insert_one(
        {
            "_id": "sess1",
            "created_at": time.time(),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=6),
            "user": {"id": "1", "username": "alice"},
            "owner_guilds": [{"id": "123", "name": "Managed"}],
            "all_guilds": [{"id": "123", "name": "Managed"}],
            "csrf_token": "csrf_good",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(
            "/guild/123/audit",
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 200
        html = await resp.text()
        assert "Pro feature" in html
        assert "Upgrade to Pro" in html
        assert "/app/upgrade?guild_id=123" in html
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_upgrade_redirect_records_audit_event(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    app = dashboard.create_app(settings=_settings())
    sessions = app["session_collection"]
    sessions.insert_one(
        {
            "_id": "sess1",
            "created_at": time.time(),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=6),
            "user": {"id": "1", "username": "alice"},
            "owner_guilds": [{"id": "123", "name": "Managed"}],
            "all_guilds": [{"id": "123", "name": "Managed"}],
            "csrf_token": "csrf_good",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(
            "/app/upgrade?guild_id=123&from=locked&section=audit",
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 302
        assert resp.headers.get("Location") == "/app/billing?guild_id=123"

        col = database.get_collection(_settings(), record_type="audit_event", guild_id=123)
        doc = col.find_one({"record_type": "audit_event", "guild_id": 123, "action": "upgrade.clicked"})
        assert isinstance(doc, dict)
        assert doc.get("details", {}).get("from") == "locked"
        assert doc.get("details", {}).get("section") == "audit"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_settings_save_blocks_fc25_override_for_free(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    async def fake_detect_installed(*_args, **_kwargs):
        return True, None

    async def fake_metadata(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(dashboard, "_detect_bot_installed", fake_detect_installed)
    monkeypatch.setattr(dashboard, "_get_guild_discord_metadata", fake_metadata)
    monkeypatch.setattr(dashboard, "get_guild_config", lambda _gid: {})

    app = dashboard.create_app(settings=_settings())
    sessions = app["session_collection"]
    sessions.insert_one(
        {
            "_id": "sess1",
            "created_at": time.time(),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=6),
            "user": {"id": "1", "username": "alice"},
            "owner_guilds": [{"id": "123", "name": "Managed"}],
            "all_guilds": [{"id": "123", "name": "Managed"}],
            "csrf_token": "csrf_good",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.post(
            "/guild/123/settings",
            data={"csrf": "csrf_good", "fc25_stats_enabled": "true"},
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 403
        text = await resp.text()
        assert "Pro" in text
    finally:
        await client.close()
