from __future__ import annotations

import sys
import time
import types
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse

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
        role_team_coach_id=2,
        role_club_manager_id=3,
        role_league_staff_id=4,
        role_league_owner_id=5,
        role_free_agent_id=6,
        role_pro_player_id=7,
        role_retired_id=8,
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
        mongodb_collection="testcol",
        mongodb_per_guild_db=False,
        mongodb_guild_db_prefix="",
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )


@pytest.mark.asyncio
async def test_dashboard_smoke_critical_path(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DASHBOARD_REDIRECT_URI", "http://localhost:8080/oauth/callback")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_PRICE_PRO_ID", "price_test_123")

    async def fake_exchange_code(*_args, **_kwargs):
        return {"access_token": "access_token"}

    async def fake_discord_get_json(*_args, url: str, **_kwargs):
        if url == dashboard.ME_URL:
            return {"id": "1", "username": "alice", "discriminator": "0001"}
        if url == dashboard.MY_GUILDS_URL:
            return [{"id": "123", "name": "Managed", "owner": True, "permissions": str(1 << 5)}]
        raise AssertionError(f"Unexpected Discord URL: {url}")

    async def fake_detect_installed(*_args, **_kwargs):
        return True, None

    class FakeCheckoutSession:
        url = "https://checkout.stripe.com/session"

    fake_stripe = types.SimpleNamespace()
    fake_stripe.api_key = ""
    fake_stripe.checkout = types.SimpleNamespace(
        Session=types.SimpleNamespace(create=lambda *_args, **_kwargs: FakeCheckoutSession())
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    monkeypatch.setattr(dashboard, "_exchange_code", fake_exchange_code)
    monkeypatch.setattr(dashboard, "_discord_get_json", fake_discord_get_json)
    monkeypatch.setattr(dashboard, "_detect_bot_installed", fake_detect_installed)

    app = dashboard.create_app(settings=_settings())
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        # Unauthenticated: marketing pages load.
        resp = await client.get("/", allow_redirects=False)
        assert resp.status == 200

        resp = await client.get("/pricing", allow_redirects=False)
        assert resp.status == 200

        resp = await client.get("/features", allow_redirects=False)
        assert resp.status == 200

        resp = await client.get("/commands", allow_redirects=False)
        assert resp.status == 200

        resp = await client.get("/support", allow_redirects=False)
        assert resp.status == 200

        # Login flow returns to the originally requested page.
        login_qs = urlencode({"next": "/app/billing?guild_id=123"})
        resp = await client.get(f"/login?{login_qs}", allow_redirects=False)
        assert resp.status == 302

        auth_location = resp.headers.get("Location")
        assert auth_location is not None
        state = parse_qs(urlparse(auth_location).query).get("state", [""])[0]
        assert state

        resp = await client.get(f"/oauth/callback?code=abc&state={state}", allow_redirects=False)
        assert resp.status == 302
        assert resp.headers.get("Location") == "/app"

        cookie = resp.cookies.get(dashboard.COOKIE_NAME)
        assert cookie is not None
        cookie_header = f"{dashboard.COOKIE_NAME}={cookie.value}"

        # Authenticated: billing + settings pages load.
        billing = await client.get("/app/billing?guild_id=123", headers={"Cookie": cookie_header})
        assert billing.status == 200

        settings_page = await client.get("/guild/123/settings", headers={"Cookie": cookie_header})
        assert settings_page.status == 200

        # Upgrade checkout can be started (Stripe mocked).
        sessions = app[dashboard.SESSION_COLLECTION_KEY]
        session_doc = sessions.find_one({"_id": cookie.value}) or {}
        csrf = session_doc.get("csrf_token")
        assert isinstance(csrf, str) and csrf

        resp = await client.post(
            "/app/billing/checkout",
            data={"csrf": csrf, "guild_id": "123", "plan": "pro"},
            headers={"Cookie": cookie_header},
            allow_redirects=False,
        )
        assert resp.status == 302
        assert resp.headers.get("Location") == "https://checkout.stripe.com/session"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_dashboard_smoke_login_state_expires(monkeypatch) -> None:
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
            return [{"id": "123", "name": "Managed", "owner": False, "permissions": str(1 << 5)}]
        raise AssertionError(f"Unexpected Discord URL: {url}")

    monkeypatch.setattr(dashboard, "_exchange_code", fake_exchange_code)
    monkeypatch.setattr(dashboard, "_discord_get_json", fake_discord_get_json)

    app = dashboard.create_app(settings=_settings())
    states = app[dashboard.STATE_COLLECTION_KEY]
    states.insert_one(
        {
            "_id": "state1",
            "issued_at": time.time() - (dashboard.STATE_TTL_SECONDS + 60),
            "next": "/",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/oauth/callback?code=abc&state=state1", allow_redirects=False)
        assert resp.status == 400
        html = await resp.text()
        assert "Login expired" in html
    finally:
        await client.close()
