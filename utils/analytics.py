from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from aiohttp import ClientSession, ClientTimeout

_DEFAULT_POSTHOG_HOST = "https://app.posthog.com"


def _posthog_config() -> tuple[str, str] | None:
    api_key = os.environ.get("POSTHOG_API_KEY", "").strip()
    if not api_key:
        return None
    host = os.environ.get("POSTHOG_HOST", _DEFAULT_POSTHOG_HOST).strip() or _DEFAULT_POSTHOG_HOST
    return api_key, host.rstrip("/")


async def _posthog_capture(
    http: ClientSession,
    *,
    api_key: str,
    host: str,
    payload: dict[str, Any],
) -> None:
    url = f"{host}/capture"
    try:
        async with http.post(url, json=payload, timeout=ClientTimeout(total=2)) as resp:
            await resp.read()
    except Exception as exc:
        logging.debug("event=posthog_capture_failed error=%s", exc)


def track_event(
    http: ClientSession | None,
    *,
    distinct_id: str,
    event: str,
    properties: dict[str, Any] | None = None,
) -> None:
    if not distinct_id:
        return
    config = _posthog_config()
    if not config or http is None:
        return
    api_key, host = config
    payload = {
        "api_key": api_key,
        "event": event,
        "distinct_id": distinct_id,
        "properties": properties or {},
    }
    asyncio.create_task(_posthog_capture(http, api_key=api_key, host=host, payload=payload))
