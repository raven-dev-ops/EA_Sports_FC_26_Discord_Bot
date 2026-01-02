from __future__ import annotations

from typing import Any

import discord

TEAM_COACH_ROLE_NAME = "Team Coach"
CLUB_MANAGER_ROLE_NAME = "Club Manager"
LEAGUE_STAFF_ROLE_NAME = "League Staff"
LEAGUE_OWNER_ROLE_NAME = "League Owner"
FREE_AGENT_ROLE_NAME = "Free Agent"
PRO_PLAYER_ROLE_NAME = "Pro Player"
RETIRED_ROLE_NAME = "Retired"

STAFF_ROLE_IDS_KEY = "staff_role_ids"

LEGACY_TEAM_COACH_ROLE_NAMES = ("Coach", "Super League Coach")
LEGACY_CLUB_MANAGER_ROLE_NAMES = ("Manager", "Coach Premium", "Coach Premium+", "Coach Premium Plus")
LEGACY_FREE_AGENT_ROLE_NAMES = ("Recruit", "Free Player")
LEGACY_PRO_PLAYER_ROLE_NAMES = ("Premium Player",)


async def ensure_offside_roles(
    guild: discord.Guild,
    *,
    existing_config: dict[str, Any] | None,
    actions: list[str],
) -> dict[str, Any]:
    """
    Ensure Offside roles exist and return an updated guild config payload.
    """
    config: dict[str, Any] = dict(existing_config or {})

    me = guild.me
    if me is None:
        actions.append("Role setup skipped (bot member unavailable).")
        return config
    if not me.guild_permissions.manage_roles:
        actions.append("Role setup skipped (missing Manage Roles permission).")
        return config

    team_coach_role = await _ensure_role(
        guild,
        name=TEAM_COACH_ROLE_NAME,
        aliases=LEGACY_TEAM_COACH_ROLE_NAMES,
        existing_role_id=_parse_int(config.get("role_team_coach_id"))
        or _parse_int(config.get("role_coach_id")),
        actions=actions,
    )
    club_manager_role = await _ensure_role(
        guild,
        name=CLUB_MANAGER_ROLE_NAME,
        aliases=LEGACY_CLUB_MANAGER_ROLE_NAMES,
        existing_role_id=_parse_int(config.get("role_club_manager_id"))
        or _parse_int(config.get("role_manager_id"))
        or _parse_int(config.get("role_coach_premium_plus_id"))
        or _parse_int(config.get("role_coach_premium_id")),
        actions=actions,
    )
    league_staff_role = await _ensure_role(
        guild,
        name=LEAGUE_STAFF_ROLE_NAME,
        aliases=("Staff",),
        existing_role_id=_parse_int(config.get("role_league_staff_id")),
        actions=actions,
    )
    league_owner_role = await _ensure_role(
        guild,
        name=LEAGUE_OWNER_ROLE_NAME,
        aliases=("Owner",),
        existing_role_id=_parse_int(config.get("role_league_owner_id"))
        or _parse_int(config.get("role_owner_id")),
        actions=actions,
    )
    free_agent_role = await _ensure_role(
        guild,
        name=FREE_AGENT_ROLE_NAME,
        aliases=LEGACY_FREE_AGENT_ROLE_NAMES,
        existing_role_id=_parse_int(config.get("role_free_agent_id"))
        or _parse_int(config.get("role_recruit_id"))
        or _parse_int(config.get("role_free_player_id")),
        actions=actions,
    )
    pro_player_role = await _ensure_role(
        guild,
        name=PRO_PLAYER_ROLE_NAME,
        aliases=LEGACY_PRO_PLAYER_ROLE_NAMES,
        existing_role_id=_parse_int(config.get("role_pro_player_id"))
        or _parse_int(config.get("role_premium_player_id")),
        actions=actions,
    )
    retired_role = await _ensure_role(
        guild,
        name=RETIRED_ROLE_NAME,
        aliases=(),
        existing_role_id=_parse_int(config.get("role_retired_id")),
        actions=actions,
    )

    config["role_team_coach_id"] = team_coach_role.id
    config["role_club_manager_id"] = club_manager_role.id
    config["role_league_staff_id"] = league_staff_role.id
    config["role_league_owner_id"] = league_owner_role.id
    config["role_free_agent_id"] = free_agent_role.id
    config["role_pro_player_id"] = pro_player_role.id
    config["role_retired_id"] = retired_role.id

    staff_role_ids = _parse_int_set(config.get(STAFF_ROLE_IDS_KEY))
    updated_staff_role_ids = set(staff_role_ids)
    updated_staff_role_ids.update(
        {
            team_coach_role.id,
            club_manager_role.id,
            league_staff_role.id,
            league_owner_role.id,
        }
    )
    if updated_staff_role_ids != staff_role_ids:
        config[STAFF_ROLE_IDS_KEY] = sorted(updated_staff_role_ids)
        actions.append("Updated staff role IDs to include Owner/Manager roles.")

    await _maybe_assign_league_owner_role(
        guild, owner_role=league_owner_role, actions=actions
    )

    return config


async def _maybe_assign_league_owner_role(
    guild: discord.Guild,
    *,
    owner_role: discord.Role,
    actions: list[str],
) -> None:
    owner_id = getattr(guild, "owner_id", None)
    if not isinstance(owner_id, int) or not owner_id:
        return

    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        actions.append("Could not assign League Owner role (missing Manage Roles permission).")
        return

    try:
        manageable = owner_role < me.top_role
    except TypeError:
        manageable = owner_role.position < me.top_role.position

    if not manageable and not me.guild_permissions.administrator:
        actions.append(
            "Could not assign League Owner role (role is above the bot). "
            "Move the bot role above it to enable auto-assignment."
        )
        return

    member = guild.get_member(owner_id)
    if member is None:
        try:
            member = await guild.fetch_member(owner_id)
        except discord.DiscordException:
            return

    if owner_role in getattr(member, "roles", []):
        return

    try:
        await member.add_roles(owner_role, reason="Offside setup: guild owner")
    except discord.DiscordException:
        actions.append("Could not assign League Owner role to the server owner (missing permissions).")
        return

    actions.append("Assigned League Owner role to the server owner.")


async def _ensure_role(
    guild: discord.Guild,
    *,
    name: str,
    aliases: tuple[str, ...],
    existing_role_id: int | None,
    actions: list[str],
) -> discord.Role:
    role, should_rename = _resolve_role(
        guild,
        desired_name=name,
        aliases=aliases,
        role_id=existing_role_id,
    )
    if role is not None:
        if should_rename:
            await _maybe_rename_role(role, desired_name=name, actions=actions)
        return role

    role = await guild.create_role(name=name, reason="Offside setup")
    actions.append(f"Created role: {name}")
    return role


def _resolve_role(
    guild: discord.Guild,
    *,
    desired_name: str,
    aliases: tuple[str, ...],
    role_id: int | None,
) -> tuple[discord.Role | None, bool]:
    wanted = desired_name.casefold()
    alias_names = {alias.casefold() for alias in aliases}

    if role_id:
        role = guild.get_role(role_id)
        if role is not None and not role.is_default():
            return role, role.name.casefold() in alias_names and role.name.casefold() != wanted

    for role in guild.roles:
        if role.is_default():
            continue
        if role.name.casefold() == wanted:
            return role, False

    for role in guild.roles:
        if role.is_default():
            continue
        if role.name.casefold() in alias_names:
            return role, True
    return None, False


async def _maybe_rename_role(
    role: discord.Role,
    *,
    desired_name: str,
    actions: list[str],
) -> None:
    before = role.name
    if before.casefold() == desired_name.casefold():
        return
    try:
        await role.edit(name=desired_name, reason="Offside setup: normalize role name")
        actions.append(f"Renamed role: {before} -> {desired_name}")
    except discord.DiscordException:
        actions.append(f"Could not rename role {before} to {desired_name} (missing permissions).")


def _parse_int(value: Any) -> int | None:
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


def _parse_int_set(value: Any) -> set[int]:
    if value is None:
        return set()
    if isinstance(value, bool):
        return set()
    if isinstance(value, int):
        return {value}
    out: set[int] = set()
    if isinstance(value, str):
        for part in value.split(","):
            token = part.strip()
            if not token:
                continue
            try:
                parsed = int(token)
            except ValueError:
                continue
            if parsed and not isinstance(parsed, bool):
                out.add(parsed)
        return out
    if isinstance(value, (list, tuple, set)):
        for item in value:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                out.add(item)
                continue
            if isinstance(item, str):
                token = item.strip()
                if not token:
                    continue
                try:
                    out.add(int(token))
                except ValueError:
                    continue
        return out
    return set()
