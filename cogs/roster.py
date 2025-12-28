from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from interactions.dashboard import build_roster_dashboard


class RosterCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="roster", description="Open the roster dashboard.")
    async def roster(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        settings = getattr(self.bot, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.", ephemeral=True
            )
            return
        embed, view = build_roster_dashboard(interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RosterCog(bot))
