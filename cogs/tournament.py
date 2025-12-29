from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services import tournament_service as ts


class TournamentCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="tournament_create", description="Create a tournament")
    async def tournament_create(
        self,
        interaction: discord.Interaction,
        name: str,
        format: str = "single_elimination",
        rules: str | None = None,
    ) -> None:
        tour = ts.create_tournament(name=name.strip(), format=format.strip(), rules=rules)
        await interaction.response.send_message(
            f"Tournament `{tour['name']}` created (state: {tour['state']}).", ephemeral=True
        )

    @app_commands.command(name="tournament_state", description="Update tournament state")
    @app_commands.describe(state="DRAFT, REG_OPEN, IN_PROGRESS, COMPLETED")
    async def tournament_state(
        self,
        interaction: discord.Interaction,
        name: str,
        state: str,
    ) -> None:
        state = state.upper()
        if state not in {
            ts.TOURNAMENT_STATE_DRAFT,
            ts.TOURNAMENT_STATE_REG_OPEN,
            ts.TOURNAMENT_STATE_IN_PROGRESS,
            ts.TOURNAMENT_STATE_COMPLETED,
        }:
            await interaction.response.send_message("Invalid state.", ephemeral=True)
            return
        updated = ts.update_tournament_state(name.strip(), state)
        if not updated:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Tournament `{name}` state updated to {state}.", ephemeral=True
        )

    @app_commands.command(name="tournament_register", description="Register a team")
    async def tournament_register(
        self,
        interaction: discord.Interaction,
        tournament: str,
        team_name: str,
        coach_id: str,
        seed: int | None = None,
    ) -> None:
        try:
            coach_int = int(coach_id.replace("<@", "").replace(">", "").replace("!", ""))
        except ValueError:
            await interaction.response.send_message("Invalid coach ID.", ephemeral=True)
            return
        try:
            participant = ts.add_participant(
                tournament_name=tournament.strip(),
                team_name=team_name.strip(),
                coach_id=coach_int,
                seed=seed,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Registered `{participant['team_name']}` for `{tournament}`.", ephemeral=True
        )

    @app_commands.command(name="tournament_bracket", description="Generate a bracket")
    async def tournament_bracket(self, interaction: discord.Interaction, tournament: str) -> None:
        try:
            matches = ts.generate_bracket(tournament_name=tournament.strip())
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        lines = [f"Round {m['round']} Match {m['sequence']}: {m['team_a']} vs {m['team_b']}" for m in matches]
        await interaction.response.send_message(
            "Bracket generated:\n" + "\n".join(lines), ephemeral=True
        )

    @app_commands.command(name="match_report", description="Report a match score")
    async def match_report(
        self,
        interaction: discord.Interaction,
        tournament: str,
        match_id: str,
        reporter_team_id: str,
        score_for: int,
        score_against: int,
    ) -> None:
        try:
            reported = ts.report_score(
                tournament_name=tournament.strip(),
                match_id=match_id,
                reporter_team_id=reporter_team_id,
                score_for=score_for,
                score_against=score_against,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Score recorded for match {match_id}: {score_for}-{score_against}.", ephemeral=True
        )

    @app_commands.command(name="match_confirm", description="Confirm a reported match")
    async def match_confirm(
        self,
        interaction: discord.Interaction,
        tournament: str,
        match_id: str,
        confirming_team_id: str,
    ) -> None:
        try:
            match = ts.confirm_match(
                tournament_name=tournament.strip(),
                match_id=match_id,
                confirming_team_id=confirming_team_id,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Match {match_id} confirmed. Winner: {match.get('winner')}", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentCog(bot))
