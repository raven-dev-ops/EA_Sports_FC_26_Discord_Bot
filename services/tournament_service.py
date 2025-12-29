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

MATCH_STATUS_PENDING = "PENDING"
MATCH_STATUS_REPORTED = "REPORTED"
MATCH_STATUS_COMPLETED = "COMPLETED"


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
    matches_channel_id: int | None = None,
    disputes_channel_id: int | None = None,
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
        "matches_channel_id": matches_channel_id,
        "disputes_channel_id": disputes_channel_id,
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


def update_tournament_channels(
    name: str,
    *,
    matches_channel_id: int | None = None,
    disputes_channel_id: int | None = None,
    collection: Collection | None = None,
) -> bool:
    if collection is None:
        collection = get_collection()
    updates: dict[str, Any] = {"updated_at": _now()}
    if matches_channel_id is not None:
        updates["matches_channel_id"] = matches_channel_id
    if disputes_channel_id is not None:
        updates["disputes_channel_id"] = disputes_channel_id
    result = collection.update_one(
        {"record_type": "tournament", "name": name},
        {"$set": updates},
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
            "status": MATCH_STATUS_PENDING,
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
    if match.get("status") == MATCH_STATUS_COMPLETED:
        return match
    scores = match.get("scores", {})
    existing = scores.get(str(reporter_team_id))
    if existing and existing.get("for") == score_for and existing.get("against") == score_against:
        return match
    scores[str(reporter_team_id)] = {
        "for": int(score_for),
        "against": int(score_against),
        "reported_at": _now(),
    }
    collection.update_one(
        {"_id": match["_id"]},
        {"$set": {"scores": scores, "status": MATCH_STATUS_REPORTED, "updated_at": _now()}},
    )
    match["scores"] = scores
    match["status"] = MATCH_STATUS_REPORTED
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
    if match.get("status") == MATCH_STATUS_COMPLETED:
        return match
    if match.get("status") != MATCH_STATUS_REPORTED:
        raise RuntimeError("No score reported yet.")
    scores = match.get("scores", {})
    if not scores:
        raise RuntimeError("No score reported yet.")
    reporter_score = next(iter(scores.values()))
    winner = match.get("team_a")
    loser = match.get("team_b")
    if reporter_score["for"] < reporter_score["against"]:
        winner, loser = loser, winner
    collection.update_one(
        {"_id": match["_id"]},
        {
            "$set": {
                "scores": scores,
                "status": MATCH_STATUS_COMPLETED,
                "winner": winner,
                "updated_at": _now(),
            }
        },
    )
    match["winner"] = winner
    match["status"] = MATCH_STATUS_COMPLETED
    return match


def set_match_deadline(
    *,
    tournament_name: str,
    match_id: str,
    deadline: str,
    collection: Collection | None = None,
) -> bool:
    if collection is None:
        collection = get_collection()
    tour = get_tournament(tournament_name, collection=collection)
    if tour is None:
        return False
    result = collection.update_one(
        {
            "record_type": "tournament_match",
            "tournament": tour["_id"],
            "_id": ObjectId(match_id),
        },
        {"$set": {"deadline": deadline, "updated_at": _now()}},
    )
    return result.matched_count > 0


def forfeit_match(
    *,
    tournament_name: str,
    match_id: str,
    winner_team_id: Any,
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
    if match.get("status") == MATCH_STATUS_COMPLETED:
        return match
    collection.update_one(
        {"_id": match["_id"]},
        {
            "$set": {
                "winner": winner_team_id,
                "status": MATCH_STATUS_COMPLETED,
                "updated_at": _now(),
            }
        },
    )
    match["winner"] = winner_team_id
    match["status"] = MATCH_STATUS_COMPLETED
    return match


def request_reschedule(
    *,
    tournament_name: str,
    match_id: str,
    reason: str,
    requested_by: Any,
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
    reqs = match.get("reschedule_requests", [])
    reqs.append(
        {"requested_by": requested_by, "reason": reason, "requested_at": _now()}
    )
    collection.update_one(
        {"_id": match["_id"]},
        {"$set": {"reschedule_requests": reqs, "updated_at": _now()}},
    )
    match["reschedule_requests"] = reqs
    return match


def add_dispute(
    *,
    tournament_name: str,
    match_id: str,
    reason: str,
    filed_by: Any,
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
    disputes = match.get("disputes", [])
    disputes.append(
        {
            "filed_by": filed_by,
            "reason": reason,
            "filed_at": _now(),
            "resolved": False,
            "resolution": None,
        }
    )
    collection.update_one(
        {"_id": match["_id"]},
        {"$set": {"disputes": disputes, "updated_at": _now()}},
    )
    match["disputes"] = disputes
    return match


def resolve_dispute(
    *,
    tournament_name: str,
    match_id: str,
    resolution: str,
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
    disputes = match.get("disputes", [])
    if not disputes:
        raise RuntimeError("No disputes to resolve.")
    disputes[-1]["resolved"] = True
    disputes[-1]["resolution"] = resolution
    disputes[-1]["resolved_at"] = _now()
    collection.update_one(
        {"_id": match["_id"]},
        {"$set": {"disputes": disputes, "updated_at": _now()}},
    )
    match["disputes"] = disputes
    return match


def advance_round(
    *,
    tournament_name: str,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    tour = get_tournament(tournament_name, collection=collection)
    if tour is None:
        raise RuntimeError("Tournament not found.")
    matches = list_matches(tournament_name, collection=collection)
    if not matches:
        raise RuntimeError("No matches exist.")
    current_round = max(m.get("round", 1) for m in matches)
    completed = [
        m for m in matches if m.get("round") == current_round and m.get("status") == MATCH_STATUS_COMPLETED
    ]
    winners = [m.get("winner") for m in completed if m.get("winner")]
    if len(winners) < 2:
        if len(winners) == 1:
            update_tournament_state(tournament_name, TOURNAMENT_STATE_COMPLETED, collection=collection)
        raise RuntimeError("Not enough completed matches to advance.")
    pairs = _pairwise(winners)
    now = _now()
    next_round = current_round + 1
    new_matches: list[dict[str, Any]] = []
    for idx, (a, b) in enumerate(pairs, start=1):
        match = {
            "record_type": "tournament_match",
            "tournament": tour["_id"],
            "round": next_round,
            "sequence": idx,
            "team_a": a,
            "team_b": b,
            "status": MATCH_STATUS_PENDING,
            "scores": {},
            "winner": None,
            "deadline": None,
            "disputes": [],
            "created_at": now,
            "updated_at": now,
        }
        result = collection.insert_one(match)
        match["_id"] = result.inserted_id
        new_matches.append(match)
    if len(new_matches) == 1 and new_matches[0]["team_b"] is None:
        update_tournament_state(tournament_name, TOURNAMENT_STATE_COMPLETED, collection=collection)
    return new_matches
