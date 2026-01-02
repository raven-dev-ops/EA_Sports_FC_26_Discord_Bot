from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import mongomock
import pytest
from PIL import Image, ImageChops
from playwright.async_api import async_playwright

import database
from config.settings import Settings
from offside_bot import dashboard

BASELINES_DIR = Path(__file__).resolve().parent / "baselines"
VIEWPORT = {"width": 1280, "height": 720}


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


def _update_baselines() -> bool:
    return os.getenv("UPDATE_VISUAL_BASELINES", "").strip().lower() in {"1", "true", "yes"}


async def _snapshot(page, *, url: str, name: str) -> None:
    await page.goto(url, wait_until="networkidle")
    snapshot_path = BASELINES_DIR / f"{name}.png"
    if _update_baselines():
        BASELINES_DIR.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=snapshot_path, full_page=True)
        return
    if not snapshot_path.exists():
        raise AssertionError(f"Missing baseline {snapshot_path}. Run UPDATE_VISUAL_BASELINES=1 to create it.")
    actual_path = snapshot_path.with_suffix(".actual.png")
    await page.screenshot(path=actual_path, full_page=True)
    with Image.open(snapshot_path) as baseline, Image.open(actual_path) as actual:
        if baseline.size != actual.size:
            raise AssertionError(
                f"Visual diff for {name}: size mismatch {baseline.size} vs {actual.size}."
            )
        diff = ImageChops.difference(baseline, actual).convert("L")
        diff_pixels = sum(1 for value in diff.getdata() if value)
    max_diff_pixels = int(os.getenv("VISUAL_MAX_DIFF_PIXELS", "0"))
    if diff_pixels > max_diff_pixels:
        raise AssertionError(
            f"Visual diff for {name}: {diff_pixels} pixels differ (max {max_diff_pixels}). "
            f"Actual: {actual_path}"
        )
    actual_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_visual_regression(monkeypatch) -> None:
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
            return [{"id": "123", "name": "Managed", "owner": False, "permissions": str(1 << 5)}]
        raise AssertionError(f"Unexpected Discord URL: {url}")

    async def fake_detect_installed(*_args, **_kwargs):
        return True, None

    fake_stripe = types.SimpleNamespace()
    fake_stripe.api_key = ""
    fake_stripe.checkout = types.SimpleNamespace(
        Session=types.SimpleNamespace(create=lambda *_args, **_kwargs: types.SimpleNamespace(url=""))
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    monkeypatch.setattr(dashboard, "_exchange_code", fake_exchange_code)
    monkeypatch.setattr(dashboard, "_discord_get_json", fake_discord_get_json)
    monkeypatch.setattr(dashboard, "_detect_bot_installed", fake_detect_installed)

    app = dashboard.create_app(settings=_settings())
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        login_qs = urlencode({"next": "/app"})
        resp = await client.get(f"/login?{login_qs}", allow_redirects=False)
        auth_location = resp.headers.get("Location")
        assert auth_location
        state = parse_qs(urlparse(auth_location).query).get("state", [""])[0]
        assert state
        resp = await client.get(f"/oauth/callback?code=abc&state={state}", allow_redirects=False)
        cookie = resp.cookies.get(dashboard.COOKIE_NAME)
        assert cookie is not None
        base_url = str(server.make_url("/")).rstrip("/")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            context = await browser.new_context(viewport=VIEWPORT, reduced_motion="reduce")
            await context.add_cookies(
                [
                    {
                        "name": dashboard.COOKIE_NAME,
                        "value": cookie.value,
                        "url": base_url,
                    }
                ]
            )
            page = await context.new_page()
            await _snapshot(page, url=f"{base_url}/", name="landing")
            await _snapshot(page, url=f"{base_url}/pricing", name="pricing")
            await _snapshot(page, url=f"{base_url}/app", name="server_picker")
            await _snapshot(page, url=f"{base_url}/app/billing?guild_id=123", name="billing")
            await context.close()
            await browser.close()
    finally:
        await client.close()
