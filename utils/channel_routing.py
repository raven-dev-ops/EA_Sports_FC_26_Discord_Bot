from __future__ import annotations

from typing import Any

from config import Settings
from services.guild_config_service import get_guild_config


def resolve_channel_id(
    settings: Settings,
    *,
    guild_id: int | None,
    field: str,
    test_mode: bool,
) -> int | None:
    """
    Resolve a configured channel ID for a guild.

    Resolution order:
    1) Per-guild config from Mongo (`guild_settings`)
    2) Environment override from `Settings`

    Test mode:
    - When enabled, all channel routing is redirected to `channel_staff_monitor_id` (if present).
    """
    if test_mode:
        sink = _resolve_config_int(settings, guild_id=guild_id, field="channel_staff_monitor_id")
        if sink:
            return sink
    return _resolve_config_int(settings, guild_id=guild_id, field=field)


def _mongo_enabled(settings: Settings) -> bool:
    return bool(settings.mongodb_uri and settings.mongodb_db_name and settings.mongodb_collection)


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_config_int(settings: Settings, *, guild_id: int | None, field: str) -> int | None:
    if guild_id and _mongo_enabled(settings):
        try:
            cfg = get_guild_config(guild_id)
        except Exception:
            cfg = {}
        value = _parse_int(cfg.get(field))
        if value:
            return value

    value = getattr(settings, field, None)
    return _parse_int(value) or None
