from __future__ import annotations

from typing import Any

import discord

from config import Settings

DASHBOARD_CATEGORY_NAME = "--OFFSIDE DASHBOARD--"
REPORTS_CATEGORY_NAME = "--OFFSIDE REPORTS--"

STAFF_PORTAL_CHANNEL_NAME = "staff-portal"
MANAGER_PORTAL_CHANNEL_NAME = "club-managers-portal"
CLUB_PORTAL_CHANNEL_NAME = "club-portal"
COACH_PORTAL_CHANNEL_NAME = "coach-portal"
RECRUIT_PORTAL_CHANNEL_NAME = "recruit-portal"

STAFF_MONITOR_CHANNEL_NAME = "staff-monitor"
ROSTER_LISTING_CHANNEL_NAME = "roster-listing"
RECRUIT_LISTING_CHANNEL_NAME = "recruit-listing"
CLUB_LISTING_CHANNEL_NAME = "club-listing"
PREMIUM_COACHES_CHANNEL_NAME = "premium-coaches"

STAFF_MONITOR_MANAGED_KEY = "channel_staff_monitor_managed"


async def ensure_offside_channels(
    guild: discord.Guild,
    *,
    settings: Settings,
    existing_config: dict[str, Any] | None,
    test_mode: bool,
) -> tuple[dict[str, Any], list[str]]:
    """
    Ensure the Offside category/channel layout exists and return an updated guild config payload.
    """
    config: dict[str, Any] = dict(existing_config or {})
    actions: list[str] = []

    staff_roles = _resolve_staff_roles(guild, settings)
    coach_roles = _resolve_coach_roles(guild, config)
    bot_member = guild.me

    dashboard_category = await _ensure_category(guild, DASHBOARD_CATEGORY_NAME, actions=actions)
    reports_category = await _ensure_category(guild, REPORTS_CATEGORY_NAME, actions=actions)

    dashboard_channels: list[discord.TextChannel] = []
    dashboard_channels.append(
        await _ensure_text_channel(
            guild,
            category=dashboard_category,
            name=STAFF_PORTAL_CHANNEL_NAME,
            overwrites=_staff_only_overwrites(guild, staff_roles, bot_member),
            existing_channel_id=_parse_int(config.get("channel_staff_portal_id")),
            actions=actions,
        )
    )
    dashboard_channels.append(
        await _ensure_text_channel(
            guild,
            category=dashboard_category,
            name=MANAGER_PORTAL_CHANNEL_NAME,
            overwrites=_staff_only_overwrites(guild, staff_roles, bot_member),
            existing_channel_id=_parse_int(config.get("channel_manager_portal_id")),
            actions=actions,
        )
    )
    dashboard_channels.append(
        await _ensure_text_channel(
            guild,
            category=dashboard_category,
            name=CLUB_PORTAL_CHANNEL_NAME,
            overwrites=_public_readonly_overwrites(guild, staff_roles, bot_member),
            existing_channel_id=_parse_int(config.get("channel_club_portal_id")),
            actions=actions,
        )
    )
    dashboard_channels.append(
        await _ensure_text_channel(
            guild,
            category=dashboard_category,
            name=COACH_PORTAL_CHANNEL_NAME,
            overwrites=_coach_portal_overwrites(guild, staff_roles, coach_roles, bot_member),
            existing_channel_id=_parse_int(config.get("channel_coach_portal_id")),
            actions=actions,
        )
    )
    dashboard_channels.append(
        await _ensure_text_channel(
            guild,
            category=dashboard_category,
            name=RECRUIT_PORTAL_CHANNEL_NAME,
            overwrites=_public_readonly_overwrites(guild, staff_roles, bot_member),
            existing_channel_id=_parse_int(config.get("channel_recruit_portal_id")),
            actions=actions,
        )
    )

    config["channel_staff_portal_id"] = dashboard_channels[0].id
    config["channel_manager_portal_id"] = dashboard_channels[1].id
    config["channel_club_portal_id"] = dashboard_channels[2].id
    config["channel_coach_portal_id"] = dashboard_channels[3].id
    config["channel_recruit_portal_id"] = dashboard_channels[4].id

    reports_channels: list[discord.TextChannel] = []

    staff_monitor_id = _parse_int(config.get("channel_staff_monitor_id"))
    staff_monitor_managed = bool(config.get(STAFF_MONITOR_MANAGED_KEY))
    if not test_mode:
        cleanup_status = await _cleanup_staff_monitor(
            guild,
            staff_monitor_id=staff_monitor_id,
            staff_monitor_managed=staff_monitor_managed,
            reports_category=reports_category,
            actions=actions,
        )
        if cleanup_status == "cleared":
            config.pop("channel_staff_monitor_id", None)
            config.pop(STAFF_MONITOR_MANAGED_KEY, None)
        elif cleanup_status == "failed":
            actions.append(
                "Staff monitor cleanup failed (missing permissions). Please delete it manually."
            )
    else:
        staff_monitor_channel, created = await _ensure_text_channel_with_created(
            guild,
            category=reports_category,
            name=STAFF_MONITOR_CHANNEL_NAME,
            overwrites=_staff_only_overwrites(guild, staff_roles, bot_member),
            existing_channel_id=staff_monitor_id,
            actions=actions,
        )
        reports_channels.append(staff_monitor_channel)
        config["channel_staff_monitor_id"] = staff_monitor_channel.id
        if created:
            config[STAFF_MONITOR_MANAGED_KEY] = True
        else:
            config[STAFF_MONITOR_MANAGED_KEY] = bool(
                staff_monitor_managed and staff_monitor_id == staff_monitor_channel.id
            )

    roster_listing = await _ensure_text_channel(
        guild,
        category=reports_category,
        name=ROSTER_LISTING_CHANNEL_NAME,
        overwrites=_public_readonly_overwrites(guild, staff_roles, bot_member),
        existing_channel_id=_parse_int(config.get("channel_roster_listing_id")),
        actions=actions,
    )
    recruit_listing = await _ensure_text_channel(
        guild,
        category=reports_category,
        name=RECRUIT_LISTING_CHANNEL_NAME,
        overwrites=_public_readonly_overwrites(guild, staff_roles, bot_member),
        existing_channel_id=_parse_int(config.get("channel_recruit_listing_id")),
        actions=actions,
    )
    club_listing = await _ensure_text_channel(
        guild,
        category=reports_category,
        name=CLUB_LISTING_CHANNEL_NAME,
        overwrites=_public_readonly_overwrites(guild, staff_roles, bot_member),
        existing_channel_id=_parse_int(config.get("channel_club_listing_id")),
        actions=actions,
    )
    premium_coaches = await _ensure_text_channel(
        guild,
        category=reports_category,
        name=PREMIUM_COACHES_CHANNEL_NAME,
        overwrites=_public_readonly_overwrites(guild, staff_roles, bot_member),
        existing_channel_id=_parse_int(config.get("channel_premium_coaches_id")),
        actions=actions,
    )

    reports_channels.extend([roster_listing, recruit_listing, club_listing, premium_coaches])

    config["channel_roster_listing_id"] = roster_listing.id
    config["channel_recruit_listing_id"] = recruit_listing.id
    config["channel_club_listing_id"] = club_listing.id
    config["channel_premium_coaches_id"] = premium_coaches.id

    await _order_under_category(
        dashboard_category,
        dashboard_channels,
        actions=actions,
    )
    await _order_under_category(
        reports_category,
        reports_channels,
        actions=actions,
    )

    return config, actions


async def cleanup_staff_monitor_channel(
    guild: discord.Guild,
    *,
    existing_config: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    config: dict[str, Any] = dict(existing_config or {})
    actions: list[str] = []

    staff_monitor_id = _parse_int(config.get("channel_staff_monitor_id"))
    staff_monitor_managed = bool(config.get(STAFF_MONITOR_MANAGED_KEY))
    if not staff_monitor_id:
        return config, actions

    reports_category = discord.utils.get(guild.categories, name=REPORTS_CATEGORY_NAME)
    if reports_category is None:
        actions.append("Reports category not found; skipping staff monitor cleanup.")
        return config, actions

    cleanup_status = await _cleanup_staff_monitor(
        guild,
        staff_monitor_id=staff_monitor_id,
        staff_monitor_managed=staff_monitor_managed,
        reports_category=reports_category,
        actions=actions,
    )
    if cleanup_status == "cleared":
        config.pop("channel_staff_monitor_id", None)
        config.pop(STAFF_MONITOR_MANAGED_KEY, None)
    elif cleanup_status == "failed":
        actions.append(
            "Staff monitor cleanup failed (missing permissions). Please delete it manually."
        )

    return config, actions


async def _ensure_category(
    guild: discord.Guild, name: str, *, actions: list[str]
) -> discord.CategoryChannel:
    existing = discord.utils.get(guild.categories, name=name)
    if existing is not None:
        return existing
    category = await guild.create_category(name, reason="Offside setup")
    actions.append(f"Created category `{name}`.")
    return category


async def _ensure_text_channel(
    guild: discord.Guild,
    *,
    category: discord.CategoryChannel,
    name: str,
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite],
    existing_channel_id: int | None,
    actions: list[str],
) -> discord.TextChannel:
    channel, _created = await _ensure_text_channel_with_created(
        guild,
        category=category,
        name=name,
        overwrites=overwrites,
        existing_channel_id=existing_channel_id,
        actions=actions,
    )
    return channel


async def _ensure_text_channel_with_created(
    guild: discord.Guild,
    *,
    category: discord.CategoryChannel,
    name: str,
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite],
    existing_channel_id: int | None,
    actions: list[str],
) -> tuple[discord.TextChannel, bool]:
    channel: discord.TextChannel | None = None
    created = False

    if existing_channel_id:
        existing = guild.get_channel(existing_channel_id)
        if isinstance(existing, discord.TextChannel):
            channel = existing

    if channel is None:
        channel = discord.utils.get(category.text_channels, name=name)

    if channel is None:
        channel = discord.utils.get(guild.text_channels, name=name)

    if channel is None:
        channel = await guild.create_text_channel(
            name,
            category=category,
            overwrites=overwrites,
            reason="Offside setup",
        )
        actions.append(f"Created <#{channel.id}>.")
        return channel, True

    edits: dict[str, Any] = {}
    if channel.category_id != category.id:
        edits["category"] = category
    edits["overwrites"] = overwrites
    if edits:
        try:
            await channel.edit(**edits, reason="Offside setup")
        except discord.DiscordException:
            pass
    if not created:
        actions.append(f"Reused <#{channel.id}>.")
    return channel, created


async def _order_under_category(
    category: discord.CategoryChannel,
    channels: list[discord.TextChannel],
    *,
    actions: list[str],
) -> None:
    if not channels:
        return
    base_position = category.position
    for idx, channel in enumerate(channels, start=1):
        try:
            await channel.edit(position=base_position + idx, reason="Offside setup ordering")
        except discord.DiscordException:
            continue


def _resolve_staff_roles(guild: discord.Guild, settings: Settings) -> list[discord.Role]:
    roles: list[discord.Role] = []
    if settings.staff_role_ids:
        for role_id in sorted(settings.staff_role_ids):
            role = guild.get_role(role_id)
            if role is not None and not role.is_default():
                roles.append(role)
        return roles

    for role in guild.roles:
        if role.is_default():
            continue
        if role.permissions.administrator or role.permissions.manage_guild:
            roles.append(role)
    return roles


def _staff_only_overwrites(
    guild: discord.Guild,
    staff_roles: list[discord.Role],
    bot_member: discord.Member | None,
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False)
    }
    for role in staff_roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )
    if bot_member is not None:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            embed_links=True,
            attach_files=True,
        )
    return overwrites


def _public_readonly_overwrites(
    guild: discord.Guild,
    staff_roles: list[discord.Role],
    bot_member: discord.Member | None,
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
        )
    }
    for role in staff_roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            manage_messages=True,
        )
    if bot_member is not None:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            embed_links=True,
            attach_files=True,
        )
    return overwrites


def _resolve_coach_roles(guild: discord.Guild, config: dict[str, Any]) -> list[discord.Role]:
    resolved: dict[int, discord.Role] = {}

    for key in ("role_coach_id", "role_coach_premium_id", "role_coach_premium_plus_id"):
        role_id = _parse_int(config.get(key))
        if not role_id:
            continue
        role = guild.get_role(role_id)
        if role is not None and not role.is_default():
            resolved[role.id] = role

    if resolved:
        return list(resolved.values())

    for name in ("Coach", "Coach Premium", "Coach Premium+"):
        role = discord.utils.get(guild.roles, name=name)
        if role is not None and not role.is_default():
            resolved[role.id] = role

    return list(resolved.values())


def _coach_portal_overwrites(
    guild: discord.Guild,
    staff_roles: list[discord.Role],
    coach_roles: list[discord.Role],
    bot_member: discord.Member | None,
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    if not coach_roles:
        return _public_readonly_overwrites(guild, staff_roles, bot_member)

    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False)
    }
    for role in coach_roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
        )
    for role in staff_roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
            manage_messages=True,
        )
    if bot_member is not None:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            embed_links=True,
            attach_files=True,
        )
    return overwrites


async def _cleanup_staff_monitor(
    guild: discord.Guild,
    *,
    staff_monitor_id: int | None,
    staff_monitor_managed: bool,
    reports_category: discord.CategoryChannel,
    actions: list[str],
) -> str:
    if not staff_monitor_id:
        return "cleared"

    channel = guild.get_channel(staff_monitor_id)
    if channel is None:
        actions.append("Staff monitor channel ID was set but the channel no longer exists; cleared.")
        return "cleared"
    if not isinstance(channel, discord.TextChannel):
        actions.append("Staff monitor channel ID did not point to a text channel; leaving untouched.")
        return "kept"
    if not staff_monitor_managed:
        actions.append("Staff monitor channel exists but is not marked bot-managed; leaving it untouched.")
        return "kept"

    if channel.name != STAFF_MONITOR_CHANNEL_NAME:
        actions.append("Staff monitor channel name did not match expected; leaving it untouched.")
        return "kept"
    if channel.category_id != reports_category.id:
        actions.append("Staff monitor channel category did not match expected; leaving it untouched.")
        return "kept"

    try:
        await channel.delete(reason="Offside: disable test mode")
        actions.append("Deleted staff monitor channel (test mode disabled).")
        return "cleared"
    except discord.DiscordException:
        return "failed"


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
