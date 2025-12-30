from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from database import get_collection
from repositories.tournament_repo import ensure_active_cycle

ROSTER_STATUS_DRAFT = "DRAFT"
ROSTER_STATUS_SUBMITTED = "SUBMITTED"
ROSTER_STATUS_APPROVED = "APPROVED"
ROSTER_STATUS_REJECTED = "REJECTED"
ROSTER_STATUS_UNLOCKED = "UNLOCKED"


def get_roster_for_coach(
    coach_discord_id: int,
    *,
    cycle_id: Any | None = None,
    collection: Collection | None = None
) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection()
    cycle = (
        ensure_active_cycle(collection=collection) if cycle_id is None else {"_id": cycle_id}
    )
    return collection.find_one(
        {
            "record_type": "team_roster",
            "cycle_id": cycle["_id"],
            "coach_discord_id": coach_discord_id,
        }
    )


def get_rosters_for_coach(
    coach_discord_id: int, *, collection: Collection | None = None
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    return list(
        collection.find(
            {
                "record_type": "team_roster",
                "coach_discord_id": coach_discord_id,
            },
            sort=[("created_at", -1)],
        )
    )


def get_latest_roster_for_coach(
    coach_discord_id: int, *, collection: Collection | None = None
) -> dict[str, Any] | None:
    rosters = get_rosters_for_coach(coach_discord_id, collection=collection)
    return rosters[0] if rosters else None


def create_roster(
    *,
    coach_discord_id: int,
    team_name: str,
    cap: int,
    cycle_id: Any | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    cycle = (
        ensure_active_cycle(collection=collection) if cycle_id is None else {"_id": cycle_id}
    )
    existing = get_roster_for_coach(
        coach_discord_id, cycle_id=cycle["_id"], collection=collection
    )
    if existing:
        return existing

    now = datetime.now(timezone.utc)
    doc = {
        "record_type": "team_roster",
        "cycle_id": cycle["_id"],
        "coach_discord_id": coach_discord_id,
        "team_name": team_name,
        "practice_times": None,
        "cap": cap,
        "status": ROSTER_STATUS_DRAFT,
        "created_at": now,
        "updated_at": now,
        "submitted_at": None,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_roster_by_id(
    roster_id: Any, *, collection: Collection | None = None
) -> dict[str, Any] | None:
    if collection is None:
        collection = get_collection()
    return collection.find_one({"record_type": "team_roster", "_id": roster_id})


def get_roster_players(
    roster_id: Any, *, collection: Collection | None = None
) -> list[dict[str, Any]]:
    if collection is None:
        collection = get_collection()
    return list(
        collection.find(
            {"record_type": "roster_player", "roster_id": roster_id},
            sort=[("added_at", 1)],
        )
    )


def count_roster_players(
    roster_id: Any, *, collection: Collection | None = None
) -> int:
    if collection is None:
        collection = get_collection()
    return collection.count_documents(
        {"record_type": "roster_player", "roster_id": roster_id}
    )


def add_player(
    *,
    roster_id: Any,
    player_discord_id: int,
    gamertag: str,
    ea_id: str,
    console: str,
    cap: int,
    collection: Collection | None = None,
) -> dict[str, Any]:
    if collection is None:
        collection = get_collection()
    now = datetime.now(timezone.utc)

    existing = collection.find_one(
        {
            "record_type": "roster_player",
            "roster_id": roster_id,
            "player_discord_id": player_discord_id,
        }
    )
    if existing:
        raise RuntimeError("Player is already on this roster.")

    count = count_roster_players(roster_id, collection=collection)
    if count >= cap:
        raise RuntimeError("Roster cap reached.")

    doc = {
        "record_type": "roster_player",
        "roster_id": roster_id,
        "player_discord_id": player_discord_id,
        "gamertag": gamertag,
        "ea_id": ea_id,
        "console": console,
        "added_at": now,
    }
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def remove_player(
    *,
    roster_id: Any,
    player_discord_id: int,
    collection: Collection | None = None,
) -> bool:
    if collection is None:
        collection = get_collection()
    result = collection.delete_one(
        {
            "record_type": "roster_player",
            "roster_id": roster_id,
            "player_discord_id": player_discord_id,
        }
    )
    return result.deleted_count > 0


def delete_roster(
    roster_id: Any, *, collection: Collection | None = None
) -> None:
    if collection is None:
        collection = get_collection()
    collection.delete_many(
        {"record_type": "roster_player", "roster_id": roster_id}
    )
    collection.delete_many(
        {"record_type": "submission_message", "roster_id": roster_id}
    )
    collection.delete_one({"record_type": "team_roster", "_id": roster_id})


def set_roster_status(
    roster_id: Any,
    status: str,
    *,
    collection: Collection | None = None,
    expected_updated_at: datetime | None = None,
) -> None:
    if collection is None:
        collection = get_collection()
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {"status": status, "updated_at": now}
    if status == ROSTER_STATUS_SUBMITTED:
        updates["submitted_at"] = now
    if status in {ROSTER_STATUS_UNLOCKED, ROSTER_STATUS_DRAFT}:
        updates["submitted_at"] = None
    filter_doc: dict[str, Any] = {"record_type": "team_roster", "_id": roster_id}
    if expected_updated_at is not None:
        filter_doc["updated_at"] = expected_updated_at
    result = collection.update_one(filter_doc, {"$set": updates})
    if expected_updated_at is not None and result.matched_count == 0:
        raise RuntimeError("Roster changed; reopen the dashboard and try again.")


def roster_is_locked(roster: dict[str, Any]) -> bool:
    return roster.get("status") in {
        ROSTER_STATUS_SUBMITTED,
        ROSTER_STATUS_APPROVED,
        ROSTER_STATUS_REJECTED,
    }


def validate_roster_identity(
    roster_id: Any, *, collection: Collection | None = None
) -> tuple[bool, str]:
    """
    Validate roster before submission: duplicates, missing fields, and counts.
    Returns (ok, message).
    """
    if collection is None:
        collection = get_collection()
    players = list(
        collection.find(
            {"record_type": "roster_player", "roster_id": roster_id},
            sort=[("added_at", 1)],
        )
    )
    if len(players) < 8:
        return False, "You need at least 8 players before submitting."
    seen = set()
    for p in players:
        pid = p.get("player_discord_id")
        if pid in seen:
            return False, "Duplicate player detected in the roster."
        seen.add(pid)
        if not p.get("gamertag") or not p.get("ea_id"):
            return False, "All players must include gamertag and EA ID."
    return True, "OK"


def update_roster_name(
    roster_id: Any, team_name: str, *, collection: Collection | None = None
) -> None:
    if collection is None:
        collection = get_collection()
    now = datetime.now(timezone.utc)
    collection.update_one(
        {"record_type": "team_roster", "_id": roster_id},
        {"$set": {"team_name": team_name, "updated_at": now}},
    )


def update_practice_times(
    roster_id: Any,
    practice_times: str | None,
    *,
    collection: Collection | None = None,
) -> None:
    if collection is None:
        collection = get_collection()
    now = datetime.now(timezone.utc)
    collection.update_one(
        {"record_type": "team_roster", "_id": roster_id},
        {"$set": {"practice_times": practice_times, "updated_at": now}},
    )


def update_roster_cap(
    roster_id: Any,
    cap: int,
    *,
    collection: Collection | None = None,
) -> None:
    if collection is None:
        collection = get_collection()
    now = datetime.now(timezone.utc)
    collection.update_one(
        {"record_type": "team_roster", "_id": roster_id},
        {"$set": {"cap": int(cap), "updated_at": now}},
    )
