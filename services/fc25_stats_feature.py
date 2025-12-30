from __future__ import annotations

from config.settings import Settings
from services import entitlements_service
from services.guild_config_service import get_guild_config
from utils.flags import feature_enabled

GUILD_OVERRIDE_KEY = "fc25_stats_enabled"


def fc25_stats_enabled(settings: Settings | None, *, guild_id: int | None) -> bool:
    """
    FC25 stats are enabled when the global feature flag is on and the guild override (if present) allows it.

    Per-guild override:
    - key: `fc25_stats_enabled`
    - values: true/false (bool or common string forms)
    """
    if settings is None:
        return False
    if not feature_enabled("fc25_stats", settings):
        return False
    if guild_id is None:
        return True
    if not entitlements_service.is_feature_enabled(
        settings,
        guild_id=guild_id,
        feature_key=entitlements_service.FEATURE_FC25_STATS,
    ):
        return False
    if not settings.mongodb_uri:
        return True

    try:
        cfg = get_guild_config(guild_id)
    except Exception:
        return True

    raw = cfg.get(GUILD_OVERRIDE_KEY)
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return bool(raw)
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    return True
