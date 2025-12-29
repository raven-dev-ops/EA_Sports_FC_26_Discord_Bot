from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection
from services import tournament_service as ts


def _now():
    return datetime.now(timezone.utc)


def ensure_group(
    *,
    tournament_name: str,
    group_name: str,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    tour = ts.get_tournament(tournament_name, collection=collection)
    if tour is None:
        raise RuntimeError("Tournament not found.")
    existing = collection.find_one(
        {
            "record_type": "tournament_group",
            "tournament": tour["_id"],
            "name": group_name,
        }
    )
    if existing:
        return existing
    now = _now()
    doc = {
        "record_type": "tournament_group",
        "tournament": tour["_id"],
        "name": group_name,
        "created_at": now,
        "updated_at": now,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def add_group_team(
    *,
    tournament_name: str,
    group_name: str,
    team_name: str,
    coach_id: int,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    group = ensure_group(
        tournament_name=tournament_name,
        group_name=group_name,
        collection=collection,
    )
    existing = collection.find_one(
        {
            "record_type": "group_team",
            "group_id": group["_id"],
            "team_name": team_name,
        }
    )
    if existing:
        return existing
    now = _now()
    doc = {
        "record_type": "group_team",
        "group_id": group["_id"],
        "tournament": group["tournament"],
        "team_name": team_name,
        "coach_id": coach_id,
        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "gf": 0,
        "ga": 0,
        "points": 0,
        "created_at": now,
        "updated_at": now,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def list_group_teams(
    *,
    group_id: Any,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    return list(
        collection.find({"record_type": "group_team", "group_id": group_id}).sort(
            [("team_name", 1)]
        )
    )


def _update_team_stats(
    team: dict[str, Any],
    scored: int,
    conceded: int,
) -> dict[str, Any]:
    team["played"] += 1
    team["gf"] += scored
    team["ga"] += conceded
    if scored > conceded:
        team["wins"] += 1
        team["points"] += 3
    elif scored == conceded:
        team["draws"] += 1
        team["points"] += 1
    else:
        team["losses"] += 1
    return team


def record_group_match(
    *,
    tournament_name: str,
    group_name: str,
    team_a: str,
    team_b: str,
    score_a: int,
    score_b: int,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    group = ensure_group(
        tournament_name=tournament_name,
        group_name=group_name,
        collection=collection,
    )
    ta = collection.find_one(
        {"record_type": "group_team", "group_id": group["_id"], "team_name": team_a}
    )
    tb = collection.find_one(
        {"record_type": "group_team", "group_id": group["_id"], "team_name": team_b}
    )
    if ta is None or tb is None:
        raise RuntimeError("Both teams must be registered in the group.")

    ta = _update_team_stats(ta, score_a, score_b)
    tb = _update_team_stats(tb, score_b, score_a)

    now = _now()
    for team in (ta, tb):
        collection.update_one(
            {"_id": team["_id"]},
            {
                "$set": {
                    "played": team["played"],
                    "wins": team["wins"],
                    "draws": team["draws"],
                    "losses": team["losses"],
                    "gf": team["gf"],
                    "ga": team["ga"],
                    "points": team["points"],
                    "updated_at": now,
                }
            },
        )

    match_doc = {
        "record_type": "group_match",
        "group_id": group["_id"],
        "tournament": group["tournament"],
        "team_a": ta["_id"],
        "team_b": tb["_id"],
        "score_a": score_a,
        "score_b": score_b,
        "played_at": now,
    }
    collection.insert_one(match_doc)
    return match_doc


def get_standings(
    *,
    tournament_name: str,
    group_name: str,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    group = ensure_group(
        tournament_name=tournament_name,
        group_name=group_name,
        collection=collection,
    )
    teams = list(
        collection.find({"record_type": "group_team", "group_id": group["_id"]})
    )
    teams.sort(
        key=lambda t: (
            -t.get("points", 0),
            -(t.get("gf", 0) - t.get("ga", 0)),
            -t.get("gf", 0),
            t.get("team_name", ""),
        )
    )
    return teams


def advance_top(
    *,
    tournament_name: str,
    group_name: str,
    top_n: int,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    standings = get_standings(
        tournament_name=tournament_name, group_name=group_name, collection=collection
    )
    top = standings[:top_n]
    advanced: list[dict[str, Any]] = []
    for idx, team in enumerate(top, start=1):
        participant = ts.add_participant(
            tournament_name=tournament_name,
            team_name=team["team_name"],
            coach_id=int(team.get("coach_id", 0)),
            seed=idx,
            collection=collection,
        )
        advanced.append(participant)
    return advanced


def generate_round_robin_pairs(teams: list[Any], *, double_round: bool = False) -> list[list[tuple[Any, Any | None]]]:
    """Generate round-robin pairs (Berger tables). If odd, add a bye (None)."""
    team_list = teams.copy()
    if len(team_list) % 2 == 1:
        team_list.append(None)
    n = len(team_list)
    rounds: list[list[tuple[Any, Any | None]]] = []
    for _ in range(n - 1):
        round_pairs: list[tuple[Any, Any | None]] = []
        for i in range(n // 2):
            a = team_list[i]
            b = team_list[n - 1 - i]
            round_pairs.append((a, b))
        # rotate
        team_list = [team_list[0]] + team_list[-1:] + team_list[1:-1]
        rounds.append(round_pairs)
    if double_round:
        mirror = [[(b, a) for (a, b) in r] for r in rounds]
        rounds.extend(mirror)
    return rounds


def fixtures_exist(
    *,
    group_id: Any,
    collection: Collection | None = None,
) -> bool:
    if collection is None:
        collection = get_collection()
    return (
        collection.count_documents({"record_type": "group_fixture", "group_id": group_id})
        > 0
    )


def generate_group_fixtures(
    *,
    tournament_name: str,
    group_name: str,
    double_round: bool = False,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    group = ensure_group(
        tournament_name=tournament_name,
        group_name=group_name,
        collection=collection,
    )
    if fixtures_exist(group_id=group["_id"], collection=collection):
        return list(
            collection.find(
                {"record_type": "group_fixture", "group_id": group["_id"]}
            ).sort([("round", 1), ("sequence", 1)])
        )
    teams = list_group_teams(group_id=group["_id"], collection=collection)
    if len(teams) < 2:
        raise RuntimeError("Need at least 2 teams in the group.")
    team_ids = [t["_id"] for t in teams]
    rounds = generate_round_robin_pairs(team_ids, double_round=double_round)
    now = _now()
    fixtures: list[dict[str, Any]] = []
    for rnd_idx, matches in enumerate(rounds, start=1):
        for seq_idx, (a, b) in enumerate(matches, start=1):
            doc = {
                "record_type": "group_fixture",
                "group_id": group["_id"],
                "tournament": group["tournament"],
                "round": rnd_idx,
                "sequence": seq_idx,
                "team_a": a,
                "team_b": b,
                "created_at": now,
            }
            result = collection.insert_one(doc)
            doc["_id"] = result.inserted_id
            fixtures.append(doc)
    return fixtures


def list_group_fixtures(
    *,
    tournament_name: str,
    group_name: str,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    group = ensure_group(
        tournament_name=tournament_name,
        group_name=group_name,
        collection=collection,
    )
    return list(
        collection.find(
            {"record_type": "group_fixture", "group_id": group["_id"]}
        ).sort([("round", 1), ("sequence", 1)])
    )
