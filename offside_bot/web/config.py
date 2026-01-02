from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
DEFAULT_STATE_TTL_SECONDS = 600
DEFAULT_PUBLIC_REPO_URL = "https://github.com/raven-dev-ops/EA_Sports_FC_26_Discord_Bot"


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _clean_env(value: str | None) -> str:
    return (value or "").strip()


@dataclass(frozen=True)
class DashboardConfig:
    session_ttl_seconds: int
    session_idle_timeout_seconds: int
    session_touch_interval_seconds: int
    state_ttl_seconds: int
    guild_metadata_ttl_seconds: int
    stats_cache_ttl_seconds: int
    request_timeout_seconds: float
    max_request_bytes: int
    rate_limit_window_seconds: int
    rate_limit_public_max: int
    rate_limit_webhook_max: int
    rate_limit_default_max: int
    guild_data_delete_grace_hours: int
    public_repo_url: str


def load_dashboard_config() -> DashboardConfig:
    repo = _clean_env(os.environ.get("PUBLIC_REPO_URL")) or _clean_env(os.environ.get("GITHUB_REPO_URL"))
    if not repo:
        repo = DEFAULT_PUBLIC_REPO_URL
    repo = repo.rstrip("/")
    return DashboardConfig(
        session_ttl_seconds=_int_env("DASHBOARD_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS),
        session_idle_timeout_seconds=_int_env("DASHBOARD_SESSION_IDLE_TIMEOUT_SECONDS", 0),
        session_touch_interval_seconds=_int_env("DASHBOARD_SESSION_TOUCH_INTERVAL_SECONDS", 300),
        state_ttl_seconds=_int_env("DASHBOARD_STATE_TTL_SECONDS", DEFAULT_STATE_TTL_SECONDS),
        guild_metadata_ttl_seconds=_int_env("DASHBOARD_GUILD_METADATA_TTL_SECONDS", 60),
        stats_cache_ttl_seconds=_int_env("DASHBOARD_STATS_CACHE_TTL_SECONDS", 1800),
        request_timeout_seconds=_float_env("DASHBOARD_REQUEST_TIMEOUT_SECONDS", 15.0),
        max_request_bytes=_int_env("DASHBOARD_MAX_REQUEST_BYTES", 1048576),
        rate_limit_window_seconds=_int_env("DASHBOARD_RATE_LIMIT_WINDOW_SECONDS", 60),
        rate_limit_public_max=_int_env("DASHBOARD_RATE_LIMIT_PUBLIC_MAX", 20),
        rate_limit_webhook_max=_int_env("DASHBOARD_RATE_LIMIT_WEBHOOK_MAX", 120),
        rate_limit_default_max=_int_env("DASHBOARD_RATE_LIMIT_DEFAULT_MAX", 300),
        guild_data_delete_grace_hours=_int_env("GUILD_DATA_DELETE_GRACE_HOURS", 24),
        public_repo_url=repo,
    )
