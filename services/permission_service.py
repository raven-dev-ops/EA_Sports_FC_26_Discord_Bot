from __future__ import annotations

from collections.abc import Iterable

from config import Settings
from services import entitlements_service
from utils.role_routing import resolve_role_id


def resolve_roster_cap(
    member_role_ids: Iterable[int],
    *,
    team_coach_role_id: int | None,
    club_manager_role_id: int | None,
    league_staff_role_id: int | None,
    league_owner_role_id: int | None,
) -> int | None:
    role_set = set(member_role_ids)

    if league_owner_role_id in role_set:
        return 22
    if league_staff_role_id in role_set:
        return 22
    if club_manager_role_id in role_set:
        return 22
    if team_coach_role_id in role_set:
        return 16

    return None


def resolve_roster_cap_from_settings(
    member_role_ids: Iterable[int], settings: Settings
) -> int | None:
    return resolve_roster_cap(
        member_role_ids,
        team_coach_role_id=settings.role_team_coach_id,
        club_manager_role_id=settings.role_club_manager_id,
        league_staff_role_id=settings.role_league_staff_id,
        league_owner_role_id=settings.role_league_owner_id,
    )


def resolve_roster_cap_for_guild(
    member_role_ids: Iterable[int],
    *,
    settings: Settings,
    guild_id: int | None,
) -> int | None:
    premium_tiers_enabled = True
    if guild_id is not None:
        premium_tiers_enabled = entitlements_service.is_feature_enabled(
            settings, guild_id=guild_id, feature_key=entitlements_service.FEATURE_PREMIUM_COACH_TIERS
        )
    return resolve_roster_cap(
        member_role_ids,
        team_coach_role_id=resolve_role_id(settings, guild_id=guild_id, field="role_team_coach_id"),
        club_manager_role_id=(
            resolve_role_id(settings, guild_id=guild_id, field="role_club_manager_id")
            if premium_tiers_enabled
            else None
        ),
        league_staff_role_id=resolve_role_id(settings, guild_id=guild_id, field="role_league_staff_id"),
        league_owner_role_id=resolve_role_id(settings, guild_id=guild_id, field="role_league_owner_id"),
    )
