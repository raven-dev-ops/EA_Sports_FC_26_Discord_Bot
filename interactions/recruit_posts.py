from __future__ import annotations

from typing import Any

import discord

from config import Settings
from interactions.recruit_embeds import build_recruit_profile_embed
from services.fc25_stats_feature import fc25_stats_enabled
from services.fc25_stats_service import get_latest_snapshot, get_link
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import edit_message, fetch_channel, send_message


async def upsert_recruit_profile_posts(
    client: discord.Client,
    *,
    settings: Settings,
    guild_id: int,
    profile: dict[str, Any],
    test_mode: bool,
) -> dict[str, int | None]:
    fc25_link = None
    fc25_snapshot = None
    if fc25_stats_enabled(settings, guild_id=guild_id):
        try:
            user_id_raw = profile.get("user_id")
            if user_id_raw is not None:
                user_id = int(user_id_raw)
                fc25_link = get_link(guild_id, user_id)
                if fc25_link:
                    fc25_snapshot = get_latest_snapshot(guild_id, user_id)
        except Exception:
            fc25_link = None
            fc25_snapshot = None

    embed = build_recruit_profile_embed(
        profile,
        fc25_link=fc25_link,
        fc25_snapshot=fc25_snapshot,
    )

    listing_channel_id = resolve_channel_id(
        settings,
        guild_id=guild_id,
        field="channel_recruit_listing_id",
        test_mode=test_mode,
    )

    staff_channel_id = None
    if test_mode:
        staff_channel_id = listing_channel_id
    else:
        staff_channel_id = resolve_channel_id(
            settings,
            guild_id=guild_id,
            field="channel_staff_monitor_id",
            test_mode=False,
        ) or resolve_channel_id(
            settings,
            guild_id=guild_id,
            field="channel_staff_portal_id",
            test_mode=False,
        )

    listing_message = None
    listing_message_id = _parse_int(profile.get("listing_message_id"))
    if listing_channel_id:
        listing_message = await _upsert_embed_post(
            client,
            channel_id=listing_channel_id,
            message_id=listing_message_id,
            embed=embed,
        )

    staff_message = None
    staff_message_id = _parse_int(profile.get("staff_message_id"))
    if staff_channel_id and (listing_message is None or staff_channel_id != listing_channel_id):
        staff_message = await _upsert_embed_post(
            client,
            channel_id=staff_channel_id,
            message_id=staff_message_id,
            embed=embed,
        )

    refs: dict[str, int | None] = {
        "listing_channel_id": listing_channel_id,
        "listing_message_id": listing_message.id if listing_message else None,
        "staff_channel_id": staff_channel_id,
        "staff_message_id": staff_message.id if staff_message else None,
    }
    if (
        staff_channel_id
        and listing_message is not None
        and staff_channel_id == listing_channel_id
    ):
        refs["staff_channel_id"] = listing_channel_id
        refs["staff_message_id"] = refs["listing_message_id"]
    return refs


async def _upsert_embed_post(
    client: discord.Client,
    *,
    channel_id: int,
    message_id: int | None,
    embed: discord.Embed,
) -> discord.Message | None:
    channel = await fetch_channel(client, channel_id)
    if channel is None:
        return None
    msg = None
    if message_id and hasattr(channel, "fetch_message"):
        try:
            msg = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
        except discord.DiscordException:
            msg = None
    if msg is not None:
        edited = await edit_message(msg, embed=embed, view=None)
        if edited is not None:
            return edited
    return await send_message(
        channel,
        embed=embed,
        allowed_mentions=discord.AllowedMentions.none(),
    )


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
