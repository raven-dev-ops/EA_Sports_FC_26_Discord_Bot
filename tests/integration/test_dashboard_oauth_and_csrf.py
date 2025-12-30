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
