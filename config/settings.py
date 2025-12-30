from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable

from . import constants


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_application_id: int
    discord_client_id: int | None
    discord_public_key: str | None
    interactions_endpoint_url: str | None
    test_mode: bool
    role_broskie_id: int | None
    role_coach_id: int | None
    role_coach_premium_id: int | None
    role_coach_premium_plus_id: int | None
    channel_staff_portal_id: int | None
    channel_club_portal_id: int | None
    channel_manager_portal_id: int | None
    channel_coach_portal_id: int | None
    channel_recruit_portal_id: int | None
    channel_staff_monitor_id: int | None
    channel_roster_listing_id: int | None
    channel_recruit_listing_id: int | None
    channel_club_listing_id: int | None
    channel_premium_coaches_id: int | None
    staff_role_ids: set[int]
    mongodb_uri: str | None
    mongodb_db_name: str | None
    mongodb_collection: str | None
    banlist_sheet_id: str | None
    banlist_range: str | None
    banlist_cache_ttl_seconds: int
    google_sheets_credentials_json: str | None
    use_sharding: bool = False
    shard_count: int | None = None
    feature_flags: set[str] = field(default_factory=set)
    fc25_stats_cache_ttl_seconds: int = 900
    fc25_stats_http_timeout_seconds: int = 7
    fc25_stats_max_concurrency: int = 3
    fc25_stats_rate_limit_per_guild: int = 20
    fc25_default_platform: str = "common-gen5"


def _required_str(name: str, missing: list[str]) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        missing.append(name)
    return value


def _required_int(name: str, missing: list[str], invalid: list[str]) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        missing.append(name)
        return 0
    try:
        return int(raw)
    except ValueError:
        invalid.append(name)
        return 0


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer.") from None


def _optional_int_set(name: str) -> set[int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return set()
    values = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            values.append(int(value))
        except ValueError:
            raise RuntimeError(f"{name} must be a comma-separated list of integers.") from None
    return set(values)


def _optional_int_default(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer.") from None


def _optional_str_set(name: str) -> set[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _optional_str(name: str) -> str | None:
    raw = os.getenv(name, "").strip()
    return raw or None


def _optional_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean (true/false).")


def _format_list(values: Iterable[str]) -> str:
    return ", ".join(sorted(values))


def load_settings() -> Settings:
    """
    Load and validate environment configuration.
    Raises RuntimeError with a consolidated message when required values are missing/invalid.
    """
    missing: list[str] = []
    invalid: list[str] = []

    discord_token = _required_str(constants.DISCORD_TOKEN_ENV, missing)
    discord_application_id = _required_int(constants.DISCORD_APPLICATION_ID_ENV, missing, invalid)

    if missing or invalid:
        details = []
        if missing:
            details.append(f"Missing required config: {_format_list(missing)}")
        if invalid:
            details.append(f"Invalid integer config: {_format_list(invalid)}")
        raise RuntimeError("; ".join(details))

    test_mode = _optional_bool(constants.TEST_MODE_ENV, default=True)
    use_sharding = _optional_bool(constants.USE_SHARDING_ENV, default=False)
    shard_count = _optional_int(constants.SHARD_COUNT_ENV)
    feature_flags = _optional_str_set(constants.FEATURE_FLAGS_ENV)
    staff_role_ids = _optional_int_set(constants.STAFF_ROLE_IDS_ENV)

    channel_staff_portal_id = _optional_int(constants.CHANNEL_STAFF_PORTAL_ID_ENV)
    channel_club_portal_id = _optional_int(constants.CHANNEL_CLUB_PORTAL_ID_ENV)
    channel_manager_portal_id = _optional_int(constants.CHANNEL_MANAGER_PORTAL_ID_ENV)
    channel_coach_portal_id = _optional_int(constants.CHANNEL_COACH_PORTAL_ID_ENV)
    channel_recruit_portal_id = _optional_int(constants.CHANNEL_RECRUIT_PORTAL_ID_ENV)

    channel_staff_monitor_id = _optional_int(constants.CHANNEL_STAFF_MONITOR_ID_ENV)

    channel_roster_listing_id = _optional_int(constants.CHANNEL_ROSTER_LISTING_ID_ENV)
    if channel_roster_listing_id is None:
        channel_roster_listing_id = _optional_int(constants.CHANNEL_ROSTER_PORTAL_ID_ENV)
    channel_recruit_listing_id = _optional_int(constants.CHANNEL_RECRUIT_LISTING_ID_ENV)
    channel_club_listing_id = _optional_int(constants.CHANNEL_CLUB_LISTING_ID_ENV)
    channel_premium_coaches_id = _optional_int(constants.CHANNEL_PREMIUM_COACHES_ID_ENV)

    fc25_stats_cache_ttl_seconds = _optional_int_default(
        constants.FC25_STATS_CACHE_TTL_SECONDS_ENV, default=900
    )
    fc25_stats_http_timeout_seconds = _optional_int_default(
        constants.FC25_STATS_HTTP_TIMEOUT_SECONDS_ENV, default=7
    )
    fc25_stats_max_concurrency = _optional_int_default(
        constants.FC25_STATS_MAX_CONCURRENCY_ENV, default=3
    )
    fc25_stats_rate_limit_per_guild = _optional_int_default(
        constants.FC25_STATS_RATE_LIMIT_PER_GUILD_ENV, default=20
    )
    fc25_default_platform = _optional_str(constants.FC25_DEFAULT_PLATFORM_ENV) or "common-gen5"

    if fc25_stats_cache_ttl_seconds <= 0:
        raise RuntimeError("FC25_STATS_CACHE_TTL_SECONDS must be > 0.")
    if fc25_stats_http_timeout_seconds <= 0:
        raise RuntimeError("FC25_STATS_HTTP_TIMEOUT_SECONDS must be > 0.")
    if fc25_stats_max_concurrency <= 0:
        raise RuntimeError("FC25_STATS_MAX_CONCURRENCY must be > 0.")
    if fc25_stats_rate_limit_per_guild <= 0:
        raise RuntimeError("FC25_STATS_RATE_LIMIT_PER_GUILD must be > 0.")

    role_broskie_id = _optional_int(constants.ROLE_BROSKIE_ID_ENV)
    role_coach_id = _optional_int(constants.ROLE_COACH_ID_ENV) or _optional_int(
        constants.ROLE_SUPER_LEAGUE_COACH_ID_ENV
    )
    role_coach_premium_id = _optional_int(constants.ROLE_COACH_PREMIUM_ID_ENV)
    role_coach_premium_plus_id = _optional_int(constants.ROLE_COACH_PREMIUM_PLUS_ID_ENV)

    return Settings(
        discord_token=discord_token,
        discord_application_id=discord_application_id,
        discord_client_id=_optional_int(constants.DISCORD_CLIENT_ID_ENV),
        discord_public_key=_optional_str(constants.DISCORD_PUBLIC_KEY_ENV),
        interactions_endpoint_url=_optional_str(constants.DISCORD_INTERACTIONS_ENDPOINT_URL_ENV),
        test_mode=test_mode,
        role_broskie_id=role_broskie_id,
        role_coach_id=role_coach_id,
        role_coach_premium_id=role_coach_premium_id,
        role_coach_premium_plus_id=role_coach_premium_plus_id,
        channel_staff_portal_id=channel_staff_portal_id,
        channel_club_portal_id=channel_club_portal_id,
        channel_manager_portal_id=channel_manager_portal_id,
        channel_coach_portal_id=channel_coach_portal_id,
        channel_recruit_portal_id=channel_recruit_portal_id,
        channel_staff_monitor_id=channel_staff_monitor_id,
        channel_roster_listing_id=channel_roster_listing_id,
        channel_recruit_listing_id=channel_recruit_listing_id,
        channel_club_listing_id=channel_club_listing_id,
        channel_premium_coaches_id=channel_premium_coaches_id,
        staff_role_ids=staff_role_ids,
        mongodb_uri=_optional_str(constants.MONGODB_URI_ENV),
        mongodb_db_name=_optional_str(constants.MONGODB_DB_NAME_ENV),
        mongodb_collection=_optional_str(constants.MONGODB_COLLECTION_ENV),
        banlist_sheet_id=_optional_str(constants.BANLIST_SHEET_ID_ENV),
        banlist_range=_optional_str(constants.BANLIST_RANGE_ENV),
        banlist_cache_ttl_seconds=_optional_int_default(
            constants.BANLIST_CACHE_TTL_SECONDS_ENV, default=300
        ),
        google_sheets_credentials_json=_optional_str(
            constants.GOOGLE_SHEETS_CREDENTIALS_JSON_ENV
        ),
        use_sharding=use_sharding,
        shard_count=shard_count,
        feature_flags=feature_flags,
        fc25_stats_cache_ttl_seconds=fc25_stats_cache_ttl_seconds,
        fc25_stats_http_timeout_seconds=fc25_stats_http_timeout_seconds,
        fc25_stats_max_concurrency=fc25_stats_max_concurrency,
        fc25_stats_rate_limit_per_guild=fc25_stats_rate_limit_per_guild,
        fc25_default_platform=fc25_default_platform,
    )


def summarize_settings(settings: Settings) -> dict[str, object]:
    """
    Produce a non-secret snapshot of configuration for startup logging.
    """
    return {
        "application_id": settings.discord_application_id,
        "client_id_present": bool(settings.discord_client_id),
        "test_mode": settings.test_mode,
        "use_sharding": settings.use_sharding,
        "shard_count": settings.shard_count,
        "feature_flags": sorted(settings.feature_flags),
        "fc25": {
            "cache_ttl_seconds": settings.fc25_stats_cache_ttl_seconds,
            "http_timeout_seconds": settings.fc25_stats_http_timeout_seconds,
            "max_concurrency": settings.fc25_stats_max_concurrency,
            "rate_limit_per_guild": settings.fc25_stats_rate_limit_per_guild,
            "default_platform": settings.fc25_default_platform,
        },
        "channels": {
            "staff_portal": settings.channel_staff_portal_id,
            "club_portal": settings.channel_club_portal_id,
            "manager_portal": settings.channel_manager_portal_id,
            "coach_portal": settings.channel_coach_portal_id,
            "recruit_portal": settings.channel_recruit_portal_id,
            "staff_monitor": settings.channel_staff_monitor_id,
            "roster_listing": settings.channel_roster_listing_id,
            "recruit_listing": settings.channel_recruit_listing_id,
            "club_listing": settings.channel_club_listing_id,
            "premium_coaches": settings.channel_premium_coaches_id,
        },
        "roles": {
            "broskie": settings.role_broskie_id,
            "coach": settings.role_coach_id,
            "coach_premium": settings.role_coach_premium_id,
            "coach_premium_plus": settings.role_coach_premium_plus_id,
            "staff_roles_defined": bool(settings.staff_role_ids),
        },
        "banlist_enabled": bool(settings.banlist_sheet_id),
        "mongodb_uri_present": bool(settings.mongodb_uri),
        "mongodb_db_name": settings.mongodb_db_name,
        "mongodb_collection": settings.mongodb_collection,
    }
