from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.roster_service import ROSTER_STATUS_UNLOCKED, get_roster_for_coach, set_roster_status


class StaffCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        settings = getattr(self.bot, "settings", None)
        if settings is None:
            return False
        role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
        if settings.staff_role_ids:
            return bool(role_ids.intersection(settings.staff_role_ids))
        return bool(getattr(interaction.user, "guild_permissions", None).manage_guild)

    @app_commands.command(name="unlock_roster", description="Unlock a roster for edits.")
    @app_commands.describe(coach="Coach whose roster should be unlocked")
    async def unlock_roster(
        self, interaction: discord.Interaction, coach: discord.Member
    ) -> None:
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You do not have permission to unlock rosters.",
                ephemeral=True,
            )
            return

        roster = get_roster_for_coach(coach.id)
        if roster is None:
            await interaction.response.send_message(
                "Roster not found for that coach.",
                ephemeral=True,
            )
            return

        set_roster_status(roster["_id"], ROSTER_STATUS_UNLOCKED)
        await interaction.response.send_message(
            f"Roster unlocked for {coach.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StaffCog(bot))
