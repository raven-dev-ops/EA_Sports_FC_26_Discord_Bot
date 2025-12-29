from __future__ import annotations

from typing import Any

from pymongo.collection import Collection

from database import get_collection
from services.tournament_service import (
    MATCH_STATUS_COMPLETED,
    list_matches,
    list_participants,
)


def compute_leaderboard(
    tournament_name: str, *, collection: Collection | None = None
) -> list[dict[str, Any]]:
    """
    Build a simple leaderboard from completed matches (wins/losses/gd).
    """
    if collection is None:
        collection = get_collection()
    participants = list_participants(tournament_name, collection=collection)
    name_map = {p["_id"]: p["team_name"] for p in participants}
    table: dict[Any, dict[str, Any]] = {}
    matches = list_matches(tournament_name, collection=collection)
    for m in matches:
        if m.get("status") != MATCH_STATUS_COMPLETED:
            continue
        a = m.get("team_a")
        b = m.get("team_b")
        scores = m.get("scores", {})
        if not scores:
            continue
        # Choose first score entry as reporter; infer other team score
        reporter_score = next(iter(scores.values()))
        score_a = reporter_score.get("for", 0)
        score_b = reporter_score.get("against", 0)
        for team in (a, b):
            if team not in table:
                table[team] = {"team_name": name_map.get(team, str(team)), "wins": 0, "losses": 0, "gd": 0}
        if score_a > score_b:
            table[a]["wins"] += 1
            table[b]["losses"] += 1
        elif score_b > score_a:
            table[b]["wins"] += 1
            table[a]["losses"] += 1
        table[a]["gd"] += score_a - score_b
        table[b]["gd"] += score_b - score_a
    return sorted(table.values(), key=lambda t: (-t["wins"], -t["gd"], t["team_name"]))
