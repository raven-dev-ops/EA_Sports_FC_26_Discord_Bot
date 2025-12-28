from __future__ import annotations

from collections.abc import Iterable

from config import Settings


def resolve_roster_cap(
    member_role_ids: Iterable[int],
    *,
    super_league_role_id: int,
    premium_role_id: int,
    premium_plus_role_id: int,
) -> int | None:
    role_set = set(member_role_ids)

    if super_league_role_id in role_set:
        return 16
    if premium_plus_role_id in role_set:
        return 25
    if premium_role_id in role_set:
        return 22

    return None


def resolve_roster_cap_from_settings(
    member_role_ids: Iterable[int], settings: Settings
) -> int | None:
    return resolve_roster_cap(
        member_role_ids,
        super_league_role_id=settings.role_super_league_coach_id,
        premium_role_id=settings.role_coach_premium_id,
        premium_plus_role_id=settings.role_coach_premium_plus_id,
    )
