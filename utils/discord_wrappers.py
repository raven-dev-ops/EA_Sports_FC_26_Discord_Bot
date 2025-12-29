from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

import discord

T = TypeVar("T")


async def with_backoff(
    coro_func: Callable[[], Awaitable[T]],
    *,
    retries: int = 3,
    base_delay: float = 0.5,
) -> T:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return await coro_func()
        except discord.HTTPException as exc:
            last_exc = exc
            if attempt == retries - 1:
                break
            await asyncio.sleep(base_delay * (2**attempt))
        except Exception as exc:
            last_exc = exc
            if attempt == retries - 1:
                break
            await asyncio.sleep(base_delay * (2**attempt))
    if last_exc:
        raise last_exc
    raise RuntimeError("with_backoff exhausted without exception detail")


async def fetch_channel(
    client: discord.Client,
    channel_id: int,
) -> discord.abc.Messageable | None:
    async def _do() -> discord.abc.Messageable | None:
        ch = client.get_channel(channel_id)
        if ch is not None:
            return ch
        return await client.fetch_channel(channel_id)

    try:
        return await with_backoff(_do)
    except discord.DiscordException:
        return None


async def send_message(
    channel: discord.abc.Messageable,
    content: str | None = None,
    **kwargs: Any,
) -> discord.Message | None:
    async def _do() -> discord.Message:
        return await channel.send(content, **kwargs)

    try:
        return await with_backoff(_do)
    except discord.DiscordException:
        return None


async def edit_message(
    message: discord.Message,
    **kwargs: Any,
) -> discord.Message | None:
    async def _do() -> discord.Message:
        return await message.edit(**kwargs)

    try:
        return await with_backoff(_do)
    except discord.DiscordException:
        return None


async def delete_message(message: discord.Message) -> bool:
    async def _do() -> None:
        await message.delete()

    try:
        await with_backoff(_do)
        return True
    except discord.DiscordException:
        return False
