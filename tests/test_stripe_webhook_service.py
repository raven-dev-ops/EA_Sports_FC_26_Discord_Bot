from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import mongomock

import database
from config.settings import Settings
from database import get_global_collection
from services import stripe_webhook_service, subscription_service


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
        role_coach_plus_id=None,
        role_club_manager_id=3,
        role_club_manager_plus_id=None,
        role_league_staff_id=4,
        role_league_owner_id=5,
        role_free_agent_id=6,
        role_pro_player_id=7,
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


def _sig_header(*, payload: bytes, secret: str, timestamp: int) -> str:
    signed_payload = str(timestamp).encode("utf-8") + b"." + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={expected}"


def test_subscription_updated_event_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    settings = _settings()

    subscription_service.ensure_subscription_indexes(settings)
    stripe_webhook_service.ensure_stripe_webhook_indexes(settings)

    event = {
        "id": "evt_123",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_123",
                "status": "active",
                "current_period_end": int(datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()),
                "metadata": {"guild_id": "123", "plan": "pro"},
            }
        },
    }
    payload = json.dumps(event).encode("utf-8")
    secret = "whsec_test"
    timestamp = int(time.time())
    result = stripe_webhook_service.handle_stripe_webhook(
        settings,
        payload=payload,
        sig_header=_sig_header(payload=payload, secret=secret, timestamp=timestamp),
        secret=secret,
    )
    assert result.status == "processed"
    assert result.guild_id == 123

    doc = subscription_service.get_guild_subscription(settings, guild_id=123)
    assert doc is not None
    assert doc["plan"] == "pro"
    assert doc["status"] == "active"
    assert doc["subscription_id"] == "sub_123"
    assert doc["customer_id"] == "cus_123"

    duplicate = stripe_webhook_service.handle_stripe_webhook(
        settings,
        payload=payload,
        sig_header=_sig_header(payload=payload, secret=secret, timestamp=timestamp),
        secret=secret,
    )
    assert duplicate.status in {"duplicate", "in_progress"}


def test_invalid_signature_rejected(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    settings = _settings()
    stripe_webhook_service.ensure_stripe_webhook_indexes(settings)

    payload = b'{"id":"evt_1","type":"checkout.session.completed","data":{"object":{}}}'
    try:
        stripe_webhook_service.handle_stripe_webhook(
            settings,
            payload=payload,
            sig_header="t=1,v1=deadbeef",
            secret="whsec_test",
        )
    except ValueError as exc:
        assert "signature" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError")


def test_unknown_event_is_dead_lettered(monkeypatch) -> None:
    monkeypatch.setattr(database, "MongoClient", mongomock.MongoClient)
    monkeypatch.setattr(database, "_CLIENT", None)
    settings = _settings()
    stripe_webhook_service.ensure_stripe_webhook_indexes(settings)

    event = {"id": "evt_unknown", "type": "account.updated", "data": {"object": {"id": "acct_1"}}}
    payload = json.dumps(event).encode("utf-8")
    secret = "whsec_test"
    timestamp = int(time.time())
    result = stripe_webhook_service.handle_stripe_webhook(
        settings,
        payload=payload,
        sig_header=_sig_header(payload=payload, secret=secret, timestamp=timestamp),
        secret=secret,
    )
    assert result.status == "processed"
    assert result.handled == "dead_lettered"

    dead_letters = get_global_collection(
        settings, name=stripe_webhook_service.STRIPE_DEAD_LETTERS_COLLECTION
    )
    assert dead_letters.find_one({"_id": "evt_unknown"}) is not None

