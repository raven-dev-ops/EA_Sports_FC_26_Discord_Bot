from __future__ import annotations

import re
from typing import Any

import discord

from config import Settings
from services import entitlements_service

DASHBOARD_CATEGORY_NAME = "--OFFSIDE DASHBOARD--"
REPORTS_CATEGORY_NAME = "--OFFSIDE REPORTS--"

STAFF_PORTAL_CHANNEL_NAME = "staff-portal"
MANAGER_PORTAL_CHANNEL_NAME = "managers-portal"
LEGACY_MANAGER_PORTAL_CHANNEL_NAME = "club-managers-portal"
LEGACY_CLUB_PORTAL_CHANNEL_NAME = "club-portal"
COACH_PORTAL_CHANNEL_NAME = "coach-portal"
RECRUIT_PORTAL_CHANNEL_NAME = "recruit-portal"
LEGACY_FREE_PLAYER_PORTAL_CHANNEL_NAME = "free-player-portal"
LEGACY_PREMIUM_PLAYER_PORTAL_CHANNEL_NAME = "premium-player-portal"

STAFF_MONITOR_CHANNEL_NAME = "staff-monitor"
ROSTER_LISTING_CHANNEL_NAME = "roster-listing"
RECRUITMENT_BOARDS_CHANNEL_NAME = "recruitment-boards"
LEGACY_RECRUIT_LISTING_CHANNEL_NAME = "recruit-listing"
CLUB_LISTING_CHANNEL_NAME = "club-listing"
PRO_COACHES_CHANNEL_NAME = "pro-coaches"
LEGACY_PREMIUM_COACHES_CHANNEL_NAME = "premium-coaches"

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
    plan = entitlements_service.get_guild_plan(settings, guild_id=guild.id)
    is_pro = entitlements_service.is_paid_plan(plan)

    bot_member = guild.me
    staff_roles = _resolve_staff_roles(
        guild,
        settings,
        config=config,
        bot_member=bot_member,
        actions=actions,
    )
    coach_roles = _resolve_coach_roles(guild, config)

    dashboard_category = await _ensure_category(
        guild,
        DASHBOARD_CATEGORY_NAME,
        actions=actions,
        bot_member=bot_member,
    )
    reports_category = await _ensure_category(
        guild,
        REPORTS_CATEGORY_NAME,
        actions=actions,
        bot_member=bot_member,
    )

    await _cleanup_duplicate_offside_categories(
        guild,
        config=config,
        dashboard_category=dashboard_category,
        reports_category=reports_category,
        actions=actions,
    )
    await _migrate_manager_portal_channel(
        guild,
        config=config,
        dashboard_category=dashboard_category,
        actions=actions,
    )
    if is_pro:
        await _migrate_pro_coaches_channel(
            guild,
            config=config,
            reports_category=reports_category,
            actions=actions,
        )
    else:
        actions.append("Skipped pro coaches channel migration (requires Pro).")
    await _migrate_recruitment_boards_channel(
        guild,
        config=config,
        reports_category=reports_category,
        actions=actions,
    )
    await _migrate_roster_listing_channel(
        guild,
        config=config,
        reports_category=reports_category,
        actions=actions,
    )

    dashboard_channels: list[discord.TextChannel] = []
    dashboard_specs: list[tuple[str, str, dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]]] = [
        (
            STAFF_PORTAL_CHANNEL_NAME,
            "channel_staff_portal_id",
            _staff_only_overwrites(guild, staff_roles, bot_member),
        ),
        (
            MANAGER_PORTAL_CHANNEL_NAME,
            "channel_manager_portal_id",
            _staff_only_overwrites(guild, staff_roles, bot_member),
        ),
        (
            COACH_PORTAL_CHANNEL_NAME,
            "channel_coach_portal_id",
            _coach_portal_overwrites(guild, staff_roles, coach_roles, bot_member),
        ),
        (
            RECRUIT_PORTAL_CHANNEL_NAME,
            "channel_recruit_portal_id",
            _public_readonly_overwrites(guild, staff_roles, bot_member),
        ),
    ]

    for name, key, overwrites in dashboard_specs:
        try:
            channel = await _ensure_text_channel(
                guild,
                category=dashboard_category,
                name=name,
                overwrites=overwrites,
                existing_channel_id=_parse_int(config.get(key)),
                actions=actions,
            )
        except discord.Forbidden:
            actions.append(
                f"Could not create `{name}` (missing permissions). "
                "Ensure the bot has `Manage Channels` and can access the Offside dashboard category."
            )
            continue
        dashboard_channels.append(channel)
        config[key] = channel.id

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
        try:
            staff_monitor_channel, created = await _ensure_text_channel_with_created(
                guild,
                category=reports_category,
                name=STAFF_MONITOR_CHANNEL_NAME,
                overwrites=_staff_only_overwrites(guild, staff_roles, bot_member),
                existing_channel_id=staff_monitor_id,
                actions=actions,
            )
        except discord.Forbidden:
            actions.append(
                "Could not create staff monitor channel (missing permissions). "
                "Grant the bot `Manage Channels` and retry."
            )
        else:
            reports_channels.append(staff_monitor_channel)
            config["channel_staff_monitor_id"] = staff_monitor_channel.id
            if created:
                config[STAFF_MONITOR_MANAGED_KEY] = True
            else:
                config[STAFF_MONITOR_MANAGED_KEY] = bool(
                    staff_monitor_managed and staff_monitor_id == staff_monitor_channel.id
                )

    reports_specs: list[tuple[str, str]] = [
        (RECRUITMENT_BOARDS_CHANNEL_NAME, "channel_recruit_listing_id"),
        (CLUB_LISTING_CHANNEL_NAME, "channel_club_listing_id"),
    ]
    if is_pro:
        reports_specs.append((PRO_COACHES_CHANNEL_NAME, "channel_premium_coaches_id"))
    else:
        actions.append("Skipped pro coaches channel creation (requires Pro).")
    reports_overwrites = _public_readonly_overwrites(guild, staff_roles, bot_member)
    for name, key in reports_specs:
        try:
            channel = await _ensure_text_channel(
                guild,
                category=reports_category,
                name=name,
                overwrites=reports_overwrites,
                existing_channel_id=_parse_int(config.get(key)),
                actions=actions,
            )
        except discord.Forbidden:
            actions.append(
                f"Could not create `{name}` (missing permissions). "
                "Ensure the bot can manage channels in the Offside reports category."
            )
            continue
        reports_channels.append(channel)
        config[key] = channel.id

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
    guild: discord.Guild,
    name: str,
    *,
    actions: list[str],
    bot_member: discord.Member | None = None,
) -> discord.CategoryChannel:
    candidates = [cat for cat in guild.categories if cat.name == name]
    if candidates:
        category = _pick_category_candidate(candidates)
        if bot_member is not None:
            await _ensure_category_bot_access(category, bot_member=bot_member, actions=actions)
        return category

    category = await guild.create_category(name, reason="Offside setup")
    actions.append(f"Created category `{name}`.")
    if bot_member is not None:
        await _ensure_category_bot_access(category, bot_member=bot_member, actions=actions)
    return category


def _pick_category_candidate(candidates: list[discord.CategoryChannel]) -> discord.CategoryChannel:
    if len(candidates) == 1:
        return candidates[0]
    return sorted(candidates, key=lambda cat: (-len(cat.channels), cat.position))[0]


async def _ensure_category_bot_access(
    category: discord.CategoryChannel,
    *,
    bot_member: discord.Member,
    actions: list[str],
) -> None:
    if bot_member.guild_permissions.administrator:
        return
    perms = category.permissions_for(bot_member)
    if perms.view_channel and perms.manage_channels:
        return
    if not bot_member.guild_permissions.manage_channels:
        return
    try:
        await category.set_permissions(
            bot_member,
            view_channel=True,
            manage_channels=True,
            send_messages=True,
            read_message_history=True,
            reason="Offside setup: ensure bot access",
        )
    except discord.Forbidden:
        actions.append(
            f"Category `{category.name}` has restricted permissions. "
            "Grant the bot `View Channel` + `Manage Channels` for this category and retry setup."
        )
        return
    except discord.DiscordException:
        return
    actions.append(f"Updated permissions for category `{category.name}` to allow bot access.")


async def _ensure_text_channel(
    guild: discord.Guild,
    *,
    category: discord.CategoryChannel,
    name: str,
    overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite],
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
    overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite],
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
        try:
            channel = await guild.create_text_channel(
                name,
                category=category,
                overwrites=overwrites,
                reason="Offside setup",
            )
        except discord.Forbidden:
            # Fallback: try creating without custom overwrites (inherit category permissions).
            try:
                channel = await guild.create_text_channel(
                    name,
                    category=category,
                    reason="Offside setup (fallback: no overwrites)",
                )
                actions.append(
                    f"Created <#{channel.id}> under `{category.name}` without custom permissions. "
                    "Please verify channel permissions."
                )
            except discord.Forbidden:
                channel = None

            if channel is not None:
                try:
                    await channel.edit(overwrites=overwrites, reason="Offside setup: apply permissions")
                except discord.DiscordException:
                    actions.append(
                        f"Could not apply permissions for <#{channel.id}> automatically. Please verify channel permissions."
                    )
                return channel, True

            # Final fallback: create the channel without a parent category (minimally), then attempt to move it into place.
            try:
                channel = await guild.create_text_channel(
                    name,
                    reason="Offside setup (fallback: no category)",
                )
                actions.append(
                    f"Created <#{channel.id}> outside `{category.name}` (category permissions blocked channel creation)."
                )
            except discord.Forbidden:
                raise
            try:
                await channel.edit(category=category, reason="Offside setup: move into category")
            except discord.DiscordException:
                actions.append(
                    f"Could not move <#{channel.id}> into `{category.name}` automatically. "
                    "Please move it manually and verify category permissions."
                )
            try:
                await channel.edit(overwrites=overwrites, reason="Offside setup: apply permissions")
            except discord.DiscordException:
                actions.append(
                    f"Could not apply permissions for <#{channel.id}> automatically. Please verify channel permissions."
                )
            return channel, True
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


def _resolve_staff_roles(
    guild: discord.Guild,
    settings: Settings,
    *,
    config: dict[str, Any],
    bot_member: discord.Member | None,
    actions: list[str],
) -> list[discord.Role]:
    role_ids: set[int] = set()

    # Prefer explicit env configuration.
    role_ids.update(settings.staff_role_ids)

    # If unset, fall back to per-guild config (auto-setup can populate this).
    if not role_ids:
        role_ids |= _parse_int_set(config.get("staff_role_ids"))

    # If still unset, infer via permissions.
    if not role_ids:
        for role in guild.roles:
            if role.is_default():
                continue
            if role.permissions.administrator or role.permissions.manage_guild:
                role_ids.add(role.id)

    # Always include staff roles (if present) when env staff roles aren't configured.
    if not settings.staff_role_ids:
        for key in (
            "role_league_owner_id",
            "role_club_manager_plus_id",
            "role_club_manager_id",
            "role_coach_plus_id",
            "role_league_staff_id",
            "role_team_coach_id",
            "role_owner_id",
            "role_manager_id",
            "role_coach_id",
            "role_coach_premium_id",
            "role_coach_premium_plus_id",
        ):
            role_id = _parse_int(config.get(key))
            if role_id:
                role_ids.add(role_id)

    roles: list[discord.Role] = []
    for role_id in sorted(role_ids):
        resolved_role = guild.get_role(role_id)
        if resolved_role is not None and not resolved_role.is_default():
            roles.append(resolved_role)

    return _filter_roles_for_overwrites(roles, bot_member=bot_member, actions=actions)


async def _cleanup_duplicate_offside_categories(
    guild: discord.Guild,
    *,
    config: dict[str, Any],
    dashboard_category: discord.CategoryChannel,
    reports_category: discord.CategoryChannel,
    actions: list[str],
) -> None:
    managed_ids = {
        _parse_int(config.get(key))
        for key in (
            "channel_staff_portal_id",
            "channel_manager_portal_id",
            "channel_club_portal_id",
            "channel_coach_portal_id",
            "channel_recruit_portal_id",
            "channel_free_player_portal_id",
            "channel_premium_player_portal_id",
            "channel_staff_monitor_id",
            "channel_roster_listing_id",
            "channel_recruit_listing_id",
            "channel_club_listing_id",
            "channel_premium_coaches_id",
        )
        if _parse_int(config.get(key))
    }

    managed_names = {
        STAFF_PORTAL_CHANNEL_NAME,
        MANAGER_PORTAL_CHANNEL_NAME,
        LEGACY_MANAGER_PORTAL_CHANNEL_NAME,
        LEGACY_CLUB_PORTAL_CHANNEL_NAME,
        COACH_PORTAL_CHANNEL_NAME,
        RECRUIT_PORTAL_CHANNEL_NAME,
        LEGACY_FREE_PLAYER_PORTAL_CHANNEL_NAME,
        LEGACY_PREMIUM_PLAYER_PORTAL_CHANNEL_NAME,
        STAFF_MONITOR_CHANNEL_NAME,
        ROSTER_LISTING_CHANNEL_NAME,
        RECRUITMENT_BOARDS_CHANNEL_NAME,
        LEGACY_RECRUIT_LISTING_CHANNEL_NAME,
        CLUB_LISTING_CHANNEL_NAME,
        PRO_COACHES_CHANNEL_NAME,
        LEGACY_PREMIUM_COACHES_CHANNEL_NAME,
    }

    repairs: list[tuple[discord.CategoryChannel, discord.CategoryChannel]] = []
    for category in guild.categories:
        if _is_repair_category_name(category.name, DASHBOARD_CATEGORY_NAME):
            repairs.append((category, dashboard_category))
        elif _is_repair_category_name(category.name, REPORTS_CATEGORY_NAME):
            repairs.append((category, reports_category))

    for duplicate_category, target_category in repairs:
        moved_any = False
        for channel in list(duplicate_category.channels):
            if not isinstance(channel, discord.TextChannel):
                continue
            if channel.id not in managed_ids and getattr(channel, "name", "") not in managed_names:
                continue
            try:
                await channel.edit(
                    category=target_category,
                    reason="Offside setup: cleanup duplicate categories",
                )
            except discord.DiscordException:
                actions.append(
                    f"Could not move <#{channel.id}> from `{duplicate_category.name}` to `{target_category.name}`. "
                    "Please move it manually."
                )
                continue
            moved_any = True

        if moved_any:
            actions.append(
                f"Moved Offside channels from `{duplicate_category.name}` to `{target_category.name}`."
            )

        if duplicate_category.channels:
            actions.append(
                f"Duplicate category `{duplicate_category.name}` still contains channels; leaving it in place."
            )
            continue

        try:
            await duplicate_category.delete(reason="Offside setup: cleanup duplicate categories")
        except discord.DiscordException:
            actions.append(f"Could not delete duplicate category `{duplicate_category.name}`.")
        else:
            actions.append(f"Deleted duplicate category `{duplicate_category.name}`.")


def _is_repair_category_name(category_name: str, canonical_name: str) -> bool:
    pattern = re.compile(rf"^{re.escape(canonical_name)}\s*\(offside\)", re.IGNORECASE)
    return bool(pattern.match(category_name))


async def _migrate_pro_coaches_channel(
    guild: discord.Guild,
    *,
    config: dict[str, Any],
    reports_category: discord.CategoryChannel,
    actions: list[str],
) -> None:
    target_name = PRO_COACHES_CHANNEL_NAME
    legacy_name = LEGACY_PREMIUM_COACHES_CHANNEL_NAME
    channel_id = _parse_int(config.get("channel_premium_coaches_id"))
    managed_channel: discord.TextChannel | None = None
    if channel_id:
        existing = guild.get_channel(channel_id)
        if isinstance(existing, discord.TextChannel):
            managed_channel = existing

    existing_target = discord.utils.get(reports_category.text_channels, name=target_name)
    if existing_target is None:
        existing_target = discord.utils.get(guild.text_channels, name=target_name)

    if managed_channel is not None and existing_target is not None and managed_channel.id != existing_target.id:
        config["channel_premium_coaches_id"] = existing_target.id
        actions.append("Found existing `pro-coaches` channel; updated config to use it.")
        return

    if managed_channel is not None:
        if managed_channel.name == legacy_name:
            try:
                await managed_channel.edit(
                    name=target_name,
                    reason="Offside setup: rename premium coaches channel",
                )
            except discord.Forbidden:
                actions.append(
                    "Could not rename `premium-coaches` (missing permissions). "
                    "Will create `pro-coaches` instead."
                )
                config.pop("channel_premium_coaches_id", None)
            else:
                actions.append("Renamed `premium-coaches` to `pro-coaches`.")
                config["channel_premium_coaches_id"] = managed_channel.id
            return
        if managed_channel.name == target_name:
            config["channel_premium_coaches_id"] = managed_channel.id
            return

    if existing_target is not None:
        config["channel_premium_coaches_id"] = existing_target.id
        return

    legacy_channel = discord.utils.get(reports_category.text_channels, name=legacy_name)
    if legacy_channel is None:
        legacy_channel = discord.utils.get(guild.text_channels, name=legacy_name)
    if legacy_channel is None:
        return
    try:
        await legacy_channel.edit(
            name=target_name,
            reason="Offside setup: rename premium coaches channel",
        )
    except discord.Forbidden:
        actions.append(
            "Could not rename `premium-coaches` (missing permissions). "
            "Will create `pro-coaches` instead."
        )
        config.pop("channel_premium_coaches_id", None)
        return
    actions.append("Renamed `premium-coaches` to `pro-coaches`.")
    config["channel_premium_coaches_id"] = legacy_channel.id


async def _migrate_manager_portal_channel(
    guild: discord.Guild,
    *,
    config: dict[str, Any],
    dashboard_category: discord.CategoryChannel,
    actions: list[str],
) -> None:
    target_name = MANAGER_PORTAL_CHANNEL_NAME
    legacy_name = LEGACY_MANAGER_PORTAL_CHANNEL_NAME
    channel_id = _parse_int(config.get("channel_manager_portal_id"))
    managed_channel: discord.TextChannel | None = None
    if channel_id:
        existing = guild.get_channel(channel_id)
        if isinstance(existing, discord.TextChannel):
            managed_channel = existing

    existing_target = discord.utils.get(dashboard_category.text_channels, name=target_name)
    if existing_target is None:
        existing_target = discord.utils.get(guild.text_channels, name=target_name)

    if managed_channel is not None and existing_target is not None and managed_channel.id != existing_target.id:
        config["channel_manager_portal_id"] = existing_target.id
        actions.append("Found existing `managers-portal` channel; updated config to use it.")
        return

    if managed_channel is not None:
        if managed_channel.name == legacy_name:
            try:
                await managed_channel.edit(
                    name=target_name,
                    reason="Offside setup: rename managers portal channel",
                )
            except discord.Forbidden:
                actions.append(
                    "Could not rename `club-managers-portal` (missing permissions). "
                    "Will create `managers-portal` instead."
                )
                config.pop("channel_manager_portal_id", None)
            else:
                actions.append("Renamed `club-managers-portal` to `managers-portal`.")
                config["channel_manager_portal_id"] = managed_channel.id
            return
        if managed_channel.name == target_name:
            config["channel_manager_portal_id"] = managed_channel.id
            return

    if existing_target is not None:
        config["channel_manager_portal_id"] = existing_target.id
        return

    legacy_channel = discord.utils.get(dashboard_category.text_channels, name=legacy_name)
    if legacy_channel is None:
        legacy_channel = discord.utils.get(guild.text_channels, name=legacy_name)
    if legacy_channel is None:
        return
    try:
        await legacy_channel.edit(
            name=target_name,
            reason="Offside setup: rename managers portal channel",
        )
    except discord.Forbidden:
        actions.append(
            "Could not rename `club-managers-portal` (missing permissions). "
            "Will create `managers-portal` instead."
        )
        config.pop("channel_manager_portal_id", None)
        return
    actions.append("Renamed `club-managers-portal` to `managers-portal`.")
    config["channel_manager_portal_id"] = legacy_channel.id


async def _migrate_recruitment_boards_channel(
    guild: discord.Guild,
    *,
    config: dict[str, Any],
    reports_category: discord.CategoryChannel,
    actions: list[str],
) -> None:
    target_name = RECRUITMENT_BOARDS_CHANNEL_NAME
    legacy_name = LEGACY_RECRUIT_LISTING_CHANNEL_NAME
    channel_id = _parse_int(config.get("channel_recruit_listing_id"))
    managed_channel: discord.TextChannel | None = None
    if channel_id:
        existing = guild.get_channel(channel_id)
        if isinstance(existing, discord.TextChannel):
            managed_channel = existing

    existing_target = discord.utils.get(reports_category.text_channels, name=target_name)
    if existing_target is None:
        existing_target = discord.utils.get(guild.text_channels, name=target_name)

    if managed_channel is not None and existing_target is not None and managed_channel.id != existing_target.id:
        config["channel_recruit_listing_id"] = existing_target.id
        actions.append("Found existing `recruitment-boards` channel; updated config to use it.")
        return

    if managed_channel is not None:
        if managed_channel.name == legacy_name:
            try:
                await managed_channel.edit(
                    name=target_name,
                    reason="Offside setup: rename recruit listing channel",
                )
            except discord.Forbidden:
                actions.append(
                    "Could not rename `recruit-listing` (missing permissions). "
                    "Will create `recruitment-boards` instead."
                )
                config.pop("channel_recruit_listing_id", None)
            else:
                actions.append("Renamed `recruit-listing` to `recruitment-boards`.")
                config["channel_recruit_listing_id"] = managed_channel.id
            return
        if managed_channel.name == target_name:
            config["channel_recruit_listing_id"] = managed_channel.id
            return

    if existing_target is not None:
        config["channel_recruit_listing_id"] = existing_target.id
        return

    legacy_channel = discord.utils.get(reports_category.text_channels, name=legacy_name)
    if legacy_channel is None:
        legacy_channel = discord.utils.get(guild.text_channels, name=legacy_name)
    if legacy_channel is None:
        return
    try:
        await legacy_channel.edit(
            name=target_name,
            reason="Offside setup: rename recruit listing channel",
        )
    except discord.Forbidden:
        actions.append(
            "Could not rename `recruit-listing` (missing permissions). "
            "Will create `recruitment-boards` instead."
        )
        config.pop("channel_recruit_listing_id", None)
        return
    actions.append("Renamed `recruit-listing` to `recruitment-boards`.")
    config["channel_recruit_listing_id"] = legacy_channel.id


async def _migrate_roster_listing_channel(
    guild: discord.Guild,
    *,
    config: dict[str, Any],
    reports_category: discord.CategoryChannel,
    actions: list[str],
) -> None:
    target_name = CLUB_LISTING_CHANNEL_NAME
    legacy_name = ROSTER_LISTING_CHANNEL_NAME
    roster_id = _parse_int(config.get("channel_roster_listing_id"))
    club_id = _parse_int(config.get("channel_club_listing_id"))

    roster_channel: discord.TextChannel | None = None
    if roster_id:
        existing = guild.get_channel(roster_id)
        if isinstance(existing, discord.TextChannel):
            roster_channel = existing

    club_channel: discord.TextChannel | None = None
    if club_id:
        existing = guild.get_channel(club_id)
        if isinstance(existing, discord.TextChannel):
            club_channel = existing

    existing_target = club_channel
    if existing_target is None:
        existing_target = discord.utils.get(reports_category.text_channels, name=target_name)
    if existing_target is None:
        existing_target = discord.utils.get(guild.text_channels, name=target_name)

    if existing_target is not None:
        if club_id != existing_target.id:
            config["channel_club_listing_id"] = existing_target.id
            actions.append("Found existing `club-listing` channel; updated config to use it.")
        if roster_id and roster_id != config.get("channel_club_listing_id"):
            config.pop("channel_roster_listing_id", None)
            actions.append("Deprecated `roster-listing` config cleared (club listings now used).")
        return

    if roster_channel is not None:
        config["channel_club_listing_id"] = roster_channel.id
        config.pop("channel_roster_listing_id", None)
        if roster_channel.name != target_name:
            try:
                await roster_channel.edit(
                    name=target_name,
                    reason="Offside setup: merge roster listing into club listings",
                )
            except discord.Forbidden:
                actions.append(
                    "Could not rename `roster-listing` (missing permissions). "
                    "Using it as the club listings channel."
                )
            else:
                actions.append("Renamed `roster-listing` to `club-listing`.")
        return

    legacy_channel = discord.utils.get(reports_category.text_channels, name=legacy_name)
    if legacy_channel is None:
        legacy_channel = discord.utils.get(guild.text_channels, name=legacy_name)
    if legacy_channel is None:
        return

    config["channel_club_listing_id"] = legacy_channel.id
    config.pop("channel_roster_listing_id", None)
    try:
        await legacy_channel.edit(
            name=target_name,
            reason="Offside setup: merge roster listing into club listings",
        )
    except discord.Forbidden:
        actions.append(
            "Could not rename `roster-listing` (missing permissions). "
            "Using it as the club listings channel."
        )
    else:
        actions.append("Renamed `roster-listing` to `club-listing`.")


def _filter_roles_for_overwrites(
    roles: list[discord.Role],
    *,
    bot_member: discord.Member | None,
    actions: list[str],
) -> list[discord.Role]:
    if bot_member is None:
        return roles
    if bot_member.guild_permissions.administrator:
        return roles

    top_role = bot_member.top_role
    filtered: list[discord.Role] = []
    for role in roles:
        if role.permissions.administrator:
            # Administrator roles can already view channels and are not needed in overwrites.
            continue
        try:
            manageable = role < top_role
        except TypeError:
            manageable = role.position < top_role.position
        if manageable:
            filtered.append(role)
            continue
        actions.append(
            f"Staff role `{role.name}` is above the bot; skipped in channel permissions. "
            "Move the bot role above it or set `staff_role_ids` to manageable roles."
        )
    return filtered


def _resolve_portal_roles(guild: discord.Guild, config: dict[str, Any], *, key: str) -> list[discord.Role]:
    role_id = _parse_int(config.get(key))
    if role_id:
        resolved_role = guild.get_role(role_id)
        if resolved_role is not None and not resolved_role.is_default():
            return [resolved_role]

    fallback_names = {
        "role_free_agent_id": "Free Agent",
        "role_pro_player_id": "Pro Player",
    }
    fallback_name = fallback_names.get(key)
    if fallback_name:
        resolved_role = discord.utils.get(guild.roles, name=fallback_name)
        if resolved_role is not None and not resolved_role.is_default():
            return [resolved_role]

    return []


def _role_portal_overwrites(
    guild: discord.Guild,
    *,
    staff_roles: list[discord.Role],
    target_roles: list[discord.Role],
    bot_member: discord.Member | None,
) -> dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]:
    if not target_roles:
        return _public_readonly_overwrites(guild, staff_roles, bot_member)

    overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False)
    }
    for role in target_roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
        )
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


def _staff_only_overwrites(
    guild: discord.Guild,
    staff_roles: list[discord.Role],
    bot_member: discord.Member | None,
) -> dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]:
    overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
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
) -> dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]:
    overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
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

    for key in (
        "role_team_coach_id",
        "role_coach_plus_id",
        "role_club_manager_id",
        "role_club_manager_plus_id",
        "role_coach_id",
        "role_coach_premium_id",
        "role_coach_premium_plus_id",
        "role_manager_id",
    ):
        role_id = _parse_int(config.get(key))
        if not role_id:
            continue
        role = guild.get_role(role_id)
        if role is not None and not role.is_default():
            resolved[role.id] = role

    if resolved:
        return list(resolved.values())

    for name in (
        "Coach",
        "Coach+",
        "Club Manager",
        "Club Manager+",
        "Team Coach",
        "Coach Premium",
        "Coach Premium+",
        "Coach Premium Plus",
        "Manager",
    ):
        role = discord.utils.get(guild.roles, name=name)
        if role is not None and not role.is_default():
            resolved[role.id] = role

    return list(resolved.values())


def _coach_portal_overwrites(
    guild: discord.Guild,
    staff_roles: list[discord.Role],
    coach_roles: list[discord.Role],
    bot_member: discord.Member | None,
) -> dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]:
    if not coach_roles:
        return _public_readonly_overwrites(guild, staff_roles, bot_member)

    overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
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
