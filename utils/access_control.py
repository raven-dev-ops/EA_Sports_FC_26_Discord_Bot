from __future__ import annotations

import discord

from utils.permissions import is_staff_user
from utils.role_routing import resolve_role_id


async def enforce_paid_access(interaction: discord.Interaction) -> bool:
    """
    Enforce role-based access for all interactions.

    Policy (guild interactions only):
    - Staff and coaches are always allowed.
    - Members with Free Agent or Pro Player roles are allowed.
    - Everyone else is denied.
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

    if is_staff_user(member, settings, guild_id=guild.id):
        return True

    coach_role_ids = {
        resolve_role_id(settings, guild_id=guild.id, field="role_team_coach_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_coach_plus_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_club_manager_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_club_manager_plus_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_league_staff_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_league_owner_id"),
    }
    coach_role_ids.discard(None)
    if coach_role_ids.intersection(role_ids):
        return True

    free_agent_role_id = resolve_role_id(
        settings,
        guild_id=guild.id,
        field="role_free_agent_id",
    ) or resolve_role_id(settings, guild_id=guild.id, field="role_recruit_id") or resolve_role_id(
        settings, guild_id=guild.id, field="role_free_player_id"
    )
    if free_agent_role_id and free_agent_role_id in role_ids:
        return True

    paid_role_ids = {
        resolve_role_id(settings, guild_id=guild.id, field="role_pro_player_id"),
        resolve_role_id(settings, guild_id=guild.id, field="role_premium_player_id"),
    }
    paid_role_ids.discard(None)

    if not coach_role_ids and not paid_role_ids and not free_agent_role_id:
        # Access control isn't configured for this guild; fail open.
        return True

    if paid_role_ids.intersection(role_ids):
        return True

    await _send_ephemeral(
        interaction,
        "Offside access is limited to paid members. "
        "Ask staff to assign **Pro Player** (or give you the **Free Agent** role).",
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
