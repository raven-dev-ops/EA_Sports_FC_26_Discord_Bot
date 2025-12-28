from __future__ import annotations

from config import Settings


def resolve_channel_id(
    settings: Settings, channel_id: int, *, test_mode: bool
) -> int:
    if test_mode and settings.discord_test_channel_id:
        return settings.discord_test_channel_id
    return channel_id
