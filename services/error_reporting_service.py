from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from config import Settings

_SENSITIVE_KEY_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "private_key",
)

_INITIALIZED = False


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(substr in lowered for substr in _SENSITIVE_KEY_SUBSTRINGS)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        scrubbed: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_sensitive_key(k):
                scrubbed[k] = "[Filtered]"
            else:
                scrubbed[k] = _scrub(v)
        return scrubbed
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _before_send(event: Any, hint: dict[str, Any]) -> Any | None:  # noqa: ARG001
    try:
        return _scrub(event)
    except Exception:
        return event


def _read_version() -> str:
    try:
        version_path = Path(__file__).resolve().parents[1] / "VERSION"
        return version_path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def init_error_reporting(*, settings: Settings, service_name: str) -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return

    try:
        import sentry_sdk  # type: ignore[import-not-found]
        from sentry_sdk.integrations.aiohttp import (
            AioHttpIntegration,  # type: ignore[import-not-found]
        )
        from sentry_sdk.integrations.logging import (
            LoggingIntegration,  # type: ignore[import-not-found]
        )
    except Exception:
        logging.warning("Sentry SDK not installed; skipping error reporting.")
        return

    environment = os.getenv("SENTRY_ENVIRONMENT", "production").strip() or "production"
    release = os.getenv("SENTRY_RELEASE", "").strip()
    if not release:
        version = _read_version()
        release = f"offside-bot@{version}" if version else "offside-bot"

    traces_sample_rate = os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0").strip()
    try:
        traces_sample_rate_f = float(traces_sample_rate) if traces_sample_rate else 0.0
    except ValueError:
        traces_sample_rate_f = 0.0

    integrations: list[Any] = [
        LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        AioHttpIntegration(),
    ]

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        send_default_pii=False,
        before_send=_before_send,
        integrations=integrations,
        traces_sample_rate=traces_sample_rate_f,
    )

    try:
        sentry_sdk.set_tag("service", service_name)
        sentry_sdk.set_tag("mongodb_per_guild_db", str(bool(settings.mongodb_per_guild_db)).lower())
    except Exception:
        pass

    _INITIALIZED = True
    logging.info("Error reporting enabled (%s, env=%s).", service_name, environment)


def set_guild_tag(guild_id: int | str | None) -> None:
    if not guild_id:
        return
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except Exception:
        return
    try:
        sentry_sdk.set_tag("guild_id", str(guild_id))
    except Exception:
        return


def capture_exception(exc: BaseException, *, guild_id: int | str | None = None) -> None:
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except Exception:
        return

    if guild_id:
        try:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("guild_id", str(guild_id))
                sentry_sdk.capture_exception(exc)
            return
        except Exception:
            return

    try:
        sentry_sdk.capture_exception(exc)
    except Exception:
        return
