from __future__ import annotations

import logging
from typing import Any

import discord

from interactions.views import RosterDashboardView
from repositories.tournament_repo import (
    ensure_active_cycle,
    ensure_cycle_by_name,
    get_cycle_by_id,
)
from services.permission_service import resolve_roster_cap_for_guild
from services.roster_service import (
    count_roster_players,
    get_roster_for_coach,
    roster_is_locked,
)
from utils.embeds import DEFAULT_COLOR


def build_roster_dashboard(
    interaction: discord.Interaction,
    *,
    cycle_name: str | None = None,
    cycle_id: Any | None = None,
) -> tuple[discord.Embed, discord.ui.View]:
    settings = getattr(interaction.client, "settings", None)
    if settings is None:
        raise RuntimeError("Bot configuration is not loaded.")

    roles = getattr(interaction.user, "roles", [])
    role_ids = [role.id for role in roles]
    cap = resolve_roster_cap_for_guild(
        role_ids,
        settings=settings,
        guild_id=getattr(interaction.guild, "id", None),
    )

    normalized_cycle_name = cycle_name.strip() if cycle_name else None
    cycle = get_cycle_by_id(cycle_id) if cycle_id is not None else None
    if cycle is None:
        cycle = (
            ensure_active_cycle()
            if normalized_cycle_name is None
            else ensure_cycle_by_name(normalized_cycle_name)
        )

    roster = get_roster_for_coach(interaction.user.id, cycle_id=cycle["_id"])
    has_roster = roster is not None
    player_count = 0
    status = "NO_ROSTER"
    team_name = "No roster yet"
    is_locked = False

    if roster:
        player_count = count_roster_players(roster["_id"])
        status = roster.get("status", "UNKNOWN")
        team_name = roster.get("team_name", "Unnamed Team")
        is_locked = roster_is_locked(roster)

    embed = discord.Embed(
        title="Roster Dashboard",
        description=(
            "Use the buttons below to manage your roster.\n"
            "- Create or rename your roster\n"
            "- Add/remove players\n"
            "- Submit when ready (locks roster)"
        ),
        color=DEFAULT_COLOR,
    )
    embed.add_field(name="Tournament", value=cycle.get("name", "Unknown"), inline=False)
    embed.add_field(name="Team", value=team_name, inline=False)
    embed.add_field(name="Status", value=status, inline=True)

    if cap is None and not has_roster:
        logging.warning(
            "Roster eligibility failed for user %s roles=%s (expected: coach=%s, premium=%s, premium_plus=%s)",
            interaction.user.id if interaction.user else "unknown",
            role_ids,
            getattr(settings, "role_coach_id", None),
            settings.role_coach_premium_id,
            settings.role_coach_premium_plus_id,
        )
        embed.add_field(
            name="Eligibility",
            value="Not eligible for roster creation (missing coach role).",
            inline=False,
        )
    else:
        display_cap = cap if cap is not None else (roster.get("cap", "N/A") if roster else "N/A")
        embed.add_field(
            name="Players",
            value=f"{player_count}/{display_cap}",
            inline=True,
        )

    view = RosterDashboardView(
        has_roster=has_roster,
        roster_id=roster["_id"] if roster else None,
        has_players=player_count > 0,
        is_locked=is_locked,
        eligible=cap is not None,
        cycle_id=cycle["_id"],
    )

    return embed, view
