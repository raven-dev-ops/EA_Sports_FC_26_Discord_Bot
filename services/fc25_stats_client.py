from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from config.settings import Settings

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://proclubs.ea.com/api/fc25/clubs"


class FC25Error(Exception):
    pass


class FC25NotFound(FC25Error):
    pass


@dataclass(frozen=True)
class FC25RateLimited(FC25Error):
    retry_after_seconds: float | None = None


class FC25TransientError(FC25Error):
    pass


class FC25ParseError(FC25Error):
    pass


class FC25StatsClient:
    def __init__(
        self,
        *,
        settings: Settings,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self.settings = settings
        self.base_url = base_url.rstrip("/")

    async def get_club_matches(
        self,
        platform_key: str,
        club_id: int,
        *,
        match_type: str = "gameType",
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{platform_key}/clubId/{club_id}/matches"
        return await self._get_json(url, params={"matchType": match_type})

    async def get_members_career_stats(
        self,
        platform_key: str,
        club_id: int,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{platform_key}/clubId/{club_id}/members/career/stats"
        return await self._get_json(url)

    async def _get_json(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=float(self.settings.fc25_stats_http_timeout_seconds))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(url, params=params) as resp:
                    status = resp.status
                    if status == 404:
                        LOGGER.info("FC25 not found (url=%s).", url)
                        raise FC25NotFound("Not found.")
                    if status == 429:
                        retry_after = resp.headers.get("Retry-After")
                        retry_after_seconds = None
                        if retry_after:
                            try:
                                retry_after_seconds = float(str(retry_after).strip())
                            except ValueError:
                                retry_after_seconds = None
                        LOGGER.warning(
                            "FC25 rate limited (url=%s retry_after=%s).",
                            url,
                            retry_after_seconds,
                        )
                        raise FC25RateLimited(retry_after_seconds=retry_after_seconds)
                    if status >= 500:
                        LOGGER.warning("FC25 upstream error (status=%s url=%s).", status, url)
                        raise FC25TransientError(f"Upstream error (status={status}).")
                    if status != 200:
                        LOGGER.warning("FC25 unexpected status (status=%s url=%s).", status, url)
                        raise FC25TransientError(f"Unexpected status (status={status}).")
                    try:
                        data = await resp.json(content_type=None)
                    except Exception as exc:
                        LOGGER.warning("FC25 JSON parse failed (url=%s).", url)
                        raise FC25ParseError("Failed to parse JSON.") from exc
            except asyncio.TimeoutError as exc:
                LOGGER.warning("FC25 request timed out (url=%s).", url)
                raise FC25TransientError("Request timed out.") from exc
            except aiohttp.ClientError as exc:
                LOGGER.warning("FC25 HTTP client error (url=%s): %s", url, exc)
                raise FC25TransientError("HTTP client error.") from exc

        if not isinstance(data, dict):
            LOGGER.warning("FC25 JSON shape mismatch (expected object url=%s).", url)
            raise FC25ParseError("Expected JSON object.")
        return data
