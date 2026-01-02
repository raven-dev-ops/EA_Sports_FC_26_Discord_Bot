from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1

STAFF_ROLE_IDS_KEY = "staff_role_ids"
FC25_STATS_ENABLED_KEY = "fc25_stats_enabled"
PREMIUM_COACHES_PIN_ENABLED_KEY = "premium_coaches_pin_enabled"

GUILD_COACH_ROLE_FIELDS: list[tuple[str, str]] = [
    ("role_coach_id", "Coach role"),
    ("role_coach_premium_id", "Coach Premium role"),
    ("role_coach_premium_plus_id", "Coach Premium+ role"),
]

GUILD_CHANNEL_FIELDS: list[tuple[str, str]] = [
    ("channel_staff_portal_id", "Staff portal channel"),
    ("channel_club_portal_id", "Club portal channel"),
    ("channel_manager_portal_id", "Club Managers portal channel"),
    ("channel_coach_portal_id", "Coach portal channel"),
    ("channel_recruit_portal_id", "Recruit portal channel"),
    ("channel_staff_monitor_id", "Staff monitor channel"),
    ("channel_roster_listing_id", "Roster listing channel"),
    ("channel_recruit_listing_id", "Recruit listing channel"),
    ("channel_club_listing_id", "Club listing channel"),
    ("channel_premium_coaches_id", "Pro coaches channel"),
]

INT_FIELDS: set[str] = {k for k, _label in (GUILD_COACH_ROLE_FIELDS + GUILD_CHANNEL_FIELDS)}
INT_LIST_FIELDS: set[str] = {STAFF_ROLE_IDS_KEY}
BOOL_FIELDS: set[str] = {PREMIUM_COACHES_PIN_ENABLED_KEY}
TRI_BOOL_FIELDS: set[str] = {FC25_STATS_ENABLED_KEY}

USER_EDITABLE_FIELDS: set[str] = INT_FIELDS | INT_LIST_FIELDS | BOOL_FIELDS | TRI_BOOL_FIELDS


def parse_optional_int(raw: str) -> int | None:
    value = raw.strip()
    if value.lower() in {"", "default"}:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("Expected an integer.") from exc


def parse_optional_bool(raw: str) -> bool | None:
    value = raw.strip().lower()
    if value in {"", "default"}:
        return None
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError("Expected true/false.")


def parse_csv_int_list(raw: str) -> list[int] | None:
    value = raw.strip()
    if value.lower() in {"", "default"}:
        return None
    out: list[int] = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError as exc:
            raise ValueError("Expected a comma-separated list of integers.") from exc
    return out


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
