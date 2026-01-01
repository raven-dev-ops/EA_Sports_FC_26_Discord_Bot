from __future__ import annotations

import discord

from config import Settings
from utils.permissions import is_staff_user
from utils.role_routing import resolve_role_id

_RETIRE_TOGGLE_CUSTOM_IDS = {"recruit:toggle_retired"}


async def enforce_paid_access(interaction: discord.Interaction) -> bool:
    """
    Enforce role-based access for all interactions.

    Policy (guild interactions only):
    - Staff and coaches are always allowed.
    - Members with Free/Premium Player roles are allowed.
    - Members with Free Agent role are allowed (and never auto-marked Retired).
    - Everyone else is denied and (best-effort) given the Retired role.
    """
    guild = interaction.guild
    if guild is None:
        return True

    settings = getattr(interaction.client, "settings", None)
    if settings is None:
        return True

    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    if member is None:
        try:
            member = await guild.fetch_member(interaction.user.id)
        except discord.DiscordException:
            return True

    role_ids = {r.id for r in member.roles if hasattr(r, "id")}

    retired_role_id = resolve_role_id(settings, guild_id=guild.id, field="role_retired_id")

    if is_staff_user(member, settings, guild_id=guild.id):
        return True

    custom_id = _get_custom_id(interaction)
    if custom_id in _RETIRE_TOGGLE_CUSTOM_IDS:
        return True

    if retired_role_id and retired_role_id in role_ids:
        await _send_ephemeral(
            interaction,
            "You are marked as **Retired** (inactive) and cannot use Offside. "
            "Use the Retirement toggle in the Recruitment Portal to become active again, or contact staff.",
        )
        return False

    coach_role_ids = {
        resolve_role_id(settings, guild_id=guild.id, field="role_coach_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_coach_premium_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_coach_premium_plus_id"),
    }
    coach_role_ids.discard(None)
    if coach_role_ids.intersection(role_ids):
        return True

    free_agent_role_id = resolve_role_id(
        settings,
        guild_id=guild.id,
        field="role_free_agent_id",
    ) or resolve_role_id(settings, guild_id=guild.id, field="role_recruit_id")
    if free_agent_role_id and free_agent_role_id in role_ids:
        return True

    paid_role_ids = {
        resolve_role_id(settings, guild_id=guild.id, field="role_free_player_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_premium_player_id"),
    }
    paid_role_ids.discard(None)

    if not coach_role_ids and not paid_role_ids and not free_agent_role_id and not retired_role_id:
        # Access control isn't configured for this guild; fail open.
        return True

    if paid_role_ids.intersection(role_ids):
        return True

    retired_assigned = await _maybe_assign_retired_role(
        member,
        settings,
        retired_role_id=retired_role_id,
    )
    suffix = " You were assigned the **Retired** role." if retired_assigned else ""
    await _send_ephemeral(
        interaction,
        "Offside access is limited to paid members. "
        "Ask staff to assign **Free Player** or **Premium Player** (or give you the **Free Agent** role)."
        f"{suffix}",
    )
    return False


def _get_custom_id(interaction: discord.Interaction) -> str | None:
    data = getattr(interaction, "data", None)
    if not isinstance(data, dict):
        return None
    value = data.get("custom_id")
    return value if isinstance(value, str) else None


async def _send_ephemeral(interaction: discord.Interaction, message: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.DiscordException:
        pass


def _can_manage_role(bot_member: discord.Member, role: discord.Role) -> bool:
    if bot_member.guild_permissions.administrator:
        return True
    try:
        return role < bot_member.top_role
    except TypeError:
        return role.position < bot_member.top_role.position


async def _maybe_assign_retired_role(
    member: discord.Member,
    settings: Settings,
    *,
    retired_role_id: int | None,
) -> bool:
    if not retired_role_id:
        return False
    guild = member.guild
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.manage_roles:
        return False
    role = guild.get_role(retired_role_id)
    if role is None:
        return False
    if role in member.roles:
        return False
    if not _can_manage_role(bot_member, role):
        return False
    try:
        await member.add_roles(role, reason="Offside access control: unpaid member")
    except discord.DiscordException:
        return False
    return True


async def _maybe_clear_retired_role(
    member: discord.Member,
    settings: Settings,
    *,
    retired_role_id: int | None,
) -> None:
    if not retired_role_id:
        return
    guild = member.guild
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.manage_roles:
        return
    role = guild.get_role(retired_role_id)
    if role is None:
        return
    if role not in member.roles:
        return
    if not _can_manage_role(bot_member, role):
        return
    try:
        await member.remove_roles(role, reason="Offside access control: member eligible")
    except discord.DiscordException:
        return
