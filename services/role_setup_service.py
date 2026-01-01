from __future__ import annotations

from typing import Any

import discord

COACH_ROLE_NAME = "Coach"
COACH_PREMIUM_ROLE_NAME = "Coach Premium"
COACH_PREMIUM_PLUS_ROLE_NAME = "Coach Premium+"

OWNER_ROLE_NAME = "Owner"
MANAGER_ROLE_NAME = "Manager"
FREE_PLAYER_ROLE_NAME = "Free Player"
PREMIUM_PLAYER_ROLE_NAME = "Premium Player"

STAFF_ROLE_IDS_KEY = "staff_role_ids"

LEGACY_COACH_ROLE_NAMES = ("Super League Coach",)
LEGACY_COACH_PREMIUM_PLUS_ROLE_NAMES = ("Coach Premium Plus",)


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

    coach_role = await _ensure_role(
        guild,
        name=COACH_ROLE_NAME,
        aliases=LEGACY_COACH_ROLE_NAMES,
        existing_role_id=_parse_int(config.get("role_coach_id")),
        actions=actions,
    )
    premium_role = await _ensure_role(
        guild,
        name=COACH_PREMIUM_ROLE_NAME,
        aliases=(),
        existing_role_id=_parse_int(config.get("role_coach_premium_id")),
        actions=actions,
    )
    premium_plus_role = await _ensure_role(
        guild,
        name=COACH_PREMIUM_PLUS_ROLE_NAME,
        aliases=LEGACY_COACH_PREMIUM_PLUS_ROLE_NAMES,
        existing_role_id=_parse_int(config.get("role_coach_premium_plus_id")),
        actions=actions,
    )

    owner_role = await _ensure_role(
        guild,
        name=OWNER_ROLE_NAME,
        aliases=(),
        existing_role_id=_parse_int(config.get("role_owner_id")),
        actions=actions,
    )
    manager_role = await _ensure_role(
        guild,
        name=MANAGER_ROLE_NAME,
        aliases=(),
        existing_role_id=_parse_int(config.get("role_manager_id")),
        actions=actions,
    )
    free_player_role = await _ensure_role(
        guild,
        name=FREE_PLAYER_ROLE_NAME,
        aliases=(),
        existing_role_id=_parse_int(config.get("role_free_player_id")),
        actions=actions,
    )
    premium_player_role = await _ensure_role(
        guild,
        name=PREMIUM_PLAYER_ROLE_NAME,
        aliases=(),
        existing_role_id=_parse_int(config.get("role_premium_player_id")),
        actions=actions,
    )

    config["role_coach_id"] = coach_role.id
    config["role_coach_premium_id"] = premium_role.id
    config["role_coach_premium_plus_id"] = premium_plus_role.id
    config["role_owner_id"] = owner_role.id
    config["role_manager_id"] = manager_role.id
    config["role_free_player_id"] = free_player_role.id
    config["role_premium_player_id"] = premium_player_role.id

    staff_role_ids = _parse_int_set(config.get(STAFF_ROLE_IDS_KEY))
    updated_staff_role_ids = set(staff_role_ids)
    updated_staff_role_ids.update({owner_role.id, manager_role.id})
    if updated_staff_role_ids != staff_role_ids:
        config[STAFF_ROLE_IDS_KEY] = sorted(updated_staff_role_ids)
        actions.append("Updated staff role IDs to include Owner/Manager roles.")

    return config


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
