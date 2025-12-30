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

TEAM_ROSTER_RECORD_TYPE = "team_roster"
ROSTER_PLAYER_RECORD_TYPE = "roster_player"
SUBMISSION_RECORD_TYPE = "submission_message"


def _team_rosters(collection: Collection | None) -> Collection:
    return collection or get_collection(record_type=TEAM_ROSTER_RECORD_TYPE)


def _roster_players(collection: Collection | None) -> Collection:
    return collection or get_collection(record_type=ROSTER_PLAYER_RECORD_TYPE)


def _submission_messages(collection: Collection | None) -> Collection:
    return collection or get_collection(record_type=SUBMISSION_RECORD_TYPE)


def get_roster_for_coach(
    coach_discord_id: int,
    *,
    cycle_id: Any | None = None,
    collection: Collection | None = None
) -> dict[str, Any] | None:
    cycle = (
        ensure_active_cycle(collection=collection) if (collection is not None and cycle_id is None)
        else ensure_active_cycle() if cycle_id is None
        else {"_id": cycle_id}
    )
    team_rosters = _team_rosters(collection)
    return team_rosters.find_one(
        {
            "record_type": TEAM_ROSTER_RECORD_TYPE,
            "cycle_id": cycle["_id"],
            "coach_discord_id": coach_discord_id,
        }
    )


def get_rosters_for_coach(
    coach_discord_id: int, *, collection: Collection | None = None
) -> list[dict[str, Any]]:
    team_rosters = _team_rosters(collection)
    return list(
        team_rosters.find(
            {
                "record_type": TEAM_ROSTER_RECORD_TYPE,
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
    cycle = (
        ensure_active_cycle(collection=collection) if (collection is not None and cycle_id is None)
        else ensure_active_cycle() if cycle_id is None
        else {"_id": cycle_id}
    )
    team_rosters = _team_rosters(collection)
    existing = team_rosters.find_one(
        {
            "record_type": TEAM_ROSTER_RECORD_TYPE,
            "cycle_id": cycle["_id"],
            "coach_discord_id": coach_discord_id,
        }
    )
    if existing:
        return existing

    now = datetime.now(timezone.utc)
    doc = {
        "record_type": TEAM_ROSTER_RECORD_TYPE,
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
    result = team_rosters.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_roster_by_id(
    roster_id: Any, *, collection: Collection | None = None
) -> dict[str, Any] | None:
    team_rosters = _team_rosters(collection)
    return team_rosters.find_one({"record_type": TEAM_ROSTER_RECORD_TYPE, "_id": roster_id})


def get_roster_players(
    roster_id: Any, *, collection: Collection | None = None
) -> list[dict[str, Any]]:
    roster_players = _roster_players(collection)
    return list(
        roster_players.find(
            {"record_type": ROSTER_PLAYER_RECORD_TYPE, "roster_id": roster_id},
            sort=[("added_at", 1)],
        )
    )


def count_roster_players(
    roster_id: Any, *, collection: Collection | None = None
) -> int:
    roster_players = _roster_players(collection)
    return roster_players.count_documents({"record_type": ROSTER_PLAYER_RECORD_TYPE, "roster_id": roster_id})


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
    roster_players = _roster_players(collection)
    now = datetime.now(timezone.utc)

    existing = roster_players.find_one(
        {
            "record_type": ROSTER_PLAYER_RECORD_TYPE,
            "roster_id": roster_id,
            "player_discord_id": player_discord_id,
        }
    )
    if existing:
        raise RuntimeError("Player is already on this roster.")

    count = count_roster_players(roster_id, collection=roster_players)
    if count >= cap:
        raise RuntimeError("Roster cap reached.")

    doc = {
        "record_type": ROSTER_PLAYER_RECORD_TYPE,
        "roster_id": roster_id,
        "player_discord_id": player_discord_id,
        "gamertag": gamertag,
        "ea_id": ea_id,
        "console": console,
        "added_at": now,
    }
    result = roster_players.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def remove_player(
    *,
    roster_id: Any,
    player_discord_id: int,
    collection: Collection | None = None,
) -> bool:
    roster_players = _roster_players(collection)
    result = roster_players.delete_one(
        {
            "record_type": ROSTER_PLAYER_RECORD_TYPE,
            "roster_id": roster_id,
            "player_discord_id": player_discord_id,
        }
    )
    return result.deleted_count > 0


def delete_roster(
    roster_id: Any, *, collection: Collection | None = None
) -> None:
    if collection is not None:
        collection.delete_many({"record_type": ROSTER_PLAYER_RECORD_TYPE, "roster_id": roster_id})
        collection.delete_many({"record_type": SUBMISSION_RECORD_TYPE, "roster_id": roster_id})
        collection.delete_one({"record_type": TEAM_ROSTER_RECORD_TYPE, "_id": roster_id})
        return

    roster_players = _roster_players(None)
    submission_messages = _submission_messages(None)
    team_rosters = _team_rosters(None)
    roster_players.delete_many({"record_type": ROSTER_PLAYER_RECORD_TYPE, "roster_id": roster_id})
    submission_messages.delete_many({"record_type": SUBMISSION_RECORD_TYPE, "roster_id": roster_id})
    team_rosters.delete_one({"record_type": TEAM_ROSTER_RECORD_TYPE, "_id": roster_id})


def set_roster_status(
    roster_id: Any,
    status: str,
    *,
    collection: Collection | None = None,
    expected_updated_at: datetime | None = None,
) -> None:
    team_rosters = _team_rosters(collection)
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {"status": status, "updated_at": now}
    if status == ROSTER_STATUS_SUBMITTED:
        updates["submitted_at"] = now
    if status in {ROSTER_STATUS_UNLOCKED, ROSTER_STATUS_DRAFT}:
        updates["submitted_at"] = None
    filter_doc: dict[str, Any] = {"record_type": TEAM_ROSTER_RECORD_TYPE, "_id": roster_id}
    if expected_updated_at is not None:
        filter_doc["updated_at"] = expected_updated_at
    result = team_rosters.update_one(filter_doc, {"$set": updates})
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
    roster_players = _roster_players(collection)
    players = list(
        roster_players.find(
            {"record_type": ROSTER_PLAYER_RECORD_TYPE, "roster_id": roster_id},
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
    team_rosters = _team_rosters(collection)
    now = datetime.now(timezone.utc)
    team_rosters.update_one(
        {"record_type": TEAM_ROSTER_RECORD_TYPE, "_id": roster_id},
        {"$set": {"team_name": team_name, "updated_at": now}},
    )


def update_practice_times(
    roster_id: Any,
    practice_times: str | None,
    *,
    collection: Collection | None = None,
) -> None:
    team_rosters = _team_rosters(collection)
    now = datetime.now(timezone.utc)
    team_rosters.update_one(
        {"record_type": TEAM_ROSTER_RECORD_TYPE, "_id": roster_id},
        {"$set": {"practice_times": practice_times, "updated_at": now}},
    )


def update_roster_cap(
    roster_id: Any,
    cap: int,
    *,
    collection: Collection | None = None,
) -> None:
    team_rosters = _team_rosters(collection)
    now = datetime.now(timezone.utc)
    team_rosters.update_one(
        {"record_type": TEAM_ROSTER_RECORD_TYPE, "_id": roster_id},
        {"$set": {"cap": int(cap), "updated_at": now}},
    )
