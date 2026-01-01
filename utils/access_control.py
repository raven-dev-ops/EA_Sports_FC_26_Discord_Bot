from __future__ import annotations

import discord

from config import Settings
from utils.permissions import is_staff_user
from utils.role_routing import resolve_role_id


async def enforce_paid_access(interaction: discord.Interaction) -> bool:
    """
    Enforce role-based access for all interactions.

    Policy (guild interactions only):
    - Staff and coaches are always allowed.
    - Members with Free/Premium Player roles are allowed.
    - Members with Recruit role are allowed (and never auto-marked Retired).
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

    if is_staff_user(member, settings, guild_id=guild.id):
        return True

    role_ids = {r.id for r in member.roles if hasattr(r, "id")}

    coach_role_ids = {
        resolve_role_id(settings, guild_id=guild.id, field="role_coach_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_coach_premium_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_coach_premium_plus_id"),
    }
    coach_role_ids.discard(None)
    if coach_role_ids.intersection(role_ids):
        return True

    recruit_role_id = resolve_role_id(settings, guild_id=guild.id, field="role_recruit_id")
    if recruit_role_id and recruit_role_id in role_ids:
        return True

    paid_role_ids = {
        resolve_role_id(settings, guild_id=guild.id, field="role_free_player_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_premium_player_id"),
    }
    paid_role_ids.discard(None)
    retired_role_id = resolve_role_id(settings, guild_id=guild.id, field="role_retired_id")

    if not coach_role_ids and not paid_role_ids and not recruit_role_id and not retired_role_id:
        # Access control isn't configured for this guild; fail open.
        return True

    if paid_role_ids.intersection(role_ids):
        return True

    if retired_role_id and retired_role_id in role_ids:
        await _send_ephemeral(
            interaction,
            "You are marked as **Retired** and cannot use Offside. "
            "If this is incorrect, contact staff.",
        )
        return False

    retired_assigned = await _maybe_assign_retired_role(
        member,
        settings,
        retired_role_id=retired_role_id,
    )
    suffix = " You were assigned the **Retired** role." if retired_assigned else ""
    await _send_ephemeral(
        interaction,
        "Offside access is limited to paid members. "
        "Ask staff to assign **Free Player** or **Premium Player** (or give you the Recruit role)."
        f"{suffix}",
    )
    return False


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
