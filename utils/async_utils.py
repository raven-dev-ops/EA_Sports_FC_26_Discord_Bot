from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

import discord

T = TypeVar("T")


async def with_backoff(
    coro_func: Callable[[], Awaitable[T]],
    *,
    retries: int = 3,
    base_delay: float = 0.5,
) -> T:
    """Run a coroutine factory with exponential backoff on Discord HTTP errors."""
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
