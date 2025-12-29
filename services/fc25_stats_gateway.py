from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from config.settings import Settings
from services.fc25_stats_client import (
    FC25ParseError,
    FC25RateLimited,
    FC25StatsClient,
    FC25TransientError,
)
from utils.cache import TTLCache

RATE_LIMIT_WINDOW_SECONDS = 600.0
FAILURE_THRESHOLD = 3
BREAKER_COOLDOWN_SECONDS = 60.0


@dataclass(frozen=True)
class FC25GatewayResult:
    data: dict[str, Any]
    from_cache: bool


class FC25StatsGateway:
    def __init__(self, *, settings: Settings, client: FC25StatsClient | None = None) -> None:
        self.settings = settings
        self.client = client or FC25StatsClient(settings=settings)
        self.cache = TTLCache[dict[str, Any]](ttl_seconds=float(settings.fc25_stats_cache_ttl_seconds))
        self._guild_calls: dict[int, list[float]] = {}
        self._user_calls: dict[int, list[float]] = {}
        self._breaker: dict[str, tuple[int, float]] = {}
        self._semaphore = asyncio.Semaphore(int(settings.fc25_stats_max_concurrency))
        self._inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._inflight_lock = asyncio.Lock()

    async def get_members_career_stats(
        self,
        *,
        guild_id: int,
        user_id: int,
        platform_key: str,
        club_id: int,
    ) -> FC25GatewayResult:
        cache_key = f"members:{platform_key}:{club_id}"
        return await self._get_or_fetch(
            cache_key,
            guild_id=guild_id,
            user_id=user_id,
            fetch=lambda: self.client.get_members_career_stats(platform_key, club_id),
        )

    async def get_club_matches(
        self,
        *,
        guild_id: int,
        user_id: int,
        platform_key: str,
        club_id: int,
        match_type: str = "gameType",
    ) -> FC25GatewayResult:
        cache_key = f"matches:{platform_key}:{club_id}:{match_type}"
        return await self._get_or_fetch(
            cache_key,
            guild_id=guild_id,
            user_id=user_id,
            fetch=lambda: self.client.get_club_matches(platform_key, club_id, match_type=match_type),
        )

    async def _get_or_fetch(
        self,
        cache_key: str,
        *,
        guild_id: int,
        user_id: int,
        fetch: Callable[[], Awaitable[dict[str, Any]]],
    ) -> FC25GatewayResult:
        cached = self.cache.get(cache_key)
        if cached is not None:
            return FC25GatewayResult(data=cached, from_cache=True)

        if self._breaker_open(cache_key):
            raise FC25TransientError("FC25 stats temporarily unavailable (circuit breaker open).")

        task: asyncio.Task[dict[str, Any]] | None = None
        created = False
        async with self._inflight_lock:
            task = self._inflight.get(cache_key)
            if task is None:
                self._enforce_rate_limits(guild_id=guild_id, user_id=user_id)

                async def _wrapped() -> dict[str, Any]:
                    async with self._semaphore:
                        return await fetch()

                task = asyncio.create_task(_wrapped())
                self._inflight[cache_key] = task
                created = True

        try:
            data = await task
        except (FC25TransientError, FC25ParseError):
            self._record_failure(cache_key)
            cached = self.cache.get(cache_key)
            if cached is not None:
                return FC25GatewayResult(data=cached, from_cache=True)
            raise
        finally:
            if created:
                async with self._inflight_lock:
                    if self._inflight.get(cache_key) is task:
                        self._inflight.pop(cache_key, None)

        self._reset_breaker(cache_key)
        self.cache.set(cache_key, data)
        return FC25GatewayResult(data=data, from_cache=False)

    def _enforce_rate_limits(self, *, guild_id: int, user_id: int) -> None:
        now = time.monotonic()
        self._prune(self._guild_calls.setdefault(guild_id, []), now)
        self._prune(self._user_calls.setdefault(user_id, []), now)

        guild_limit = int(self.settings.fc25_stats_rate_limit_per_guild)
        user_limit = max(5, guild_limit // 2)

        if len(self._guild_calls[guild_id]) >= guild_limit:
            retry = self._retry_after_seconds(self._guild_calls[guild_id], now)
            raise FC25RateLimited(retry_after_seconds=retry)
        if len(self._user_calls[user_id]) >= user_limit:
            retry = self._retry_after_seconds(self._user_calls[user_id], now)
            raise FC25RateLimited(retry_after_seconds=retry)

        self._guild_calls[guild_id].append(now)
        self._user_calls[user_id].append(now)

    def _prune(self, calls: list[float], now: float) -> None:
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        while calls and calls[0] < cutoff:
            calls.pop(0)

    def _retry_after_seconds(self, calls: list[float], now: float) -> float | None:
        if not calls:
            return None
        oldest = calls[0]
        remaining = RATE_LIMIT_WINDOW_SECONDS - (now - oldest)
        return max(0.0, remaining)

    def _breaker_open(self, key: str) -> bool:
        state = self._breaker.get(key)
        if not state:
            return False
        failures, open_until = state
        if failures < FAILURE_THRESHOLD:
            return False
        if time.monotonic() >= open_until:
            self._breaker.pop(key, None)
            return False
        return True

    def _record_failure(self, key: str) -> None:
        failures, _open_until = self._breaker.get(key, (0, 0.0))
        failures += 1
        open_until = 0.0
        if failures >= FAILURE_THRESHOLD:
            open_until = time.monotonic() + BREAKER_COOLDOWN_SECONDS
        self._breaker[key] = (failures, open_until)

    def _reset_breaker(self, key: str) -> None:
        self._breaker.pop(key, None)
