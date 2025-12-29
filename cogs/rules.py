from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import DEFAULT_COLOR, make_embed

RULES_TEMPLATE = """\
**Competition Name**: <Enter tournament name>
**Game/Platform**: EA Sports FC 26, platform(s) allowed
**Format**: Single-elim / Double-elim / Group + Knockout (specify)
**Seeding**: Random / Based on prior season / Points
**Match Length & Settings**: Halves, extra time, penalties, pauses, squads allowed/banned
**Region/Latency**: Primary server/region, host selection, DC/lag policy
**Scheduling**: Deadlines per round, extension rules, forfeits
**Reporting**: Screenshot or video proof required? Where to post results?
**Rosters**: Max/min players, lock time, transfer/loan rules, ID verification
**Disputes**: How to file (use `/dispute_add`), what evidence is needed, SLA for response
**Reschedules**: Use `/match_reschedule`, allowable reasons, max per team
**Conduct**: Code of conduct, cheating/exploit bans, harassment policy
**Penalties**: Warnings, game loss, DQ, bans (duration)
**Admins**: List of staff roles responsible for rulings
"""


class RulesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="rules_template", description="Get a starter rules template to paste and edit.")
    async def rules_template(self, interaction: discord.Interaction) -> None:
        embed = make_embed(
            title="Tournament Rules Template",
            description=RULES_TEMPLATE,
            color=DEFAULT_COLOR,
            footer="Copy, edit, and post in your tournament channel.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RulesCog(bot))
