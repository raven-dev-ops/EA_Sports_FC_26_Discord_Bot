from __future__ import annotations

from typing import Any, Optional

import discord

from utils.discord_wrappers import delete_message, edit_message, fetch_channel, send_message


class DiscordAPIError(Exception):
    pass


class DiscordNotFound(DiscordAPIError):
    pass


class DiscordRateLimited(DiscordAPIError):
    pass


async def get_text_channel(client: discord.Client, channel_id: int) -> discord.abc.Messageable:
    channel = await fetch_channel(client, channel_id)
    if channel is None:
        raise DiscordNotFound(f"Channel {channel_id} not found or inaccessible.")
    return channel


async def send_channel_message(
    channel: discord.abc.Messageable,
    content: Optional[str] = None,
    **kwargs: Any,
) -> discord.Message:
    msg = await send_message(channel, content, **kwargs)
    if msg is None:
        raise DiscordAPIError("Failed to send message.")
    return msg


async def edit_channel_message(message: discord.Message, **kwargs: Any) -> discord.Message:
    msg = await edit_message(message, **kwargs)
    if msg is None:
        raise DiscordAPIError("Failed to edit message.")
    return msg


async def delete_channel_message(message: discord.Message) -> None:
    ok = await delete_message(message)
    if not ok:
        raise DiscordAPIError("Failed to delete message.")
