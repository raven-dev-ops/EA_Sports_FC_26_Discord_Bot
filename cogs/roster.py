from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from interactions.views import RosterDashboardView
from services.permission_service import resolve_roster_cap_from_settings
from services.roster_service import (
    count_roster_players,
    get_roster_for_coach,
    roster_is_locked,
)


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

        roles = getattr(interaction.user, "roles", [])
        role_ids = [role.id for role in roles]
        cap = resolve_roster_cap_from_settings(role_ids, settings)

        roster = get_roster_for_coach(interaction.user.id)
        has_roster = roster is not None
        player_count = 0
        status = "NO_ROSTER"
        team_name = "No roster yet"
        is_locked = False

        if roster:
            player_count = count_roster_players(roster["_id"])
            status = roster.get("status", "UNKNOWN")
            team_name = roster.get("team_name", "Unnamed Team")
            is_locked = roster_is_locked(roster)

        embed = discord.Embed(title="Roster Dashboard")
        embed.add_field(name="Team", value=team_name, inline=False)
        embed.add_field(name="Status", value=status, inline=True)

        if cap is None and not has_roster:
            embed.add_field(
                name="Eligibility",
                value="Not eligible for roster creation (missing coach role).",
                inline=False,
            )
        else:
            display_cap = cap if cap is not None else roster.get("cap", "N/A")
            embed.add_field(
                name="Players",
                value=f"{player_count}/{display_cap}",
                inline=True,
            )

        view = RosterDashboardView(
            has_roster=has_roster,
            roster_id=roster["_id"] if roster else None,
            has_players=player_count > 0,
            is_locked=is_locked,
            eligible=cap is not None,
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RosterCog(bot))
