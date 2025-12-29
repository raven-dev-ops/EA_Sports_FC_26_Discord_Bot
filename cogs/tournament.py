from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services import tournament_service as ts
from services import group_service as gs
from utils.discord_wrappers import fetch_channel, send_message


class TournamentCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _get_channels(
        self, interaction: discord.Interaction, tournament: dict
    ) -> tuple[discord.abc.Messageable | None, discord.abc.Messageable | None]:
        matches_ch = None
        disputes_ch = None
        if tournament.get("matches_channel_id"):
            matches_ch = await fetch_channel(interaction.client, int(tournament["matches_channel_id"]))
        if tournament.get("disputes_channel_id"):
            disputes_ch = await fetch_channel(interaction.client, int(tournament["disputes_channel_id"]))
        return matches_ch, disputes_ch

    @app_commands.command(name="tournament_create", description="Create a tournament")
    async def tournament_create(
        self,
        interaction: discord.Interaction,
        name: str,
        format: str = "single_elimination",
        rules: str | None = None,
    ) -> None:
        matches_channel_id = None
        disputes_channel_id = None
        guild = interaction.guild
        safe_name = name.strip()
        if guild:
            try:
                match_channel = await guild.create_text_channel(f"{safe_name}-matches")
                matches_channel_id = match_channel.id
                disputes_channel = await guild.create_text_channel(f"{safe_name}-disputes")
                disputes_channel_id = disputes_channel.id
            except discord.DiscordException:
                pass
        tour = ts.create_tournament(
            name=safe_name,
            format=format.strip(),
            rules=rules,
            matches_channel_id=matches_channel_id,
            disputes_channel_id=disputes_channel_id,
        )
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
        tour = ts.get_tournament(tournament.strip())
        if tour is None:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
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
        matches_ch, _ = await self._get_channels(interaction, tour)
        if matches_ch:
            await send_message(
                matches_ch,
                f"[{tournament}] Match {match_id} reported: {reporter_team_id} "
                f"{score_for}-{score_against} (status: {reported.get('status')})",
            )
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
        tour = ts.get_tournament(tournament.strip())
        if tour is None:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
        try:
            match = ts.confirm_match(
                tournament_name=tournament.strip(),
                match_id=match_id,
                confirming_team_id=confirming_team_id,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        matches_ch, _ = await self._get_channels(interaction, tour)
        if matches_ch:
            await send_message(
                matches_ch,
                f"[{tournament}] Match {match_id} confirmed. Winner: {match.get('winner')}",
            )
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
        tour = ts.get_tournament(tournament.strip())
        if tour is None:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
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
        matches_ch, disputes_ch = await self._get_channels(interaction, tour)
        target = disputes_ch or matches_ch
        if target:
            await send_message(
                target,
                f"[{tournament}] Reschedule requested for match {match_id} by <@{interaction.user.id}>: {reason}",
            )
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
        tour = ts.get_tournament(tournament.strip())
        if tour is None:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
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
        _, disputes_ch = await self._get_channels(interaction, tour)
        if disputes_ch:
            await send_message(
                disputes_ch,
                f"[{tournament}] Dispute filed on match {match_id} by <@{interaction.user.id}>: {reason}",
            )
        await interaction.response.send_message("Dispute recorded.", ephemeral=True)

    @app_commands.command(name="dispute_resolve", description="Resolve the latest dispute on a match")
    async def dispute_resolve(
        self,
        interaction: discord.Interaction,
        tournament: str,
        match_id: str,
        resolution: str,
    ) -> None:
        tour = ts.get_tournament(tournament.strip())
        if tour is None:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
        try:
            ts.resolve_dispute(
                tournament_name=tournament.strip(),
                match_id=match_id,
                resolution=resolution,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        _, disputes_ch = await self._get_channels(interaction, tour)
        if disputes_ch:
            await send_message(
                disputes_ch,
                f"[{tournament}] Dispute resolved for match {match_id}: {resolution}",
            )
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

    @app_commands.command(name="group_create", description="Create a group within a tournament")
    async def group_create(
        self,
        interaction: discord.Interaction,
        tournament: str,
        group_name: str,
    ) -> None:
        try:
            gs.ensure_group(tournament_name=tournament.strip(), group_name=group_name.strip())
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Group `{group_name}` ensured for tournament `{tournament}`.", ephemeral=True
        )

    @app_commands.command(name="group_register", description="Add a team to a group")
    async def group_register(
        self,
        interaction: discord.Interaction,
        tournament: str,
        group_name: str,
        team_name: str,
        coach_id: str,
    ) -> None:
        try:
            coach_int = int(coach_id.replace("<@", "").replace(">", "").replace("!", ""))
        except ValueError:
            await interaction.response.send_message("Invalid coach ID.", ephemeral=True)
            return
        try:
            gs.add_group_team(
                tournament_name=tournament.strip(),
                group_name=group_name.strip(),
                team_name=team_name.strip(),
                coach_id=coach_int,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Team `{team_name}` registered to group `{group_name}`.", ephemeral=True
        )

    @app_commands.command(name="group_match_report", description="Report a group stage match score")
    async def group_match_report(
        self,
        interaction: discord.Interaction,
        tournament: str,
        group_name: str,
        team_a: str,
        team_b: str,
        score_a: int,
        score_b: int,
    ) -> None:
        try:
            gs.record_group_match(
                tournament_name=tournament.strip(),
                group_name=group_name.strip(),
                team_a=team_a.strip(),
                team_b=team_b.strip(),
                score_a=score_a,
                score_b=score_b,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Recorded {team_a} {score_a}-{score_b} {team_b} in group {group_name}.", ephemeral=True
        )

    @app_commands.command(name="group_standings", description="Show group standings")
    async def group_standings(
        self,
        interaction: discord.Interaction,
        tournament: str,
        group_name: str,
    ) -> None:
        try:
            teams = gs.get_standings(
                tournament_name=tournament.strip(), group_name=group_name.strip()
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        lines = [
            f"{idx+1}. {t['team_name']} - {t['points']} pts (GD {t['gf']-t['ga']}, GF {t['gf']})"
            for idx, t in enumerate(teams)
        ]
        await interaction.response.send_message(
            "Standings:\n" + "\n".join(lines), ephemeral=True
        )

    @app_commands.command(name="group_advance", description="Advance top N from group into bracket")
    async def group_advance(
        self,
        interaction: discord.Interaction,
        tournament: str,
        group_name: str,
        top_n: int,
    ) -> None:
        try:
            advanced = gs.advance_top(
                tournament_name=tournament.strip(),
                group_name=group_name.strip(),
                top_n=top_n,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        names = [p["team_name"] for p in advanced]
        await interaction.response.send_message(
            f"Advanced: {', '.join(names)}", ephemeral=True
        )

    @app_commands.command(name="group_generate_fixtures", description="Generate group round-robin fixtures")
    @app_commands.describe(double_round="If true, creates home/away mirror fixtures.")
    async def group_generate_fixtures(
        self,
        interaction: discord.Interaction,
        tournament: str,
        group_name: str,
        double_round: bool = False,
    ) -> None:
        try:
            fixtures = gs.generate_group_fixtures(
                tournament_name=tournament.strip(),
                group_name=group_name.strip(),
                double_round=double_round,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        lines = [
            f"Round {f['round']} Match {f['sequence']}: {f['team_a']} vs {f.get('team_b')}"
            for f in fixtures
        ]
        await interaction.response.send_message(
            "Fixtures:\n" + "\n".join(lines), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentCog(bot))
