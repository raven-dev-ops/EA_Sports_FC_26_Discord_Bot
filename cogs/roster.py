from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from interactions.modals import CreateRosterModal
from repositories.tournament_repo import ensure_cycle_by_name


class RosterCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="roster", description="Open the roster dashboard.")
    @app_commands.describe(tournament="Optional tournament cycle name.")
    async def roster(
        self, interaction: discord.Interaction, tournament: str | None = None
    ) -> None:
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
        cycle_id = None
        if tournament:
            cycle = ensure_cycle_by_name(tournament.strip())
            cycle_id = cycle["_id"]
        await interaction.response.send_modal(CreateRosterModal(cycle_id=cycle_id))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RosterCog(bot))
