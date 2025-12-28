from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class DevCog(commands.Cog):
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

    @app_commands.command(
        name="dev_on", description="Enable test mode routing for this bot session."
    )
    async def dev_on(self, interaction: discord.Interaction) -> None:
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You do not have permission to toggle test mode.",
                ephemeral=True,
            )
            return

        self.bot.test_mode = True
        test_channel_id = getattr(self.bot, "test_channel_id", None)
        if test_channel_id:
            await interaction.response.send_message(
                f"Test mode enabled. Routing to <#{test_channel_id}>.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Test mode enabled, but DISCORD_TEST_CHANNEL is not set.",
            ephemeral=True,
        )

    @app_commands.command(
        name="dev_off", description="Disable test mode routing for this bot session."
    )
    async def dev_off(self, interaction: discord.Interaction) -> None:
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You do not have permission to toggle test mode.",
                ephemeral=True,
            )
            return

        self.bot.test_mode = False
        await interaction.response.send_message(
            "Test mode disabled. Using configured channels.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DevCog(bot))
