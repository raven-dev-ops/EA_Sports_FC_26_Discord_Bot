from __future__ import annotations

from typing import Any

import discord

from interactions.modals import AddPlayerModal, CreateRosterModal, RemovePlayerModal
from services.roster_service import get_roster_by_id, get_roster_players, roster_is_locked
from utils.formatting import format_roster_line


class RosterDashboardView(discord.ui.View):
    def __init__(
        self,
        *,
        has_roster: bool,
        roster_id: Any | None,
        has_players: bool,
        is_locked: bool,
        eligible: bool,
    ) -> None:
        super().__init__(timeout=300)
        self.has_roster = has_roster
        self.roster_id = roster_id
        self.has_players = has_players
        self.is_locked = is_locked
        self.eligible = eligible

        create_button = discord.ui.Button(
            label="Create Roster",
            style=discord.ButtonStyle.primary,
            disabled=has_roster or not eligible,
        )
        create_button.callback = self.on_create_roster
        self.add_item(create_button)

        add_button = discord.ui.Button(
            label="Add Player",
            style=discord.ButtonStyle.success,
            disabled=not has_roster or is_locked,
        )
        add_button.callback = self.on_add_player
        self.add_item(add_button)

        remove_button = discord.ui.Button(
            label="Remove Player",
            style=discord.ButtonStyle.secondary,
            disabled=not has_roster or not has_players or is_locked,
        )
        remove_button.callback = self.on_remove_player
        self.add_item(remove_button)

        view_button = discord.ui.Button(
            label="View Roster",
            style=discord.ButtonStyle.secondary,
            disabled=not has_roster,
        )
        view_button.callback = self.on_view_roster
        self.add_item(view_button)

        submit_button = discord.ui.Button(
            label="Submit Roster",
            style=discord.ButtonStyle.danger,
            disabled=not has_roster or is_locked,
        )
        submit_button.callback = self.on_submit_roster
        self.add_item(submit_button)

    async def on_create_roster(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CreateRosterModal())

    async def on_add_player(self, interaction: discord.Interaction) -> None:
        if self.roster_id is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(AddPlayerModal(roster_id=self.roster_id))

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
        await interaction.response.send_message(
            "Submit roster is not configured yet.", ephemeral=True
        )
