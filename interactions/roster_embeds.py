from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

from repositories.tournament_repo import get_cycle_by_id
from utils.embeds import DEFAULT_COLOR, SUCCESS_COLOR, apply_embed_footer, make_embed


def build_roster_listing_embed(
    roster: dict[str, Any],
    players: list[dict[str, Any]],
    *,
    approved: bool,
    reason: str | None = None,
) -> discord.Embed:
    team_name = str(roster.get("team_name") or "Unnamed Team").strip() or "Unnamed Team"
    coach_id = roster.get("coach_discord_id")
    cap = roster.get("cap")
    cap_value = int(cap) if isinstance(cap, int) else None
    player_count = len(players)
    openings = cap_value - player_count if isinstance(cap_value, int) else None
    practice_times = str(roster.get("practice_times") or "").strip() or "Not set"

    cycle_name = None
    cycle_id = roster.get("cycle_id")
    if cycle_id is not None:
        cycle = get_cycle_by_id(cycle_id)
        if cycle:
            cycle_name = str(cycle.get("name") or "").strip() or None

    status = "Approved" if approved else "Rejected"
    embed = make_embed(
        title=f"Roster {status}: {team_name}",
        description=(f"Coach: <@{coach_id}>" if coach_id else None),
        color=SUCCESS_COLOR if approved else DEFAULT_COLOR,
    )

    if cycle_name:
        embed.add_field(name="Tournament", value=cycle_name, inline=False)

    if cap_value is not None:
        embed.add_field(
            name="Players",
            value=f"{player_count}/{cap_value}" + (f" (Openings: {openings})" if openings is not None else ""),
            inline=True,
        )
    else:
        embed.add_field(name="Players", value=str(player_count), inline=True)

    embed.add_field(name="Practice Times", value=practice_times[:1024], inline=False)

    if reason:
        embed.add_field(name="Reason", value=reason[:1024], inline=False)

    lines = []
    for idx, player in enumerate(players, start=1):
        mention = f"<@{player.get('player_discord_id')}>"
        gamertag = str(player.get("gamertag") or "").strip()
        ea_id = str(player.get("ea_id") or "").strip()
        console = str(player.get("console") or "").strip()
        details = " / ".join(part for part in (mention, gamertag, ea_id, console) if part)
        lines.append(f"{idx}. {details}")

    if lines:
        for idx, chunk in enumerate(_chunk_lines(lines, max_len=1024)):
            embed.add_field(
                name="Roster" if idx == 0 else "Roster (cont.)",
                value=chunk,
                inline=False,
            )
            if idx >= 20:
                break
    else:
        embed.add_field(name="Roster", value="No players listed.", inline=False)

    updated_at = roster.get("updated_at") or roster.get("created_at")
    if isinstance(updated_at, datetime):
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        apply_embed_footer(embed, f"Updated: {discord.utils.format_dt(updated_at, style='R')}")

    return embed


def _chunk_lines(lines: list[str], *, max_len: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for line in lines:
        line_len = len(line) + (1 if current else 0)
        if current and length + line_len > max_len:
            chunks.append("\n".join(current))
            current = []
            length = 0
        if len(line) > max_len:
            chunks.append(line[: max_len - 3] + "...")
            continue
        current.append(line)
        length += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks

