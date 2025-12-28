from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Iterable

from . import constants


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_application_id: int
    discord_client_id: int | None
    discord_public_key: str | None
    interactions_endpoint_url: str | None
    discord_test_channel_id: int | None
    test_mode: bool
    role_broskie_id: int
    role_super_league_coach_id: int
    role_coach_premium_id: int
    role_coach_premium_plus_id: int
    channel_roster_portal_id: int
    channel_staff_submissions_id: int
    channel_admin_portal_id: int
    staff_role_ids: set[int]
    mongodb_uri: str | None
    mongodb_db_name: str | None
    mongodb_collection: str | None
    banlist_sheet_id: str | None
    banlist_range: str | None
    banlist_cache_ttl_seconds: int
    google_sheets_credentials_json: str | None


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
    missing: list[str] = []
    invalid: list[str] = []

    discord_token = _required_str(constants.DISCORD_TOKEN_ENV, missing)
    discord_application_id = _required_int(constants.DISCORD_APPLICATION_ID_ENV, missing, invalid)

    role_broskie_id = _required_int(constants.ROLE_BROSKIE_ID_ENV, missing, invalid)
    role_super_league_coach_id = _required_int(
        constants.ROLE_SUPER_LEAGUE_COACH_ID_ENV, missing, invalid
    )
    role_coach_premium_id = _required_int(constants.ROLE_COACH_PREMIUM_ID_ENV, missing, invalid)
    role_coach_premium_plus_id = _required_int(
        constants.ROLE_COACH_PREMIUM_PLUS_ID_ENV, missing, invalid
    )

    channel_roster_portal_id = _required_int(
        constants.CHANNEL_ROSTER_PORTAL_ID_ENV, missing, invalid
    )
    channel_staff_submissions_id = _required_int(
        constants.CHANNEL_STAFF_SUBMISSIONS_ID_ENV, missing, invalid
    )
    channel_admin_portal_id = _required_int(
        constants.CHANNEL_ADMIN_PORTAL_ID_ENV, missing, invalid
    )

    if missing or invalid:
        details = []
        if missing:
            details.append(f"Missing required config: {_format_list(missing)}")
        if invalid:
            details.append(f"Invalid integer config: {_format_list(invalid)}")
        raise RuntimeError("; ".join(details))

    discord_test_channel_id = _optional_int(constants.DISCORD_TEST_CHANNEL_ENV)
    test_mode = _optional_bool(constants.TEST_MODE_ENV, default=True)

    if test_mode and discord_test_channel_id is None:
        raise RuntimeError(
            "DISCORD_TEST_CHANNEL is required when TEST_MODE is enabled."
        )

    return Settings(
        discord_token=discord_token,
        discord_application_id=discord_application_id,
        discord_client_id=_optional_int(constants.DISCORD_CLIENT_ID_ENV),
        discord_public_key=_optional_str(constants.DISCORD_PUBLIC_KEY_ENV),
        interactions_endpoint_url=_optional_str(constants.DISCORD_INTERACTIONS_ENDPOINT_URL_ENV),
        discord_test_channel_id=discord_test_channel_id,
        test_mode=test_mode,
        role_broskie_id=role_broskie_id,
        role_super_league_coach_id=role_super_league_coach_id,
        role_coach_premium_id=role_coach_premium_id,
        role_coach_premium_plus_id=role_coach_premium_plus_id,
        channel_roster_portal_id=channel_roster_portal_id,
        channel_staff_submissions_id=channel_staff_submissions_id,
        channel_admin_portal_id=channel_admin_portal_id,
        staff_role_ids=_optional_int_set(constants.STAFF_ROLE_IDS_ENV),
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
    )
