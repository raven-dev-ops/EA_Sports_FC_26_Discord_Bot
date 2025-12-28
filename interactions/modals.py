from __future__ import annotations

from typing import Any

import discord

from interactions.dashboard import build_roster_dashboard
from services.permission_service import resolve_roster_cap_from_settings
from services.roster_service import (
    add_player,
    count_roster_players,
    create_roster,
    get_roster_by_id,
    get_roster_for_coach,
    remove_player,
    roster_is_locked,
)
from utils.validation import normalize_console, parse_discord_id, validate_team_name
from utils.errors import log_interaction_error, send_interaction_error


class SafeModal(discord.ui.Modal):
    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        log_interaction_error(error, interaction, source="modal")
        await send_interaction_error(interaction)


class CreateRosterModal(SafeModal, title="Create Roster"):
    team_name = discord.ui.TextInput(
        label="Team Name",
        min_length=2,
        max_length=32,
        placeholder="Enter your team name",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.", ephemeral=True
            )
            return

        roles = getattr(interaction.user, "roles", [])
        role_ids = [role.id for role in roles]
        cap = resolve_roster_cap_from_settings(role_ids, settings)
        if cap is None:
            await interaction.response.send_message(
                "You are not eligible to create a roster.", ephemeral=True
            )
            return

        name = self.team_name.value.strip()
        if not validate_team_name(name):
            await interaction.response.send_message(
                "Team name must be 2-32 characters using letters, numbers, spaces, '-' or '_'.",
                ephemeral=True,
            )
            return

        existing = get_roster_for_coach(interaction.user.id)
        if existing:
            embed, view = build_roster_dashboard(interaction)
            await interaction.response.send_message(
                "Roster already exists.", embed=embed, view=view, ephemeral=True
            )
            return

        create_roster(
            coach_discord_id=interaction.user.id,
            team_name=name,
            cap=cap,
        )

        embed, view = build_roster_dashboard(interaction)
        await interaction.response.send_message(
            "Roster created.", embed=embed, view=view, ephemeral=True
        )


class AddPlayerModal(SafeModal, title="Add Player"):
    def __init__(self, *, roster_id: Any) -> None:
        super().__init__()
        self.roster_id = roster_id

    discord_id = discord.ui.TextInput(
        label="Player Discord ID or mention",
        placeholder="@Player or 1234567890",
    )
    gamertag = discord.ui.TextInput(label="Gamertag or PSN")
    ea_id = discord.ui.TextInput(label="EA ID")
    console = discord.ui.TextInput(label="Console (PS, XBOX, PC, SWITCH)")

    async def on_submit(self, interaction: discord.Interaction) -> None:
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

        player_id = parse_discord_id(self.discord_id.value)
        if player_id is None:
            await interaction.response.send_message(
                "Enter a valid Discord mention or ID for the player.",
                ephemeral=True,
            )
            return

        console_value = normalize_console(self.console.value)
        if console_value is None:
            await interaction.response.send_message(
                "Console must be one of: PS, XBOX, PC, SWITCH.",
                ephemeral=True,
            )
            return

        try:
            add_player(
                roster_id=self.roster_id,
                player_discord_id=player_id,
                gamertag=self.gamertag.value.strip(),
                ea_id=self.ea_id.value.strip(),
                console=console_value,
                cap=int(roster.get("cap", 0)),
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        count = count_roster_players(self.roster_id)
        cap = roster.get("cap", "N/A")
        await interaction.response.send_message(
            f"Player added. Roster now {count}/{cap}.",
            ephemeral=True,
        )


class RemovePlayerModal(SafeModal, title="Remove Player"):
    def __init__(self, *, roster_id: Any) -> None:
        super().__init__()
        self.roster_id = roster_id

    discord_id = discord.ui.TextInput(
        label="Player Discord ID or mention",
        placeholder="@Player or 1234567890",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
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

        player_id = parse_discord_id(self.discord_id.value)
        if player_id is None:
            await interaction.response.send_message(
                "Enter a valid Discord mention or ID for the player.",
                ephemeral=True,
            )
            return

        removed = remove_player(
            roster_id=self.roster_id,
            player_discord_id=player_id,
        )
        if not removed:
            await interaction.response.send_message(
                "Player not found on this roster.",
                ephemeral=True,
            )
            return

        count = count_roster_players(self.roster_id)
        cap = roster.get("cap", "N/A")
        await interaction.response.send_message(
            f"Player removed. Roster now {count}/{cap}.",
            ephemeral=True,
        )
