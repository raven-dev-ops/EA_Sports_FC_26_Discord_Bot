from __future__ import annotations

import discord

from interactions.dashboard import build_roster_dashboard
from services.permission_service import resolve_roster_cap_from_settings
from services.roster_service import create_roster, get_roster_for_coach
from utils.validation import validate_team_name


class CreateRosterModal(discord.ui.Modal, title="Create Roster"):
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
