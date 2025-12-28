from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Show bot commands and examples.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Offside Bot Help",
            description="Command list with examples.",
        )
        embed.add_field(
            name="/roster [tournament]",
            value="Open the roster creation modal.\nExample: `/roster`",
            inline=False,
        )
        embed.add_field(
            name="/unlock_roster <coach> [tournament]",
            value="Staff-only roster unlock.\nExample: `/unlock_roster @Coach`",
            inline=False,
        )
        embed.add_field(
            name="/dev_on",
            value="Staff-only test mode routing on.\nExample: `/dev_on`",
            inline=False,
        )
        embed.add_field(
            name="/dev_off",
            value="Staff-only test mode routing off.\nExample: `/dev_off`",
            inline=False,
        )
        embed.add_field(
            name="/ping",
            value="Health check.\nExample: `/ping`",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
