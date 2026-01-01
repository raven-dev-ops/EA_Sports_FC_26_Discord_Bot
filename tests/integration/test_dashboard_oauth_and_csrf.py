from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import mongomock
import pytest

import database
from config.settings import Settings
from offside_bot import dashboard
from services import entitlements_service, subscription_service


def _settings(*, mongodb_per_guild_db: bool = False) -> Settings:
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
        mongodb_per_guild_db=mongodb_per_guild_db,
        mongodb_guild_db_prefix="",
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )


def _stripe_sig_header(*, payload: bytes, secret: str, timestamp: int) -> str:
    signed_payload = str(timestamp).encode("utf-8") + b"." + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={expected}"


@pytest.mark.asyncio
async def test_protected_routes_redirect_to_login_with_next(monkeypatch) -> None:
    from urllib.parse import parse_qs, urlparse

    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    app = dashboard.create_app(settings=_settings())
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/app/billing?guild_id=123", allow_redirects=False)
        assert resp.status == 302
        location = resp.headers.get("Location")
        assert location is not None
        parsed = urlparse(location)
        assert parsed.path == "/login"
        assert parse_qs(parsed.query).get("next") == ["/app/billing?guild_id=123"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_app_requires_login_redirects_with_next(monkeypatch) -> None:
    from urllib.parse import parse_qs, urlparse

    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    app = dashboard.create_app(settings=_settings())
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/app", allow_redirects=False)
        assert resp.status == 302
        location = resp.headers.get("Location")
        assert location is not None
        parsed = urlparse(location)
        assert parsed.path == "/login"
        assert parse_qs(parsed.query).get("next") == ["/app"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_console_allows_allowlisted_user(monkeypatch) -> None:
    from urllib.parse import parse_qs, urlparse

    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DASHBOARD_REDIRECT_URI", "http://localhost:8080/oauth/callback")
    monkeypatch.setenv("ADMIN_DISCORD_IDS", "1")

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
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/login?next=/admin", allow_redirects=False)
        location = resp.headers.get("Location")
        assert location is not None
        state = parse_qs(urlparse(location).query).get("state", [""])[0]
        assert state

        resp = await client.get(f"/oauth/callback?code=abc&state={state}", allow_redirects=False)
        cookie = resp.cookies.get(dashboard.COOKIE_NAME)
        assert cookie is not None
        cookie_header = f"{dashboard.COOKIE_NAME}={cookie.value}"

        admin_page = await client.get("/admin", headers={"Cookie": cookie_header})
        assert admin_page.status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_console_denies_non_admin(monkeypatch) -> None:
    from urllib.parse import parse_qs, urlparse

    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DASHBOARD_REDIRECT_URI", "http://localhost:8080/oauth/callback")
    monkeypatch.setenv("ADMIN_DISCORD_IDS", "999")

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
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/login?next=/admin", allow_redirects=False)
        location = resp.headers.get("Location")
        assert location is not None
        state = parse_qs(urlparse(location).query).get("state", [""])[0]
        assert state

        resp = await client.get(f"/oauth/callback?code=abc&state={state}", allow_redirects=False)
        cookie = resp.cookies.get(dashboard.COOKIE_NAME)
        assert cookie is not None
        cookie_header = f"{dashboard.COOKIE_NAME}={cookie.value}"

        admin_page = await client.get("/admin", headers={"Cookie": cookie_header})
        assert admin_page.status == 403
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_oauth_callback_access_denied_renders_friendly_page(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DASHBOARD_REDIRECT_URI", "http://localhost:8080/oauth/callback")

    app = dashboard.create_app(settings=_settings())
    states = app[dashboard.STATE_COLLECTION_KEY]
    states.insert_one(
        {
            "_id": "state1",
            "issued_at": time.time(),
            "next": "/guild/123/overview",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/oauth/callback?error=access_denied&state=state1", allow_redirects=False)
        assert resp.status == 200
        html = await resp.text()
        assert "Login cancelled" in html
        assert "Try again" in html
        assert "/login?next=" in html
        assert "guild%2F123%2Foverview" in html
    finally:
        await client.close()


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
    states = app[dashboard.STATE_COLLECTION_KEY]
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
        sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
async def test_oauth_callback_with_expired_state_is_rejected(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DASHBOARD_REDIRECT_URI", "http://localhost:8080/oauth/callback")

    app = dashboard.create_app(settings=_settings())
    states = app[dashboard.STATE_COLLECTION_KEY]
    states.insert_one(
        {
            "_id": "state_expired",
            "issued_at": time.time() - (dashboard.STATE_TTL_SECONDS + 5),
            "next": "/app",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/oauth/callback?code=abc&state=state_expired", allow_redirects=False)
        assert resp.status == 400
        html = await resp.text()
        assert "Login expired" in html
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_session_idle_timeout_forces_relogin(monkeypatch) -> None:
    from urllib.parse import parse_qs, urlparse

    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
    now = time.time()
    sessions.insert_one(
        {
            "_id": "sess_idle",
            "created_at": now - 120,
            "last_seen_at": now - (dashboard.SESSION_IDLE_TIMEOUT_SECONDS + 5),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=dashboard.SESSION_TTL_SECONDS),
            "user": {"id": "1", "username": "alice", "discriminator": "0001"},
            "owner_guilds": [{"id": "123", "name": "Guild"}],
            "all_guilds": [{"id": "123", "name": "Guild"}],
            "csrf_token": "csrf_idle",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/app", allow_redirects=False, headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess_idle"})
        assert resp.status == 302
        parsed = urlparse(resp.headers["Location"])
        assert parsed.path == "/login"
        assert parse_qs(parsed.query).get("next") == ["/app"]
        assert sessions.find_one({"_id": "sess_idle"}) is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_guild_list_cache_ttl_forces_relogin(monkeypatch) -> None:
    from urllib.parse import parse_qs, urlparse

    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
    now = time.time()
    stale = now - (dashboard.GUILD_METADATA_TTL_SECONDS + 5)
    sessions.insert_one(
        {
            "_id": "sess_stale_guilds",
            "created_at": now - 120,
            "last_seen_at": now,
            "guilds_fetched_at": stale,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=dashboard.SESSION_TTL_SECONDS),
            "user": {"id": "1", "username": "alice", "discriminator": "0001"},
            "owner_guilds": [{"id": "123", "name": "Guild"}],
            "all_guilds": [{"id": "123", "name": "Guild"}],
            "csrf_token": "csrf_stale",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/app", allow_redirects=False, headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess_stale_guilds"})
        assert resp.status == 302
        parsed = urlparse(resp.headers["Location"])
        assert parsed.path == "/login"
        assert parse_qs(parsed.query).get("next") == ["/app"]
        assert sessions.find_one({"_id": "sess_stale_guilds"}) is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_oauth_callback_sets_secure_cookie_flags_when_https(monkeypatch) -> None:
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
            return [{"id": "123", "name": "Managed", "owner": True, "permissions": "0"}]
        raise AssertionError(f"Unexpected Discord URL: {url}")

    monkeypatch.setattr(dashboard, "_exchange_code", fake_exchange_code)
    monkeypatch.setattr(dashboard, "_discord_get_json", fake_discord_get_json)
    monkeypatch.setattr(dashboard, "_is_https", lambda _req: True)

    app = dashboard.create_app(settings=_settings())
    states = app[dashboard.STATE_COLLECTION_KEY]
    states.insert_one(
        {
            "_id": "state_secure",
            "issued_at": time.time(),
            "next": "/",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/oauth/callback?code=abc&state=state_secure", allow_redirects=False)
        assert resp.status == 302
        set_cookie = resp.headers.get("Set-Cookie", "")
        assert dashboard.COOKIE_NAME in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=Lax" in set_cookie or "SameSite=lax" in set_cookie
        assert "Secure" in set_cookie
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_billing_checkout_requires_csrf(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_PRICE_PRO_ID", "price_123")

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
async def test_billing_checkout_blocks_duplicate_subscription(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_PRICE_PRO_ID", "price_123")

    async def fake_create(*_args, **_kwargs):
        return {"url": "https://stripe.test/checkout"}

    import stripe  # type: ignore[import-not-found]

    monkeypatch.setattr(stripe.checkout.Session, "create", fake_create)

    def fake_subscription(settings, *, guild_id):
        return {"status": "active", "plan": "pro", "subscription_id": "sub_123", "guild_id": guild_id}

    monkeypatch.setattr(subscription_service, "get_guild_subscription", fake_subscription)
    monkeypatch.setattr(dashboard, "get_guild_subscription", fake_subscription)

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
            data={"csrf": "csrf_good", "guild_id": "123", "plan": "pro"},
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 400
        text = await resp.text()
        assert "already has an active" in text.lower()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_guild_access_denied_is_logged(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
    now = time.time()
    sessions.insert_one(
        {
            "_id": "sess_denied",
            "created_at": now,
            "last_seen_at": now,
            "guilds_fetched_at": now,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=dashboard.SESSION_TTL_SECONDS),
            "user": {"id": "1", "username": "alice", "discriminator": "0001"},
            "owner_guilds": [{"id": "123", "name": "Guild"}],
            "all_guilds": [{"id": "123", "name": "Guild"}],
            "csrf_token": "csrf_good",
        }
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(
            "/guild/999/overview", allow_redirects=False, headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess_denied"}
        )
        assert resp.status == 403
        collection = database.get_collection(settings=_settings())
        docs = list(collection.find({"record_type": "audit_event", "guild_id": 999}))
        assert len(docs) == 1
        doc = docs[0]
        assert doc.get("action") == "dashboard.access_denied"
        assert doc.get("category") == "auth"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_billing_portal_requires_csrf(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
async def test_billing_success_syncs_subscription(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    entitlements_service.invalidate_all()

    import sys
    import types

    period_end = int(datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp())

    class FakeCheckoutSession:
        metadata = {"guild_id": "123", "plan": "pro"}
        customer = "cus_123"
        subscription = {"id": "sub_123", "status": "active", "current_period_end": period_end}

    def fake_session_retrieve(*_args, **_kwargs):
        return FakeCheckoutSession()

    fake_stripe = types.SimpleNamespace()
    fake_stripe.api_key = ""
    fake_stripe.checkout = types.SimpleNamespace(
        Session=types.SimpleNamespace(retrieve=fake_session_retrieve)
    )
    fake_stripe.Subscription = types.SimpleNamespace(retrieve=lambda *_args, **_kwargs: {})
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
            "/app/billing/success?guild_id=123&session_id=cs_test_123",
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 200
        html = await resp.text()
        assert "Pro enabled for this server." in html
        assert "badge pro" in html

        doc = subscription_service.get_guild_subscription(_settings(), guild_id=123)
        assert isinstance(doc, dict)
        assert doc.get("plan") == "pro"
        assert doc.get("status") == "active"
        assert doc.get("customer_id") == "cus_123"
        assert doc.get("subscription_id") == "sub_123"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_billing_webhook_is_idempotent(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    entitlements_service.invalidate_all()

    event = {
        "id": "evt_idempotent",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_123",
                "subscription": "sub_123",
                "metadata": {"guild_id": "123", "plan": "pro"},
            }
        },
    }
    payload = json.dumps(event).encode("utf-8")
    sig_header = _stripe_sig_header(payload=payload, secret="whsec_test", timestamp=int(time.time()))

    app = dashboard.create_app(settings=_settings())
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.post(
            "/api/billing/webhook",
            data=payload,
            headers={"Stripe-Signature": sig_header},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "processed"

        resp = await client.post(
            "/api/billing/webhook",
            data=payload,
            headers={"Stripe-Signature": sig_header},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] in {"duplicate", "in_progress"}

        doc = subscription_service.get_guild_subscription(_settings(), guild_id=123)
        assert isinstance(doc, dict)
        assert doc.get("plan") == "pro"
        assert doc.get("status") == "checkout_completed"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_dashboard_shows_pro_expired_notice(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    entitlements_service.invalidate_all()

    async def fake_detect_installed(*_args, **_kwargs):
        return False, None

    monkeypatch.setattr(dashboard, "_detect_bot_installed", fake_detect_installed)
    monkeypatch.setattr(dashboard, "get_guild_config", lambda _gid: {})

    subscription_service.upsert_guild_subscription(
        _settings(),
        guild_id=123,
        plan="pro",
        status="canceled",
        period_end=datetime(2020, 1, 1, tzinfo=timezone.utc),
        customer_id="cus_123",
        subscription_id="sub_123",
    )

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
        assert "PRO EXPIRED" in html
        assert "from=notice" in html
        assert "/app/billing?guild_id=123" in html
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
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
async def test_audit_page_allows_pro_plan(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    entitlements_service.invalidate_all()

    async def fake_detect_installed(*_args, **_kwargs):
        return True, None

    monkeypatch.setattr(dashboard, "_detect_bot_installed", fake_detect_installed)

    subscription_service.upsert_guild_subscription(
        _settings(),
        guild_id=123,
        plan="pro",
        status="active",
        period_end=datetime(2030, 1, 1, tzinfo=timezone.utc),
        customer_id="cus_123",
        subscription_id="sub_123",
    )

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
        assert "Audit Log" in html
        assert "Download CSV" in html
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_upgrade_redirect_records_audit_event(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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


@pytest.mark.asyncio
async def test_setup_wizard_page_renders(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    async def fake_bot_get_json(*_args, url: str, **_kwargs):
        if url.endswith("/guilds/123"):
            return {"id": "123", "name": "Managed"}
        if url.endswith("/guilds/123/roles"):
            bot_perms = (1 << 4) | (1 << 13) | (1 << 28)
            return [
                {"id": "123", "name": "@everyone", "permissions": "0", "position": 0},
                {"id": "10", "name": "Offside Bot", "permissions": str(bot_perms), "position": 10},
                {"id": "11", "name": "Coach", "permissions": "0", "position": 1},
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
            ]
        if url.endswith("/guilds/123/members/1"):
            return {"roles": ["10"], "user": {"id": "1"}}
        if "/channels/" in url and "/messages" in url:
            return [{"id": "m1", "author": {"id": "1"}}]
        raise AssertionError(f"Unexpected bot Discord URL: {url}")

    monkeypatch.setattr(dashboard, "_discord_bot_get_json", fake_bot_get_json)
    monkeypatch.setattr(
        dashboard,
        "get_guild_config",
        lambda _gid: {
            "role_coach_id": 11,
            "channel_staff_portal_id": 20,
            "channel_manager_portal_id": 21,
            "channel_club_portal_id": 22,
            "channel_coach_portal_id": 23,
            "channel_recruit_portal_id": 24,
            "channel_staff_monitor_id": 30,
            "channel_roster_listing_id": 31,
            "channel_recruit_listing_id": 32,
            "channel_club_listing_id": 33,
        },
    )

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
            "/guild/123/setup",
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 200
        html = await resp.text()
        assert "Setup Wizard" in html
        assert "/api/guild/123/ops/run_full_setup" in html
        assert "Run full setup" in html
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_run_full_setup_enqueues_tasks(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    async def fake_detect_installed(*_args, **_kwargs):
        return True, None

    monkeypatch.setattr(dashboard, "_detect_bot_installed", fake_detect_installed)

    app = dashboard.create_app(settings=_settings())
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
            "/api/guild/123/ops/run_full_setup",
            data={"csrf": "csrf_good"},
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 302
        assert resp.headers.get("Location") == "/guild/123/setup?queued=1"

        ops_tasks = database.get_global_collection(_settings(), name="ops_tasks")
        actions = {doc.get("action") for doc in ops_tasks.find({"guild_id": 123})}
        assert "run_setup" in actions
        assert "repost_portals" in actions
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ops_run_setup_enqueues_task(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    async def fake_detect_installed(*_args, **_kwargs):
        return True, None

    monkeypatch.setattr(dashboard, "_detect_bot_installed", fake_detect_installed)

    settings = _settings()
    app = dashboard.create_app(settings=settings)
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
            "/api/guild/123/ops/run_setup",
            data={"csrf": "csrf_good"},
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 302
        assert resp.headers.get("Location") == "/guild/123/overview"

        ops_tasks = database.get_global_collection(settings, name="ops_tasks")
        doc = ops_tasks.find_one({"guild_id": 123, "action": "run_setup"})
        assert doc is not None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ops_repost_portals_enqueues_task(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)

    async def fake_detect_installed(*_args, **_kwargs):
        return True, None

    monkeypatch.setattr(dashboard, "_detect_bot_installed", fake_detect_installed)

    settings = _settings()
    app = dashboard.create_app(settings=settings)
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
            "/api/guild/123/ops/repost_portals",
            data={"csrf": "csrf_good"},
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 302
        assert resp.headers.get("Location") == "/guild/123/overview"

        ops_tasks = database.get_global_collection(settings, name="ops_tasks")
        doc = ops_tasks.find_one({"guild_id": 123, "action": "repost_portals"})
        assert doc is not None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ops_schedule_delete_data_enqueues_task(monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    monkeypatch.setattr(
        entitlements_service,
        "get_guild_plan",
        lambda *_args, **_kwargs: entitlements_service.PLAN_PRO,
    )

    settings = _settings(mongodb_per_guild_db=True)
    app = dashboard.create_app(settings=settings)
    sessions = app[dashboard.SESSION_COLLECTION_KEY]
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
            "/api/guild/123/ops/schedule_delete_data",
            data={"csrf": "csrf_good", "confirm": "DELETE 123"},
            headers={"Cookie": f"{dashboard.COOKIE_NAME}=sess1"},
            allow_redirects=False,
        )
        assert resp.status == 302
        assert resp.headers.get("Location") == "/guild/123/ops"

        ops_tasks = database.get_global_collection(settings, name="ops_tasks")
        doc = ops_tasks.find_one({"guild_id": 123, "action": "delete_guild_data"})
        assert doc is not None
        assert "run_after" in doc
    finally:
        await client.close()
