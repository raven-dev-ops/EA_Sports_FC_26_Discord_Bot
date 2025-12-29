from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

import discord

from utils.cache import TTLCache

T = TypeVar("T")

_CHANNEL_CACHE = TTLCache[discord.abc.Messageable](ttl_seconds=60.0)


async def with_backoff(
    coro_func: Callable[[], Awaitable[T]],
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    timeout: float = 10.0,
) -> T:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return await asyncio.wait_for(coro_func(), timeout=timeout)
        except discord.HTTPException as exc:
            last_exc = exc
            delay = getattr(exc, "retry_after", None) or base_delay * (2**attempt)
            if attempt == retries - 1:
                break
            await asyncio.sleep(float(delay))
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
    cache_key = f"channel:{channel_id}"
    cached = _CHANNEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    def _as_messageable(ch: object | None) -> discord.abc.Messageable | None:
        if isinstance(ch, discord.abc.Messageable):
            return ch
        return None

    async def _do() -> discord.abc.Messageable | None:
        ch = _as_messageable(client.get_channel(channel_id))
        if ch is not None:
            return ch
        fetched = await client.fetch_channel(channel_id)
        return _as_messageable(fetched)

    try:
        ch = await with_backoff(_do)
        if ch:
            _CHANNEL_CACHE.set(cache_key, ch)
        return ch
    except discord.DiscordException:
        return None


async def send_message(
    channel: discord.abc.Messageable,
    content: str | None = None,
    **kwargs: Any,
) -> discord.Message | None:
    if "allowed_mentions" not in kwargs:
        kwargs["allowed_mentions"] = discord.AllowedMentions(
            everyone=False, users=True, roles=False, replied_user=False
        )
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
