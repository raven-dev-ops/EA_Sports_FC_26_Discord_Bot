from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Final

from pymongo import ReturnDocument
from pymongo.collection import Collection

from config import Settings
from database import get_global_collection
from services import entitlements_service
from services.audit_log_service import record_audit_event
from services.subscription_service import (
    get_guild_subscription_by_subscription_id,
    upsert_guild_subscription,
)

STRIPE_EVENTS_COLLECTION: Final[str] = "stripe_webhook_events"
STRIPE_DEAD_LETTERS_COLLECTION: Final[str] = "stripe_webhook_dead_letters"

STRIPE_SIGNATURE_TOLERANCE_SECONDS: Final[int] = 300
STRIPE_EVENT_TTL_DAYS: Final[int] = 90
STRIPE_PROCESSING_STALE_SECONDS: Final[int] = 600


@dataclass(frozen=True)
class StripeWebhookResult:
    event_id: str
    event_type: str
    status: str
    handled: str | None = None
    guild_id: int | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_guild_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return int(raw)
    return None


def _metadata_dict(obj: dict[str, Any]) -> dict[str, Any]:
    raw = obj.get("metadata")
    return raw if isinstance(raw, dict) else {}


def ensure_stripe_webhook_indexes(settings: Settings) -> None:
    events = get_global_collection(settings, name=STRIPE_EVENTS_COLLECTION)
    dead_letters = get_global_collection(settings, name=STRIPE_DEAD_LETTERS_COLLECTION)

    ttl_seconds = STRIPE_EVENT_TTL_DAYS * 24 * 60 * 60
    events.create_index("received_at", expireAfterSeconds=ttl_seconds, name="ttl_received_at")
    dead_letters.create_index("received_at", expireAfterSeconds=ttl_seconds, name="ttl_received_at")
    events.create_index("status", name="idx_status")


def verify_stripe_signature(
    payload: bytes,
    *,
    sig_header: str,
    secret: str,
    tolerance_seconds: int = STRIPE_SIGNATURE_TOLERANCE_SECONDS,
) -> bool:
    timestamp_raw: str | None = None
    sigs: list[str] = []
    for part in (sig_header or "").split(","):
        key, _, value = part.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "t":
            timestamp_raw = value
        elif key == "v1":
            sigs.append(value)

    if not timestamp_raw or not timestamp_raw.isdigit() or not sigs:
        return False
    timestamp = int(timestamp_raw)
    if tolerance_seconds > 0 and abs(time.time() - timestamp) > tolerance_seconds:
        return False

    signed_payload = timestamp_raw.encode("utf-8") + b"." + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in sigs)


def _dead_letter(
    col: Collection,
    *,
    event_id: str,
    event_type: str,
    reason: str,
    payload: dict[str, Any],
) -> None:
    now = _utc_now()
    col.update_one(
        {"_id": event_id},
        {
            "$setOnInsert": {
                "_id": event_id,
                "received_at": now,
                "event_type": event_type,
                "reason": reason,
                "payload": payload,
            }
        },
        upsert=True,
    )


def handle_stripe_webhook(
    settings: Settings,
    *,
    payload: bytes,
    sig_header: str,
    secret: str,
) -> StripeWebhookResult:
    log = logging.getLogger(__name__)
    if not verify_stripe_signature(payload, sig_header=sig_header, secret=secret):
        raise ValueError("Invalid Stripe signature.")

    try:
        event = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid Stripe JSON payload.") from exc
    if not isinstance(event, dict):
        raise ValueError("Stripe payload must be a JSON object.")

    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    if not event_id or not event_type:
        raise ValueError("Stripe payload missing id/type.")

    events = get_global_collection(settings, name=STRIPE_EVENTS_COLLECTION)
    dead_letters = get_global_collection(settings, name=STRIPE_DEAD_LETTERS_COLLECTION)

    existing = events.find_one({"_id": event_id}) or {}
    if isinstance(existing, dict) and existing.get("status") == "processed":
        log.info(
            "stripe_webhook_duplicate",
            extra={"event_id": event_id, "event_type": event_type, "handled": existing.get("handled")},
        )
        return StripeWebhookResult(event_id=event_id, event_type=event_type, status="duplicate")

    now = _utc_now()
    stale_before = now - timedelta(seconds=STRIPE_PROCESSING_STALE_SECONDS)
    claimed = events.find_one_and_update(
        {
            "_id": event_id,
            "$or": [
                {"status": {"$ne": "processing"}},
                {"processing_started_at": {"$lt": stale_before}},
            ],
        },
        {
            "$set": {
                "status": "processing",
                "type": event_type,
                "processing_started_at": now,
                "last_seen_at": now,
            },
            "$setOnInsert": {"received_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if claimed is None:
        log.info(
            "stripe_webhook_in_progress",
            extra={"event_id": event_id, "event_type": event_type, "status": "in_progress"},
        )
        return StripeWebhookResult(event_id=event_id, event_type=event_type, status="in_progress")

    handled = "ignored"
    guild_id: int | None = None

    try:
        raw_data = event.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        raw_obj = data.get("object")
        obj: dict[str, Any] = raw_obj if isinstance(raw_obj, dict) else {}

        if event_type == "checkout.session.completed":
            meta = _metadata_dict(obj)
            guild_id = _parse_guild_id(meta.get("guild_id"))
            plan = str(meta.get("plan") or entitlements_service.PLAN_PRO).strip().lower()
            customer_id = obj.get("customer")
            subscription_id = obj.get("subscription")
            if guild_id is None:
                _dead_letter(
                    dead_letters,
                    event_id=event_id,
                    event_type=event_type,
                    reason="missing_guild_id_metadata",
                    payload=event,
                )
                handled = "dead_lettered"
            else:
                upsert_guild_subscription(
                    settings,
                    guild_id=guild_id,
                    plan=plan,
                    status="checkout_completed",
                    period_end=None,
                    customer_id=str(customer_id) if customer_id else None,
                    subscription_id=str(subscription_id) if subscription_id else None,
                )
                entitlements_service.invalidate_guild_plan(guild_id)
                handled = "checkout_completed"

        elif event_type.startswith("customer.subscription."):
            meta = _metadata_dict(obj)
            guild_id = _parse_guild_id(meta.get("guild_id"))
            plan = str(meta.get("plan") or entitlements_service.PLAN_PRO).strip().lower()
            status = str(obj.get("status") or "").strip().lower() or "unknown"
            customer_id = obj.get("customer")
            subscription_id = obj.get("id")
            period_end_raw = obj.get("current_period_end")
            period_end = None
            if isinstance(period_end_raw, (int, float)):
                period_end = datetime.fromtimestamp(float(period_end_raw), tz=timezone.utc)

            if guild_id is None:
                _dead_letter(
                    dead_letters,
                    event_id=event_id,
                    event_type=event_type,
                    reason="missing_guild_id_metadata",
                    payload=event,
                )
                handled = "dead_lettered"
            else:
                upsert_guild_subscription(
                    settings,
                    guild_id=guild_id,
                    plan=plan,
                    status=status,
                    period_end=period_end,
                    customer_id=str(customer_id) if customer_id else None,
                    subscription_id=str(subscription_id) if subscription_id else None,
                )
                entitlements_service.invalidate_guild_plan(guild_id)
                handled = "subscription_updated"

        elif event_type == "invoice.payment_failed":
            subscription_id = obj.get("subscription")
            sub_id = str(subscription_id) if subscription_id else ""
            sub = get_guild_subscription_by_subscription_id(settings, subscription_id=sub_id) if sub_id else None
            if not sub:
                _dead_letter(
                    dead_letters,
                    event_id=event_id,
                    event_type=event_type,
                    reason="unknown_subscription_id",
                    payload=event,
                )
                handled = "dead_lettered"
            else:
                guild_id = _parse_guild_id(sub.get("guild_id")) or _parse_guild_id(sub.get("_id"))
                if guild_id is None:
                    _dead_letter(
                        dead_letters,
                        event_id=event_id,
                        event_type=event_type,
                        reason="missing_guild_id_in_subscription_doc",
                        payload=event,
                    )
                    handled = "dead_lettered"
                else:
                    upsert_guild_subscription(
                        settings,
                        guild_id=guild_id,
                        plan=str(sub.get("plan") or entitlements_service.PLAN_FREE),
                        status="payment_failed",
                        period_end=sub.get("period_end") if isinstance(sub.get("period_end"), datetime) else None,
                        customer_id=str(sub.get("customer_id") or obj.get("customer") or "") or None,
                        subscription_id=sub_id or None,
                    )
                    entitlements_service.invalidate_guild_plan(guild_id)
                    handled = "payment_failed"

        elif event_type == "invoice.paid":
            subscription_id = obj.get("subscription")
            sub_id = str(subscription_id) if subscription_id else ""
            sub = get_guild_subscription_by_subscription_id(settings, subscription_id=sub_id) if sub_id else None
            if not sub:
                _dead_letter(
                    dead_letters,
                    event_id=event_id,
                    event_type=event_type,
                    reason="unknown_subscription_id",
                    payload=event,
                )
                handled = "dead_lettered"
            else:
                guild_id = _parse_guild_id(sub.get("guild_id")) or _parse_guild_id(sub.get("_id"))
                if guild_id is None:
                    _dead_letter(
                        dead_letters,
                        event_id=event_id,
                        event_type=event_type,
                        reason="missing_guild_id_in_subscription_doc",
                        payload=event,
                    )
                    handled = "dead_lettered"
                else:
                    upsert_guild_subscription(
                        settings,
                        guild_id=guild_id,
                        plan=str(sub.get("plan") or entitlements_service.PLAN_PRO),
                        status="active",
                        period_end=sub.get("period_end") if isinstance(sub.get("period_end"), datetime) else None,
                        customer_id=str(sub.get("customer_id") or obj.get("customer") or "") or None,
                        subscription_id=sub_id or None,
                    )
                    entitlements_service.invalidate_guild_plan(guild_id)
                    handled = "invoice_paid"

        else:
            _dead_letter(
                dead_letters,
                event_id=event_id,
                event_type=event_type,
                reason="unhandled_event_type",
                payload=event,
            )
            handled = "dead_lettered"

    except Exception as exc:
        events.update_one(
            {"_id": event_id},
            {"$set": {"status": "failed", "failed_at": _utc_now(), "error": str(exc)}},
        )
        log.exception("stripe_webhook_failed", extra={"event_id": event_id, "event_type": event_type})
        raise

    events.update_one(
        {"_id": event_id},
        {
            "$set": {
                "status": "processed",
                "processed_at": _utc_now(),
                "handled": handled,
                "guild_id": guild_id,
            }
        },
    )

    if guild_id is not None:
        try:
            record_audit_event(
                guild_id=guild_id,
                category="billing",
                action=f"stripe.{handled or event_type}",
                source="stripe_webhook",
                details={
                    "event_id": event_id,
                    "event_type": event_type,
                    "handled": handled,
                    "status": "processed",
                },
            )
        except Exception:
            pass

    log.info(
        "stripe_webhook_processed",
        extra={"event_id": event_id, "event_type": event_type, "handled": handled, "guild_id": guild_id},
    )
    return StripeWebhookResult(
        event_id=event_id,
        event_type=event_type,
        status="processed",
        handled=handled,
        guild_id=guild_id,
    )
