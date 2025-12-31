from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services import entitlements_service, stats_service
from services import group_service as gs
from services import tournament_service as ts
from utils.discord_wrappers import edit_message, fetch_channel, send_message
from utils.embeds import DEFAULT_COLOR, SUCCESS_COLOR, WARNING_COLOR, make_embed
from utils.permissions import is_staff_user
from utils.validation import sanitize_text


class TournamentCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.settings = getattr(bot, "settings", None)

    async def _require_staff(self, interaction: discord.Interaction, *, require_pro: bool = True) -> bool:
        if not is_staff_user(
            interaction.user, self.settings, guild_id=getattr(interaction, "guild_id", None)
        ):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return False
        if require_pro:
            guild_id = getattr(interaction, "guild_id", None)
            if not isinstance(guild_id, int):
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return False
            try:
                entitlements_service.require_feature(
                    self.settings,
                    guild_id=guild_id,
                    feature_key=entitlements_service.FEATURE_TOURNAMENT_AUTOMATION,
                )
            except PermissionError:
                await interaction.response.send_message(
                    "Tournament automation is Pro-only for this server.",
                    ephemeral=True,
                )
                return False
        return True

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
        if not await self._require_staff(interaction):
            return
        matches_channel_id = None
        disputes_channel_id = None
        guild = interaction.guild
        safe_name = sanitize_text(name, max_length=60)
        safe_format = sanitize_text(format, max_length=40)
        safe_rules = sanitize_text(rules, max_length=400, allow_newlines=False) if rules else None
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
            format=safe_format,
            rules=safe_rules,
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
        if not await self._require_staff(interaction):
            return
        state = state.upper()
        if state not in {
            ts.TOURNAMENT_STATE_DRAFT,
            ts.TOURNAMENT_STATE_REG_OPEN,
            ts.TOURNAMENT_STATE_IN_PROGRESS,
            ts.TOURNAMENT_STATE_COMPLETED,
        }:
            await interaction.response.send_message("Invalid state.", ephemeral=True)
            return
        updated = ts.update_tournament_state(sanitize_text(name, max_length=60), state)
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
        if not await self._require_staff(interaction):
            return
        try:
            coach_int = int(coach_id.replace("<@", "").replace(">", "").replace("!", ""))
        except ValueError:
            await interaction.response.send_message("Invalid coach ID.", ephemeral=True)
            return
        try:
            participant = ts.add_participant(
                tournament_name=sanitize_text(tournament, max_length=60),
                team_name=sanitize_text(team_name, max_length=60),
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
        if not await self._require_staff(interaction):
            return
        try:
            safe_tournament = sanitize_text(tournament, max_length=60)
            matches = ts.generate_bracket(tournament_name=safe_tournament)
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        # Display with team names if available
        participants = ts.list_participants(safe_tournament)
        name_map = {p["_id"]: p["team_name"] for p in participants}
        lines = [
            f"R{m['round']} M{m['sequence']}: {name_map.get(m['team_a'], m['team_a'])}"
            f" vs {name_map.get(m.get('team_b'), m.get('team_b'))}"
            for m in matches
        ]
        embed = make_embed(
            title=f"Bracket published: {tournament}",
            description="\n".join(lines),
            color=SUCCESS_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="tournament_bracket_preview", description="Preview the first-round bracket without publishing."
    )
    async def tournament_bracket_preview(self, interaction: discord.Interaction, tournament: str) -> None:
        if not await self._require_staff(interaction):
            return
        try:
            preview = ts.preview_bracket(tournament_name=sanitize_text(tournament, max_length=60))
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        def _fmt(name: str | None, seed: int | None) -> str:
            if not name:
                return "BYE"
            return f"{name} (seed {seed})" if seed is not None else name

        lines = [
            f"R1 M{m['sequence']}: {_fmt(m['team_a'], m.get('team_a_seed'))}"
            f" vs {_fmt(m.get('team_b'), m.get('team_b_seed'))}"
            for m in preview
        ]
        embed = make_embed(
            title=f"Bracket preview: {tournament}",
            description="\n".join(lines),
            color=DEFAULT_COLOR,
            footer="No changes saved; rerun after edits or seeding adjustments.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
        if not await self._require_staff(interaction):
            return
        safe_tournament = sanitize_text(tournament, max_length=60)
        tour = ts.get_tournament(safe_tournament)
        if tour is None:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
        expected = tour.get("updated_at")
        try:
            reported = ts.report_score(
                tournament_name=safe_tournament,
                match_id=match_id,
                reporter_team_id=reporter_team_id,
                score_for=score_for,
                score_against=score_against,
                expected_updated_at=expected,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        matches_ch, _ = await self._get_channels(interaction, tour)
        if matches_ch:
            msg = await send_message(
                matches_ch,
                f"[{tournament}] Match {match_id} reported: {reporter_team_id} "
                f"{score_for}-{score_against} (status: {reported.get('status')})",
            )
            if msg:
                ts.set_match_message_id(match_id=match_id, field="match_message_id", message_id=msg.id)
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
        if not await self._require_staff(interaction):
            return
        safe_tournament = sanitize_text(tournament, max_length=60)
        tour = ts.get_tournament(safe_tournament)
        if tour is None:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
        expected = tour.get("updated_at")
        try:
            match = ts.confirm_match(
                tournament_name=safe_tournament,
                match_id=match_id,
                confirming_team_id=confirming_team_id,
                expected_updated_at=expected,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        matches_ch, _ = await self._get_channels(interaction, tour)
        if matches_ch:
            # Edit prior match message if recorded; otherwise post a new one.
            existing_msg_id = match.get("match_message_id")
            if existing_msg_id:
                try:
                    msg = await matches_ch.fetch_message(existing_msg_id)
                    await edit_message(
                        msg,
                        content=f"[{tournament}] Match {match_id} confirmed. Winner: {match.get('winner')}",
                    )
                except discord.DiscordException:
                    await send_message(
                        matches_ch,
                        f"[{tournament}] Match {match_id} confirmed. Winner: {match.get('winner')}",
                    )
            else:
                posted = await send_message(
                    matches_ch,
                    f"[{tournament}] Match {match_id} confirmed. Winner: {match.get('winner')}",
                )
                if posted:
                    ts.set_match_message_id(
                        match_id=match_id, field="match_message_id", message_id=posted.id
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
        if not await self._require_staff(interaction):
            return
        ok = ts.set_match_deadline(
            tournament_name=sanitize_text(tournament, max_length=60),
            match_id=match_id,
            deadline=sanitize_text(deadline, max_length=120),
        )
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
        if not await self._require_staff(interaction):
            return
        try:
            match = ts.forfeit_match(
                tournament_name=sanitize_text(tournament, max_length=60),
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
        if not await self._require_staff(interaction):
            return
        safe_tournament = sanitize_text(tournament, max_length=60)
        tour = ts.get_tournament(safe_tournament)
        if tour is None:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
        try:
            req = ts.request_reschedule(
                tournament_name=safe_tournament,
                match_id=match_id,
                reason=sanitize_text(reason, max_length=200),
                requested_by=interaction.user.id,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        matches_ch, disputes_ch = await self._get_channels(interaction, tour)
        target = disputes_ch or matches_ch
        if target:
            msg = await send_message(
                target,
                f"[{tournament}] Reschedule requested for match {match_id} by <@{interaction.user.id}>: {reason}",
            )
            if msg:
                ts.set_match_message_id(match_id=match_id, field="dispute_message_id", message_id=msg.id)
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
        if not await self._require_staff(interaction):
            return
        safe_tournament = sanitize_text(tournament, max_length=60)
        tour = ts.get_tournament(safe_tournament)
        if tour is None:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
        try:
            ts.add_dispute(
                tournament_name=safe_tournament,
                match_id=match_id,
                reason=sanitize_text(reason, max_length=200),
                filed_by=interaction.user.id,
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        _, disputes_ch = await self._get_channels(interaction, tour)
        if disputes_ch:
            msg = await send_message(
                disputes_ch,
                f"[{tournament}] Dispute filed on match {match_id} by <@{interaction.user.id}>: {reason}",
            )
            if msg:
                ts.set_match_message_id(match_id=match_id, field="dispute_message_id", message_id=msg.id)
        await interaction.response.send_message("Dispute recorded.", ephemeral=True)

    @app_commands.command(name="dispute_resolve", description="Resolve the latest dispute on a match")
    async def dispute_resolve(
        self,
        interaction: discord.Interaction,
        tournament: str,
        match_id: str,
        resolution: str,
    ) -> None:
        if not await self._require_staff(interaction):
            return
        safe_tournament = sanitize_text(tournament, max_length=60)
        tour = ts.get_tournament(safe_tournament)
        if tour is None:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
        try:
            match = ts.resolve_dispute(
                tournament_name=safe_tournament,
                match_id=match_id,
                resolution=sanitize_text(resolution, max_length=200),
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        _, disputes_ch = await self._get_channels(interaction, tour)
        if disputes_ch:
            existing_msg_id = match.get("dispute_message_id")
            if existing_msg_id:
                try:
                    msg = await disputes_ch.fetch_message(existing_msg_id)
                    await edit_message(
                        msg,
                        content=f"[{tournament}] Dispute resolved for match {match_id}: {resolution}",
                    )
                except discord.DiscordException:
                    await send_message(
                        disputes_ch,
                        f"[{tournament}] Dispute resolved for match {match_id}: {resolution}",
                    )
            else:
                await send_message(
                    disputes_ch,
                    f"[{tournament}] Dispute resolved for match {match_id}: {resolution}",
                )
        await interaction.response.send_message("Dispute resolved.", ephemeral=True)

    @app_commands.command(name="advance_round", description="Advance winners to the next round")
    async def advance_round(self, interaction: discord.Interaction, tournament: str) -> None:
        if not await self._require_staff(interaction):
            return
        try:
            safe_tournament = sanitize_text(tournament, max_length=60)
            matches = ts.advance_round(tournament_name=safe_tournament)
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        participants = ts.list_participants(safe_tournament)
        name_map = {p["_id"]: p["team_name"] for p in participants}
        lines = [
            f"R{m['round']} M{m['sequence']}: {name_map.get(m['team_a'], m['team_a'])}"
            f" vs {name_map.get(m.get('team_b'), m.get('team_b'))}"
            for m in matches
        ]
        round_label = matches[0]["round"] if matches else "next"
        embed = make_embed(
            title=f"Advanced to round {round_label}",
            description="\n".join(lines) if lines else "No new matches created.",
            color=WARNING_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="group_create", description="Create a group within a tournament")
    async def group_create(
        self,
        interaction: discord.Interaction,
        tournament: str,
        group_name: str,
    ) -> None:
        if not await self._require_staff(interaction):
            return
        try:
            gs.ensure_group(
                tournament_name=sanitize_text(tournament, max_length=60),
                group_name=sanitize_text(group_name, max_length=60),
            )
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
        if not await self._require_staff(interaction):
            return
        try:
            coach_int = int(coach_id.replace("<@", "").replace(">", "").replace("!", ""))
        except ValueError:
            await interaction.response.send_message("Invalid coach ID.", ephemeral=True)
            return
        try:
            gs.add_group_team(
                tournament_name=sanitize_text(tournament, max_length=60),
                group_name=sanitize_text(group_name, max_length=60),
                team_name=sanitize_text(team_name, max_length=60),
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
        if not await self._require_staff(interaction):
            return
        try:
            gs.record_group_match(
                tournament_name=sanitize_text(tournament, max_length=60),
                group_name=sanitize_text(group_name, max_length=60),
                team_a=sanitize_text(team_a, max_length=60),
                team_b=sanitize_text(team_b, max_length=60),
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
        if not await self._require_staff(interaction):
            return
        try:
            teams = gs.get_standings(
                tournament_name=sanitize_text(tournament, max_length=60),
                group_name=sanitize_text(group_name, max_length=60),
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
        if not await self._require_staff(interaction):
            return
        try:
            advanced = gs.advance_top(
                tournament_name=sanitize_text(tournament, max_length=60),
                group_name=sanitize_text(group_name, max_length=60),
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
        if not await self._require_staff(interaction):
            return
        try:
            fixtures = gs.generate_group_fixtures(
                tournament_name=sanitize_text(tournament, max_length=60),
                group_name=sanitize_text(group_name, max_length=60),
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

    @app_commands.command(name="tournament_dashboard", description="Show tournament command quick reference.")
    async def tournament_dashboard(self, interaction: discord.Interaction) -> None:
        if not await self._require_staff(interaction, require_pro=False):
            return
        embed = make_embed(
            title="Tournament Dashboard",
            description="Staff-only quick actions and references.",
            color=DEFAULT_COLOR,
        )
        embed.add_field(
            name="Setup",
            value="`/tournament_create`, `/tournament_state`, `/tournament_register`",
            inline=False,
        )
        embed.add_field(
            name="Bracket & Matches",
            value=(
                "`/tournament_bracket` (publish), `/tournament_bracket_preview` (dry-run), "
                "`/advance_round`, `/match_report`, `/match_confirm`, `/match_deadline`, `/match_forfeit`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Scheduling",
            value="`/match_reschedule`, `/dispute_add`, `/dispute_resolve`",
            inline=False,
        )
        embed.add_field(
            name="Groups",
            value="`/group_create`, `/group_register`, `/group_generate_fixtures`, `/group_match_report`, `/group_standings`, `/group_advance`",
            inline=False,
        )
        embed.add_field(
            name="Stats",
            value="`/tournament_stats` for wins/loss/GD leaderboard.",
            inline=False,
        )
        embed.set_footer(text="Responses are ephemeral to staff.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="tournament_stats", description="Show wins/losses and GD for a tournament.")
    async def tournament_stats(self, interaction: discord.Interaction, tournament: str) -> None:
        if not await self._require_staff(interaction):
            return
        leaderboard = stats_service.compute_leaderboard(sanitize_text(tournament, max_length=60))
        if not leaderboard:
            await interaction.response.send_message("No completed matches yet.", ephemeral=True)
            return
        lines = [
            f"{idx+1}. {row['team_name']} - W {row['wins']} / L {row['losses']} (GD {row['gd']})"
            for idx, row in enumerate(leaderboard)
        ]
        embed = make_embed(
            title=f"Leaderboard: {tournament}",
            description="\n".join(lines),
            color=DEFAULT_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentCog(bot))
