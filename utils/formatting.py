from __future__ import annotations

from typing import Iterable


def format_roster_line(
    *,
    discord_mention: str,
    gamertag: str,
    ea_id: str,
    console: str,
) -> str:
    return f"{discord_mention} / {gamertag} / {ea_id} / {console}"


def format_roster_lines(lines: Iterable[str]) -> str:
    return "\n".join(lines) if lines else "No players added."


def format_submission_message(
    *,
    team_name: str,
    coach_mention: str,
    roster_count: int,
    cap: int,
    roster_lines: Iterable[str],
    status_text: str,
) -> str:
    lines = format_roster_lines(roster_lines)
    return (
        "New Roster Submission\n"
        f"Team: {team_name}\n"
        f"Coach: {coach_mention}\n"
        f"Roster ({roster_count}/{cap}):\n"
        f"{lines}\n"
        f"Status: {status_text} (Players: {roster_count}/{cap})"
    )
