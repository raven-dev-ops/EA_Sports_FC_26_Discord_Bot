from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import DEFAULT_COLOR, WARNING_COLOR, make_embed


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Show bot commands and examples.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = make_embed(
            title="Offside Bot Help",
            description="Command catalog with examples. All responses are ephemeral.",
            color=DEFAULT_COLOR,
        )
        embed.add_field(
            name="Coach Workflow",
            value=(
                "1) `/roster` → open dashboard modal.\n"
                "2) Add players via **Add Player** (use exact Discord IDs).\n"
                "3) Minimum 8 players to submit; limits depend on coach role.\n"
                "4) **Submit Roster** once ready.\n"
                "5) If rejected, staff will unlock; fix issues and re-submit."
            ),
            inline=False,
        )
        embed.add_field(
            name="Staff Workflow",
            value=(
                "• Review submissions in the staff portal. Use the dashboard buttons to approve/reject.\n"
                "• If rejecting, include a clear reason; then `/unlock_roster @Coach`.\n"
                "• Approved rosters are posted to the roster portal automatically."
            ),
            inline=False,
        )
        embed.add_field(
            name="Coach Commands",
            value=(
                "- `/roster [tournament]` open roster dashboard.\n"
                "- `/help` show this menu."
            ),
            inline=False,
        )
        embed.add_field(
            name="Staff/Admin Commands",
            value=(
                "- `/unlock_roster <coach> [tournament]`\n"
                "- `/dev_on` / `/dev_off` toggle test routing\n"
                "- `/config_view` / `/config_set <field> <value>` (runtime only)\n"
                "- `/ping` health check"
            ),
            inline=False,
        )
        embed.add_field(
            name="Tournament Commands",
            value=(
                "- Setup: `/tournament_create`, `/tournament_state`, `/tournament_register`\n"
                "- Brackets: `/tournament_bracket` publish, `/tournament_bracket_preview` dry-run\n"
                "- Matches: `/match_report`, `/match_confirm`, `/match_deadline`, `/match_forfeit`\n"
                "- Scheduling: `/match_reschedule`, `/dispute_add`, `/dispute_resolve`, `/advance_round`\n"
                "- Groups: `/group_create`, `/group_register`, `/group_generate_fixtures`, "
                "`/group_match_report`, `/group_standings`, `/group_advance`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Roster Submission Steps",
            value=(
                "1) Gather player Discord IDs and your assigned team name.\n"
                "2) Open `/roster`, enter team name and tournament (if requested).\n"
                "3) Add players one by one; verify counts meet min/role limits.\n"
                "4) Submit once; wait for staff review. If rejected, address the reason and re-submit after unlock.\n"
                "5) Approved rosters are final until staff reopens them."
            ),
            inline=False,
        )
        embed.add_field(
            name="Notes",
            value=(
                "- All messages are ephemeral to reduce channel noise.\n"
                "- Use exact team names and IDs; inputs are trimmed/sanitized.\n"
                "- Test mode routes logs and portals to the configured test channel."
            ),
            inline=False,
        )
        embed.set_footer(text="Need more? Reach out in the staff channel.")

        warning = make_embed(
            title="Reminder",
            description="Keep player counts within your role limits and double-check IDs before submitting.",
            color=WARNING_COLOR,
        )
        await interaction.response.send_message(embeds=[embed, warning], ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
