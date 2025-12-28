from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from interactions.coach_portal import send_coach_portal_message


class CoachPortalCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="coach_portal",
        description="Post the coach roster portal embed to the roster portal channel.",
    )
    async def coach_portal(self, interaction: discord.Interaction) -> None:
        await send_coach_portal_message(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CoachPortalCog(bot))
