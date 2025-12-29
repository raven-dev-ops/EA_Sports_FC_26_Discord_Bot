from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from bson import ObjectId
from pymongo.collection import Collection

from database import get_collection

TOURNAMENT_STATE_DRAFT = "DRAFT"
TOURNAMENT_STATE_REG_OPEN = "REG_OPEN"
TOURNAMENT_STATE_IN_PROGRESS = "IN_PROGRESS"
TOURNAMENT_STATE_COMPLETED = "COMPLETED"


def _now():
    return datetime.now(timezone.utc)


def list_tournaments(*, collection: Collection | None = None) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    return list(
        collection.find({"record_type": "tournament"}).sort([("created_at", -1)])
    )


def get_tournament(name: str, *, collection: Collection | None = None) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection()
    return collection.find_one({"record_type": "tournament", "name": name})


def create_tournament(
    *,
    name: str,
    format: str = "single_elimination",
    rules: str | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    existing = get_tournament(name, collection=collection)
    if existing:
        return existing
    now = _now()
    doc = {
        "record_type": "tournament",
        "name": name,
        "format": format,
        "rules": rules,
        "state": TOURNAMENT_STATE_DRAFT,
        "created_at": now,
        "updated_at": now,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def update_tournament_state(
    name: str, state: str, *, collection: Collection | None = None
) -> bool:
    if collection is None:
        collection = get_collection()
    result = collection.update_one(
        {"record_type": "tournament", "name": name},
        {"$set": {"state": state, "updated_at": _now()}},
    )
    return result.matched_count > 0


def add_participant(
    *,
    tournament_name: str,
    team_name: str,
    coach_id: int,
    seed: int | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    tour = get_tournament(tournament_name, collection=collection)
    if tour is None:
        raise RuntimeError("Tournament not found.")
    if tour.get("state") not in {TOURNAMENT_STATE_DRAFT, TOURNAMENT_STATE_REG_OPEN}:
        raise RuntimeError("Registration is closed.")
    existing = collection.find_one(
        {
            "record_type": "tournament_participant",
            "tournament": tour["_id"],
            "team_name": team_name,
        }
    )
    if existing:
        return existing
    now = _now()
    doc = {
        "record_type": "tournament_participant",
        "tournament": tour["_id"],
        "team_name": team_name,
        "coach_id": coach_id,
        "seed": seed,
        "created_at": now,
        "updated_at": now,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def list_participants(tournament_name: str, *, collection: Collection | None = None) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    tour = get_tournament(tournament_name, collection=collection)
    if tour is None:
        return []
    return list(
        collection.find(
            {"record_type": "tournament_participant", "tournament": tour["_id"]}
        ).sort([("seed", 1), ("created_at", 1)])
    )


def _pairwise(items: list[Any]) -> list[tuple[Any | None, Any | None]]:
    pairs: list[tuple[Any | None, Any | None]] = []
    for i in range(0, len(items), 2):
        a = items[i]
        b = items[i + 1] if i + 1 < len(items) else None
        pairs.append((a, b))
    return pairs


def generate_bracket(
    *,
    tournament_name: str,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    tour = get_tournament(tournament_name, collection=collection)
    if tour is None:
        raise RuntimeError("Tournament not found.")

    participants = list_participants(tournament_name, collection=collection)
    if len(participants) < 2:
        raise RuntimeError("Need at least 2 participants to generate a bracket.")

    now = _now()
    pairs = _pairwise(participants)
    matches: list[dict[str, Any]] = []
    for idx, (a, b) in enumerate(pairs, start=1):
        match = {
            "record_type": "tournament_match",
            "tournament": tour["_id"],
            "round": 1,
            "sequence": idx,
            "team_a": a["_id"],
            "team_b": b["_id"] if b else None,
            "status": "PENDING",
            "scores": {},
            "winner": None,
            "created_at": now,
            "updated_at": now,
        }
        result = collection.insert_one(match)
        match["_id"] = result.inserted_id
        matches.append(match)
    update_tournament_state(tournament_name, TOURNAMENT_STATE_IN_PROGRESS, collection=collection)
    return matches


def list_matches(tournament_name: str, *, collection: Collection | None = None) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    tour = get_tournament(tournament_name, collection=collection)
    if tour is None:
        return []
    return list(
        collection.find(
            {"record_type": "tournament_match", "tournament": tour["_id"]}
        ).sort([("round", 1), ("sequence", 1)])
    )


def report_score(
    *,
    tournament_name: str,
    match_id: str,
    reporter_team_id: Any,
    score_for: int,
    score_against: int,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    tour = get_tournament(tournament_name, collection=collection)
    if tour is None:
        raise RuntimeError("Tournament not found.")
    match = collection.find_one(
        {
            "record_type": "tournament_match",
            "tournament": tour["_id"],
            "_id": ObjectId(match_id),
        }
    )
    if match is None:
        raise RuntimeError("Match not found.")
    if match.get("status") == "COMPLETED":
        return match
    scores = match.get("scores", {})
    scores[str(reporter_team_id)] = {
        "for": int(score_for),
        "against": int(score_against),
        "reported_at": _now(),
    }
    collection.update_one(
        {"_id": match["_id"]},
        {"$set": {"scores": scores, "status": "REPORTED", "updated_at": _now()}},
    )
    match["scores"] = scores
    match["status"] = "REPORTED"
    return match


def confirm_match(
    *,
    tournament_name: str,
    match_id: str,
    confirming_team_id: Any,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    tour = get_tournament(tournament_name, collection=collection)
    if tour is None:
        raise RuntimeError("Tournament not found.")
    match = collection.find_one(
        {
            "record_type": "tournament_match",
            "tournament": tour["_id"],
            "_id": ObjectId(match_id),
        }
    )
    if match is None:
        raise RuntimeError("Match not found.")
    if match.get("status") == "COMPLETED":
        return match
    scores = match.get("scores", {})
    reporter_score = None
    for team_id, payload in scores.items():
        reporter_score = payload
        break
    if not reporter_score:
        raise RuntimeError("No score reported yet.")
    winner = match.get("team_a")
    loser = match.get("team_b")
    if reporter_score["for"] < reporter_score["against"]:
        winner, loser = loser, winner
    collection.update_one(
        {"_id": match["_id"]},
        {
            "$set": {
                "scores": scores,
                "status": "COMPLETED",
                "winner": winner,
                "updated_at": _now(),
            }
        },
    )
    match["winner"] = winner
    match["status"] = "COMPLETED"
    return match
