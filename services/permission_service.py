from __future__ import annotations

from collections.abc import Iterable

from config import Settings
from utils.role_routing import resolve_role_id


def resolve_roster_cap(
    member_role_ids: Iterable[int],
    *,
    coach_role_id: int | None,
    premium_role_id: int | None,
    premium_plus_role_id: int | None,
) -> int | None:
    role_set = set(member_role_ids)

    if premium_plus_role_id in role_set:
        return 25
    if premium_role_id in role_set:
        return 22
    if coach_role_id in role_set:
        return 16

    return None


def resolve_roster_cap_from_settings(
    member_role_ids: Iterable[int], settings: Settings
) -> int | None:
    return resolve_roster_cap(
        member_role_ids,
        coach_role_id=settings.role_coach_id,
        premium_role_id=settings.role_coach_premium_id,
        premium_plus_role_id=settings.role_coach_premium_plus_id,
    )


def resolve_roster_cap_for_guild(
    member_role_ids: Iterable[int],
    *,
    settings: Settings,
    guild_id: int | None,
) -> int | None:
    return resolve_roster_cap(
        member_role_ids,
        coach_role_id=resolve_role_id(settings, guild_id=guild_id, field="role_coach_id"),
        premium_role_id=resolve_role_id(
            settings, guild_id=guild_id, field="role_coach_premium_id"
        ),
        premium_plus_role_id=resolve_role_id(
            settings, guild_id=guild_id, field="role_coach_premium_plus_id"
        ),
    )
