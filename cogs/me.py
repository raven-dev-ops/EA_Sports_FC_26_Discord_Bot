from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from interactions.recruit_embeds import build_recruit_profile_embed
from services.fc25_stats_feature import fc25_stats_enabled
from services.fc25_stats_service import get_latest_snapshot, get_link
from services.recruitment_service import get_recruit_profile


class MeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="me", description="Show your stored recruit profile preview.")
    async def me(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command must be used in a guild.",
                ephemeral=True,
            )
            return

        profile = None
        try:
            profile = get_recruit_profile(guild.id, interaction.user.id)
        except Exception:
            profile = None
        if not profile:
            await interaction.response.send_message(
                "No recruit profile found yet. Use the Recruitment Portal to register.",
                ephemeral=True,
            )
            return

        settings = getattr(self.bot, "settings", None)
        fc25_link = None
        fc25_snapshot = None
        if settings is not None and fc25_stats_enabled(settings, guild_id=guild.id):
            try:
                fc25_link = get_link(guild.id, interaction.user.id)
                if fc25_link:
                    fc25_snapshot = get_latest_snapshot(guild.id, interaction.user.id)
            except Exception:
                fc25_link = None
                fc25_snapshot = None

        embed = build_recruit_profile_embed(
            profile,
            fc25_link=fc25_link,
            fc25_snapshot=fc25_snapshot,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MeCog(bot))

