from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Final

from config import Settings
from services.subscription_service import get_guild_subscription

PLAN_FREE: Final[str] = "free"
PLAN_PRO: Final[str] = "pro"

FEATURE_PREMIUM_COACH_TIERS: Final[str] = "premium_coach_tiers"
FEATURE_PREMIUM_COACHES_REPORT: Final[str] = "premium_coaches_report"
FEATURE_FC25_STATS: Final[str] = "fc25_stats"
FEATURE_BANLIST: Final[str] = "banlist"
FEATURE_TOURNAMENT_AUTOMATION: Final[str] = "tournament_automation"

PRO_FEATURE_KEYS: Final[set[str]] = {
    FEATURE_PREMIUM_COACH_TIERS,
    FEATURE_PREMIUM_COACHES_REPORT,
    FEATURE_FC25_STATS,
    FEATURE_BANLIST,
    FEATURE_TOURNAMENT_AUTOMATION,
}

_CACHE_TTL_SECONDS: float = 15.0
_PLAN_CACHE: dict[int, tuple[float, str]] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_get(*, guild_id: int) -> str | None:
    item = _PLAN_CACHE.get(guild_id)
    if not item:
        return None
    expires_at, plan = item
    if expires_at < time.time():
        _PLAN_CACHE.pop(guild_id, None)
        return None
    return plan


def _cache_set(*, guild_id: int, plan: str) -> None:
    _PLAN_CACHE[guild_id] = (time.time() + _CACHE_TTL_SECONDS, plan)


def invalidate_guild_plan(guild_id: int) -> None:
    _PLAN_CACHE.pop(guild_id, None)


def invalidate_all() -> None:
    _PLAN_CACHE.clear()


def _forced_pro_guild_ids() -> set[int]:
    raw = os.environ.get("ENTITLEMENTS_FORCE_PRO_GUILDS", "").strip()
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if token.isdigit():
            out.add(int(token))
    return out


def _plan_from_subscription_doc(doc: dict) -> str:
    status = str(doc.get("status") or "").strip().lower()
    if status not in {"active", "trialing"}:
        return PLAN_FREE

    period_end = doc.get("period_end")
    if isinstance(period_end, datetime) and period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    if isinstance(period_end, datetime) and period_end < _utc_now():
        return PLAN_FREE

    plan = str(doc.get("plan") or "").strip().lower()
    if plan == PLAN_PRO:
        return PLAN_PRO
    return PLAN_FREE


def get_guild_plan(settings: Settings | None, *, guild_id: int) -> str:
    cached = _cache_get(guild_id=guild_id)
    if cached is not None:
        return cached

    if guild_id in _forced_pro_guild_ids():
        _cache_set(guild_id=guild_id, plan=PLAN_PRO)
        return PLAN_PRO

    if settings is None or not settings.mongodb_uri:
        _cache_set(guild_id=guild_id, plan=PLAN_FREE)
        return PLAN_FREE

    doc = get_guild_subscription(settings, guild_id=guild_id)
    plan = _plan_from_subscription_doc(doc) if doc else PLAN_FREE
    _cache_set(guild_id=guild_id, plan=plan)
    return plan


def is_feature_enabled(settings: Settings | None, *, guild_id: int, feature_key: str) -> bool:
    key = feature_key.strip().lower()
    if key in {k.lower() for k in PRO_FEATURE_KEYS}:
        return get_guild_plan(settings, guild_id=guild_id) == PLAN_PRO
    return True

