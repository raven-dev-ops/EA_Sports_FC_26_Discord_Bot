from __future__ import annotations

from typing import Any

import discord

from interactions.modals import CreateRosterModal


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
        await interaction.response.send_message(
            "Add player is not configured yet.", ephemeral=True
        )

    async def on_remove_player(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Remove player is not configured yet.", ephemeral=True
        )

    async def on_view_roster(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "View roster is not configured yet.", ephemeral=True
        )

    async def on_submit_roster(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Submit roster is not configured yet.", ephemeral=True
        )
