from __future__ import annotations

from typing import Any

import discord

from interactions.modals import (
    AddPlayerModal,
    CreateRosterModal,
    RemovePlayerModal,
    RenameRosterModal,
)
from services.audit_service import (
    AUDIT_ACTION_APPROVED,
    AUDIT_ACTION_REJECTED,
    record_staff_action,
)
from services.recruitment_service import list_recruit_profile_distinct, search_recruit_profiles
from services.roster_service import (
    ROSTER_STATUS_APPROVED,
    ROSTER_STATUS_REJECTED,
    ROSTER_STATUS_SUBMITTED,
    ROSTER_STATUS_UNLOCKED,
    count_roster_players,
    get_roster_by_id,
    get_roster_players,
    roster_is_locked,
    set_roster_status,
    validate_roster_identity,
)
from services.submission_service import (
    create_submission_record,
    delete_submission_by_roster,
    get_submission_by_roster,
    update_submission_status,
)
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import delete_message, fetch_channel, send_message
from utils.errors import log_interaction_error, send_interaction_error
from utils.formatting import format_roster_line, format_submission_message


class SafeView(discord.ui.View):
    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        log_interaction_error(error, interaction, source="view")
        await send_interaction_error(interaction)

    async def on_timeout(self) -> None:
        self.disable_items()
        message = getattr(self, "message", None)
        if message is None:
            return
        try:
            await message.edit(view=self)
        except discord.DiscordException:
            pass

    def disable_items(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True


class RosterDashboardView(SafeView):
    def __init__(
        self,
        *,
        has_roster: bool,
        roster_id: Any | None,
        has_players: bool,
        is_locked: bool,
        eligible: bool,
        cycle_id: Any | None,
    ) -> None:
        super().__init__(timeout=300)
        self.has_roster = has_roster
        self.roster_id = roster_id
        self.has_players = has_players
        self.is_locked = is_locked
        self.eligible = eligible
        self.cycle_id = cycle_id

        create_button: discord.ui.Button = discord.ui.Button(
            label="Create Roster",
            style=discord.ButtonStyle.primary,
            disabled=has_roster or not eligible,
        )
        setattr(create_button, "callback", self.on_create_roster)
        self.add_item(create_button)

        add_button: discord.ui.Button = discord.ui.Button(
            label="Manual Add",
            style=discord.ButtonStyle.success,
            disabled=not has_roster or is_locked,
        )
        setattr(add_button, "callback", self.on_add_player)
        self.add_item(add_button)

        add_pool_button: discord.ui.Button = discord.ui.Button(
            label="Add From Player Pool",
            style=discord.ButtonStyle.primary,
            disabled=not has_roster or is_locked,
        )
        setattr(add_pool_button, "callback", self.on_add_player_from_pool)
        self.add_item(add_pool_button)

        remove_button: discord.ui.Button = discord.ui.Button(
            label="Remove Player",
            style=discord.ButtonStyle.secondary,
            disabled=not has_roster or not has_players or is_locked,
        )
        setattr(remove_button, "callback", self.on_remove_player)
        self.add_item(remove_button)

        view_button: discord.ui.Button = discord.ui.Button(
            label="View Roster",
            style=discord.ButtonStyle.secondary,
            disabled=not has_roster,
        )
        setattr(view_button, "callback", self.on_view_roster)
        self.add_item(view_button)

        submit_button: discord.ui.Button = discord.ui.Button(
            label="Submit Roster",
            style=discord.ButtonStyle.danger,
            disabled=not has_roster or is_locked,
        )
        setattr(submit_button, "callback", self.on_submit_roster)
        self.add_item(submit_button)

        rename_button: discord.ui.Button = discord.ui.Button(
            label="Edit Team Name",
            style=discord.ButtonStyle.secondary,
            disabled=not has_roster or is_locked,
        )
        setattr(rename_button, "callback", self.on_rename_team)
        self.add_item(rename_button)

    async def on_create_roster(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CreateRosterModal(cycle_id=self.cycle_id))

    async def on_add_player(self, interaction: discord.Interaction) -> None:
        if self.roster_id is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(AddPlayerModal(roster_id=self.roster_id))

    async def on_add_player_from_pool(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This action must be used in a guild.",
                ephemeral=True,
            )
            return
        if self.roster_id is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return
        roster = get_roster_by_id(self.roster_id)
        if roster is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return
        if roster_is_locked(roster):
            await interaction.response.send_message(
                "This roster is locked and cannot be edited.",
                ephemeral=True,
            )
            return
        view = RosterPlayerSearchView(
            guild_id=guild.id,
            roster_id=self.roster_id,
        )
        await interaction.response.send_message(
            embed=view.build_embed(),
            view=view,
            ephemeral=True,
        )

    async def on_remove_player(self, interaction: discord.Interaction) -> None:
        if self.roster_id is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(RemovePlayerModal(roster_id=self.roster_id))

    async def on_view_roster(self, interaction: discord.Interaction) -> None:
        if self.roster_id is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return

        roster = get_roster_by_id(self.roster_id)
        if roster is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return

        players = get_roster_players(self.roster_id)
        lines = [
            f"{idx}. "
            + format_roster_line(
                discord_mention=f"<@{player['player_discord_id']}>",
                gamertag=player.get("gamertag", ""),
                ea_id=player.get("ea_id", ""),
                console=player.get("console", ""),
            )
            for idx, player in enumerate(players, start=1)
        ]

        embed = discord.Embed(title="Roster Preview")
        status = roster.get("status", "UNKNOWN")
        if roster_is_locked(roster):
            status = f"{status} (LOCKED)"

        embed.add_field(name="Team", value=roster.get("team_name", "Unnamed Team"), inline=False)
        embed.add_field(
            name="Status",
            value=status,
            inline=True,
        )
        embed.add_field(
            name="Players",
            value=f"{len(players)}/{roster.get('cap', 'N/A')}",
            inline=True,
        )
        embed.description = "\n".join(lines) if lines else "No players added."

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_submit_roster(self, interaction: discord.Interaction) -> None:
        if self.roster_id is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Submit roster for staff review?",
            view=SubmitRosterConfirmView(roster_id=self.roster_id),
            ephemeral=True,
        )

    async def on_rename_team(self, interaction: discord.Interaction) -> None:
        if self.roster_id is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(RenameRosterModal(roster_id=self.roster_id))


class RosterPlayerSearchView(SafeView):
    def __init__(
        self,
        *,
        guild_id: int,
        roster_id: Any,
    ) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.roster_id = roster_id
        self.page = 0
        self.page_size = 25
        self.position: str | None = None
        self.archetype: str | None = None
        self.server_name: str | None = None
        self._has_next = False
        self._results: list[dict[str, Any]] = []

        positions = _union_distinct(
            guild_id,
            ("main_position", "secondary_position"),
            limit=24,
        )
        archetypes = _union_distinct(
            guild_id,
            ("main_archetype", "secondary_archetype"),
            limit=24,
        )
        servers = list_recruit_profile_distinct(guild_id, "server_name", limit=24)

        self.position_select: discord.ui.Select = discord.ui.Select(
            placeholder="Position (any)",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="Any", value="__any__", default=True)]
            + [discord.SelectOption(label=p, value=p) for p in positions],
        )
        self.position_select.callback = self._on_position_change  # type: ignore[assignment]
        self.add_item(self.position_select)

        self.archetype_select: discord.ui.Select = discord.ui.Select(
            placeholder="Archetype (any)",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="Any", value="__any__", default=True)]
            + [discord.SelectOption(label=a.title()[:100], value=a) for a in archetypes],
        )
        self.archetype_select.callback = self._on_archetype_change  # type: ignore[assignment]
        self.add_item(self.archetype_select)

        self.server_select: discord.ui.Select = discord.ui.Select(
            placeholder="Server (any)",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="Any", value="__any__", default=True)]
            + [discord.SelectOption(label=s[:100], value=s) for s in servers],
        )
        self.server_select.callback = self._on_server_change  # type: ignore[assignment]
        self.add_item(self.server_select)

        self.results_select: discord.ui.Select = discord.ui.Select(
            placeholder="Select a player",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="No results yet", value="__none__")],
            disabled=True,
        )
        self.results_select.callback = self._on_select_player  # type: ignore[assignment]
        self.add_item(self.results_select)

        prev_btn: discord.ui.Button = discord.ui.Button(label="Prev", style=discord.ButtonStyle.secondary)
        setattr(prev_btn, "callback", self._on_prev)
        self.add_item(prev_btn)

        next_btn: discord.ui.Button = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary)
        setattr(next_btn, "callback", self._on_next)
        self.add_item(next_btn)

        refresh_btn: discord.ui.Button = discord.ui.Button(label="Refresh", style=discord.ButtonStyle.primary)
        setattr(refresh_btn, "callback", self._on_refresh)
        self.add_item(refresh_btn)

        self._refresh_results()

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Add From Player Pool",
            description="Filter by position/archetype/server, then select a player to add.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Filters",
            value=(
                f"Position: {self.position or 'Any'}\n"
                f"Archetype: {self.archetype or 'Any'}\n"
                f"Server: {self.server_name or 'Any'}"
            ),
            inline=False,
        )
        embed.add_field(
            name="Results",
            value=f"Showing {len(self._results)} result(s) (page {self.page + 1}).",
            inline=False,
        )
        return embed

    async def _on_position_change(self, interaction: discord.Interaction) -> None:
        value = self.position_select.values[0]
        self.position = None if value == "__any__" else value
        self.page = 0
        self._refresh_results()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_archetype_change(self, interaction: discord.Interaction) -> None:
        value = self.archetype_select.values[0]
        self.archetype = None if value == "__any__" else value
        self.page = 0
        self._refresh_results()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_server_change(self, interaction: discord.Interaction) -> None:
        value = self.server_select.values[0]
        self.server_name = None if value == "__any__" else value
        self.page = 0
        self._refresh_results()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_select_player(self, interaction: discord.Interaction) -> None:
        value = self.results_select.values[0]
        if value == "__none__":
            await interaction.response.send_message("No player selected.", ephemeral=True)
            return
        try:
            player_id = int(value)
        except ValueError:
            await interaction.response.send_message("Invalid player selection.", ephemeral=True)
            return
        await interaction.response.send_modal(
            AddPlayerModal(roster_id=self.roster_id, player_discord_id=player_id)
        )

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if self.page <= 0:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
            return
        self.page -= 1
        self._refresh_results()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if not self._has_next:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
            return
        self.page += 1
        self._refresh_results()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_refresh(self, interaction: discord.Interaction) -> None:
        self._refresh_results()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _refresh_results(self) -> None:
        limit = self.page_size + 1
        offset = self.page * self.page_size
        results = search_recruit_profiles(
            self.guild_id,
            position=self.position,
            archetype=self.archetype,
            server_name=self.server_name,
            limit=limit,
            offset=offset,
        )
        self._has_next = len(results) > self.page_size
        self._results = results[: self.page_size]

        if not self._results:
            self.results_select.options = [discord.SelectOption(label="No matches", value="__none__")]
            self.results_select.disabled = True
        else:
            options: list[discord.SelectOption] = []
            for profile in self._results:
                user_id = profile.get("user_id")
                if not isinstance(user_id, int):
                    continue
                display = (
                    str(profile.get("display_name") or "").strip()
                    or str(profile.get("user_tag") or "").strip()
                    or str(user_id)
                )
                pos = str(profile.get("main_position") or "?")
                arch = str(profile.get("main_archetype") or "").title()
                server = str(profile.get("server_name") or "")
                label = f"{display} - {pos} ({arch}) - {server}".strip(" -")
                options.append(
                    discord.SelectOption(
                        label=label[:100],
                        value=str(user_id),
                    )
                )
            self.results_select.options = options[:25] if options else [
                discord.SelectOption(label="No matches", value="__none__")
            ]
            self.results_select.disabled = not bool(options)

        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Prev":
                child.disabled = self.page <= 0
            if isinstance(child, discord.ui.Button) and child.label == "Next":
                child.disabled = not self._has_next


def _union_distinct(guild_id: int, fields: tuple[str, ...], *, limit: int) -> list[str]:
    values: set[str] = set()
    for field in fields:
        for v in list_recruit_profile_distinct(guild_id, field, limit=limit * 2):
            values.add(v)
    sorted_values = sorted(values, key=lambda v: v.casefold())
    return sorted_values[: max(0, int(limit))]


class SubmitRosterConfirmView(SafeView):
    def __init__(self, *, roster_id: Any) -> None:
        super().__init__(timeout=120)
        self.roster_id = roster_id

        confirm_button: discord.ui.Button = discord.ui.Button(
            label="Confirm Submit", style=discord.ButtonStyle.danger
        )
        setattr(confirm_button, "callback", self.on_confirm)
        self.add_item(confirm_button)

        cancel_button: discord.ui.Button = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.secondary
        )
        setattr(cancel_button, "callback", self.on_cancel)
        self.add_item(cancel_button)

    async def on_confirm(self, interaction: discord.Interaction) -> None:
        roster = get_roster_by_id(self.roster_id)
        if roster is None:
            await interaction.response.edit_message(
                content="Roster not found.", view=None
            )
            return

        if roster_is_locked(roster):
            await interaction.response.edit_message(
                content="This roster is locked and cannot be submitted.",
                view=None,
            )
            return

        existing_submission = get_submission_by_roster(self.roster_id)
        if existing_submission:
            if roster.get("status") == ROSTER_STATUS_UNLOCKED:
                # Clean up stale submission so the unlocked roster can be resubmitted.
                removed = delete_submission_by_roster(self.roster_id)
                if removed:
                    channel_id = removed.get("staff_channel_id")
                    message_id = removed.get("staff_message_id")
                    if isinstance(channel_id, int) and isinstance(message_id, int):
                        channel = await fetch_channel(interaction.client, channel_id)
                        if channel:
                            try:
                                msg = await channel.fetch_message(message_id)
                                await msg.delete()
                            except discord.DiscordException:
                                pass
            else:
                await interaction.response.edit_message(
                    content="Roster is already submitted.", view=None
                )
                return

        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.edit_message(
                content="Bot configuration is not loaded.", view=None
            )
            return

        test_mode = bool(getattr(interaction.client, "test_mode", False))
        staff_channel_id = resolve_channel_id(
            settings,
            guild_id=getattr(interaction.guild, "id", None),
            field="channel_staff_portal_id",
            test_mode=test_mode,
        )
        if not staff_channel_id:
            await interaction.response.edit_message(
                content="Staff channel is not configured. Ask staff to run `/setup_channels`.",
                view=None,
            )
            return
        channel = await fetch_channel(interaction.client, staff_channel_id)
        if channel is None:
            await interaction.response.edit_message(
                content="Staff channel not found.", view=None
            )
            return

        players = get_roster_players(self.roster_id)
        ok, reason = validate_roster_identity(self.roster_id)
        if not ok:
            await interaction.response.edit_message(
                content=reason,
                view=None,
            )
            return
        roster_lines = [
            format_roster_line(
                discord_mention=f"<@{player['player_discord_id']}>",
                gamertag=player.get("gamertag", ""),
                ea_id=player.get("ea_id", ""),
                console=player.get("console", ""),
            )
            for player in players
        ]

        count = count_roster_players(self.roster_id)
        cap = int(roster.get("cap", 0))
        status_text = "Pending"

        message_content = format_submission_message(
            team_name=roster.get("team_name", "Unnamed Team"),
            coach_mention=f"<@{roster.get('coach_discord_id')}>",
            roster_count=count,
            cap=cap,
            roster_lines=roster_lines,
            status_text=status_text,
        )

        staff_message = await send_message(
            channel, message_content, view=StaffReviewView(roster_id=self.roster_id)
        )
        if staff_message is None:
            await interaction.response.edit_message(
                content="Failed to send submission to staff channel.", view=None
            )
            return

        create_submission_record(
            roster_id=self.roster_id,
            staff_channel_id=staff_channel_id,
            staff_message_id=staff_message.id,
            status=status_text.upper(),
        )
        set_roster_status(
            self.roster_id,
            ROSTER_STATUS_SUBMITTED,
            expected_updated_at=roster.get("updated_at"),
        )

        await interaction.response.edit_message(
            content="Roster submitted for staff review.", view=None
        )

    async def on_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Submission canceled.", view=None)


class StaffReviewView(SafeView):
    def __init__(self, *, roster_id: Any) -> None:
        super().__init__(timeout=86400)
        self.roster_id = roster_id

        approve_button: discord.ui.Button = discord.ui.Button(
            label="Approve", style=discord.ButtonStyle.success
        )
        setattr(approve_button, "callback", self.on_approve)
        self.add_item(approve_button)

        reject_button: discord.ui.Button = discord.ui.Button(
            label="Reject", style=discord.ButtonStyle.danger
        )
        setattr(reject_button, "callback", self.on_reject)
        self.add_item(reject_button)

    async def on_approve(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            StaffDecisionModal(roster_id=self.roster_id, approved=True)
        )

    async def on_reject(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            StaffDecisionModal(roster_id=self.roster_id, approved=False)
        )

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            return False
        role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
        if settings.staff_role_ids:
            return bool(role_ids.intersection(settings.staff_role_ids))
        perms = getattr(interaction.user, "guild_permissions", None)
        return bool(getattr(perms, "manage_guild", False))

    async def _handle_decision(
        self,
        interaction: discord.Interaction,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> None:
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You do not have permission to review this roster.",
                ephemeral=True,
            )
            return

        roster = get_roster_by_id(self.roster_id)
        if roster is None:
            await interaction.response.send_message(
                "Roster not found.", ephemeral=True
            )
            return

        players = get_roster_players(self.roster_id)
        roster_lines = [
            format_roster_line(
                discord_mention=f"<@{player['player_discord_id']}>",
                gamertag=player.get("gamertag", ""),
                ea_id=player.get("ea_id", ""),
                console=player.get("console", ""),
            )
            for player in players
        ]

        count = len(players)
        cap = int(roster.get("cap", 0))
        status_text = "Approved" if approved else "Rejected"
        roster_status = ROSTER_STATUS_APPROVED if approved else ROSTER_STATUS_REJECTED

        message_content = format_submission_message(
            team_name=roster.get("team_name", "Unnamed Team"),
            coach_mention=f"<@{roster.get('coach_discord_id')}>",
            roster_count=count,
            cap=cap,
            roster_lines=roster_lines,
            status_text=status_text,
        )
        if reason:
            message_content += f"\nReason: {reason}"

        update_submission_status(
            roster_id=self.roster_id,
            status=status_text.upper(),
        )
        set_roster_status(
            self.roster_id,
            roster_status,
            expected_updated_at=roster.get("updated_at"),
        )
        record_staff_action(
            roster_id=self.roster_id,
            action=AUDIT_ACTION_APPROVED if approved else AUDIT_ACTION_REJECTED,
            staff_discord_id=interaction.user.id,
            staff_display_name=getattr(interaction.user, "display_name", None),
            staff_username=str(interaction.user),
        )

        self.disable_items()
        await interaction.response.send_message(
            f"Roster {status_text.lower()}.", ephemeral=True
        )

        submission = get_submission_by_roster(self.roster_id)
        staff_channel: discord.abc.Messageable | None = None
        staff_channel_id: int | None = None
        staff_message_id: int | None = None
        if submission:
            raw_channel_id = submission.get("staff_channel_id")
            raw_message_id = submission.get("staff_message_id")
            staff_channel_id = raw_channel_id if isinstance(raw_channel_id, int) else None
            staff_message_id = raw_message_id if isinstance(raw_message_id, int) else None
            if staff_channel_id is not None:
                staff_channel = await fetch_channel(interaction.client, staff_channel_id)
            if staff_channel and staff_message_id is not None:
                try:
                    message = await staff_channel.fetch_message(staff_message_id)
                    await message.edit(content=message_content, view=None)
                except discord.DiscordException:
                    pass
            update_submission_status(
                roster_id=self.roster_id, status=status_text.upper()
            )

        if approved:
            settings = getattr(interaction.client, "settings", None)
            if settings:
                test_mode = bool(getattr(interaction.client, "test_mode", False))
                roster_channel_id = resolve_channel_id(
                    settings,
                    guild_id=getattr(interaction.guild, "id", None),
                    field="channel_roster_listing_id",
                    test_mode=test_mode,
                )
                if not roster_channel_id:
                    await interaction.followup.send(
                        "Roster was approved, but the roster listing channel is not configured. "
                        "Ask staff to run `/setup_channels`.",
                        ephemeral=True,
                    )
                    return
                roster_channel = await fetch_channel(interaction.client, roster_channel_id)
                if roster_channel:
                    await send_message(roster_channel, message_content)

        if reason:
            try:
                coach_id = roster.get("coach_discord_id")
                if isinstance(coach_id, int):
                    user = await interaction.client.fetch_user(coach_id)
                    await user.send(
                        f"Your roster was {status_text.lower()}.\n"
                        f"Team: {roster.get('team_name', 'Unnamed Team')}\n"
                        f"Reason: {reason}"
                    )
            except Exception:
                pass

        # Clean up the staff portal message after a decision to avoid duplicates.
        if staff_channel and staff_message_id is not None:
            try:
                msg = await staff_channel.fetch_message(staff_message_id)
                await delete_message(msg)
            except discord.DiscordException:
                pass


class StaffDecisionModal(discord.ui.Modal, title="Decision"):
    reason: discord.ui.TextInput = discord.ui.TextInput(
        label="Reason (optional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(self, *, roster_id: Any, approved: bool) -> None:
        super().__init__()
        self.roster_id = roster_id
        self.approved = approved
        if not approved:
            self.reason.required = True
            self.reason.label = "Reason (required for rejection)"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        parent = StaffReviewView(roster_id=self.roster_id)
        await parent._handle_decision(
            interaction, approved=self.approved, reason=self.reason.value.strip() or None
        )
