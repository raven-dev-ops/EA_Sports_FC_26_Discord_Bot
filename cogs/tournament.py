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

    @app_commands.command(name="match_deadline", description="Set a match deadline note")
    async def match_deadline(
        self,
        interaction: discord.Interaction,
        tournament: str,
        match_id: str,
        deadline: str,
    ) -> None:
        ok = ts.set_match_deadline(tournament_name=tournament.strip(), match_id=match_id, deadline=deadline)
        if not ok:
            await interaction.response.send_message("Tournament or match not found.", ephemeral=True)
            return
        await interaction.response.send_message(f"Deadline set for match {match_id}.", ephemeral=True)

    @app_commands.command(name="match_forfeit", description="Forfeit a match to a winner")
    async def match_forfeit(
        self,
        interaction: discord.Interaction,
        tournament: str,
        match_id: str,
        winner_team_id: str,
    ) -> None:
        try:
            match = ts.forfeit_match(
                tournament_name=tournament.strip(),
                match_id=match_id,
                winner_team_id=winner_team_id,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Match {match_id} forfeited. Winner: {match.get('winner')}", ephemeral=True
        )

    @app_commands.command(name="match_reschedule", description="Request a reschedule for a match")
    async def match_reschedule(
        self,
        interaction: discord.Interaction,
        tournament: str,
        match_id: str,
        reason: str,
    ) -> None:
        try:
            req = ts.request_reschedule(
                tournament_name=tournament.strip(),
                match_id=match_id,
                reason=reason,
                requested_by=interaction.user.id,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Reschedule request noted for match {match_id}. ({len(req.get('reschedule_requests', []))} requests total)",
            ephemeral=True,
        )

    @app_commands.command(name="dispute_add", description="File a dispute for a match")
    async def dispute_add(
        self,
        interaction: discord.Interaction,
        tournament: str,
        match_id: str,
        reason: str,
    ) -> None:
        try:
            ts.add_dispute(
                tournament_name=tournament.strip(),
                match_id=match_id,
                reason=reason,
                filed_by=interaction.user.id,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message("Dispute recorded.", ephemeral=True)

    @app_commands.command(name="dispute_resolve", description="Resolve the latest dispute on a match")
    async def dispute_resolve(
        self,
        interaction: discord.Interaction,
        tournament: str,
        match_id: str,
        resolution: str,
    ) -> None:
        try:
            ts.resolve_dispute(
                tournament_name=tournament.strip(),
                match_id=match_id,
                resolution=resolution,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message("Dispute resolved.", ephemeral=True)

    @app_commands.command(name="advance_round", description="Advance winners to the next round")
    async def advance_round(self, interaction: discord.Interaction, tournament: str) -> None:
        try:
            matches = ts.advance_round(tournament_name=tournament.strip())
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        lines = [f"Round {m['round']} Match {m['sequence']}: {m['team_a']} vs {m['team_b']}" for m in matches]
        await interaction.response.send_message(
            "Next round created:\n" + "\n".join(lines),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentCog(bot))
