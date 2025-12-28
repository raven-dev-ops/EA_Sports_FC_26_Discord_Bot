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
    coach_discord_id: int, *, collection: Collection | None = None
) -> dict[str, Any] | None:
    collection = collection or get_collection()
    cycle = ensure_active_cycle(collection=collection)
    return collection.find_one(
        {
            "record_type": "team_roster",
            "cycle_id": cycle["_id"],
            "coach_discord_id": coach_discord_id,
        }
    )


def create_roster(
    *,
    coach_discord_id: int,
    team_name: str,
    cap: int,
    collection: Collection | None = None,
) -> dict[str, Any]:
    collection = collection or get_collection()
    cycle = ensure_active_cycle(collection=collection)
    existing = get_roster_for_coach(coach_discord_id, collection=collection)
    if existing:
        return existing

    now = datetime.now(timezone.utc)
    doc = {
        "record_type": "team_roster",
        "cycle_id": cycle["_id"],
        "coach_discord_id": coach_discord_id,
        "team_name": team_name,
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
    collection = collection or get_collection()
    return collection.find_one({"record_type": "team_roster", "_id": roster_id})


def get_roster_players(
    roster_id: Any, *, collection: Collection | None = None
) -> list[dict[str, Any]]:
    collection = collection or get_collection()
    return list(
        collection.find(
            {"record_type": "roster_player", "roster_id": roster_id},
            sort=[("added_at", 1)],
        )
    )


def count_roster_players(
    roster_id: Any, *, collection: Collection | None = None
) -> int:
    collection = collection or get_collection()
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
    collection = collection or get_collection()
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
    collection = collection or get_collection()
    result = collection.delete_one(
        {
            "record_type": "roster_player",
            "roster_id": roster_id,
            "player_discord_id": player_discord_id,
        }
    )
    return result.deleted_count > 0


def set_roster_status(
    roster_id: Any, status: str, *, collection: Collection | None = None
) -> None:
    collection = collection or get_collection()
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {"status": status, "updated_at": now}
    if status == ROSTER_STATUS_SUBMITTED:
        updates["submitted_at"] = now
    collection.update_one(
        {"record_type": "team_roster", "_id": roster_id},
        {"$set": updates},
    )


def roster_is_locked(roster: dict[str, Any]) -> bool:
    return roster.get("status") in {
        ROSTER_STATUS_SUBMITTED,
        ROSTER_STATUS_APPROVED,
        ROSTER_STATUS_REJECTED,
    }
