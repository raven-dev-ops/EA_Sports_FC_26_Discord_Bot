from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from interactions.admin_portal import send_admin_portal_message


class AdminPortalCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        settings = getattr(self.bot, "settings", None)
        if settings is None:
            return False
        role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
        if settings.staff_role_ids:
            return bool(role_ids.intersection(settings.staff_role_ids))
        perms = getattr(interaction.user, "guild_permissions", None)
        return bool(perms and perms.manage_guild)

    @app_commands.command(
        name="admin_portal",
        description="Post the admin control panel to the admin portal channel.",
    )
    async def admin_portal(self, interaction: discord.Interaction) -> None:
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You do not have permission to post the admin portal.",
                ephemeral=True,
            )
            return

        await send_admin_portal_message(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminPortalCog(bot))
