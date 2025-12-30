from __future__ import annotations

import os
from datetime import datetime, timezone

from pymongo import MongoClient

COACH_ID = 790188155969601577
TEAM_NAMES = ["Test 1", "Test 2", "Test 3", "Test 4"]
DEFAULT_DB_NAME = "OffsideDiscordBot"


def main() -> None:
    mongo_uri = os.environ.get("MONGODB_URI")
    db_name = os.environ.get("MONGODB_DB_NAME") or DEFAULT_DB_NAME
    collection_name = os.environ.get("MONGODB_COLLECTION")
    cycle_id_raw = os.environ.get("CYCLE_ID")  # optional: hex id for a specific cycle
    if not mongo_uri:
        raise SystemExit("Set MONGODB_URI.")

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[db_name]
    if collection_name:
        cycles_collection = db[collection_name]
        rosters_collection = db[collection_name]
        players_collection = db[collection_name]
    else:
        cycles_collection = db["tournament_cycles"]
        rosters_collection = db["team_rosters"]
        players_collection = db["roster_players"]
    now = datetime.now(timezone.utc)

    cycle = cycles_collection.find_one({"record_type": "tournament_cycle", "is_active": True})
    if cycle is None:
        cycle = {
            "record_type": "tournament_cycle",
            "name": "Seeded Test Cycle",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        cycle_id = cycles_collection.insert_one(cycle).inserted_id
        cycle["_id"] = cycle_id
    else:
        cycle_id = cycle["_id"]

    if cycle_id_raw:
        cycle_id = cycle_id_raw

    def mk_player(idx: int, team_idx: int) -> dict:
        discord_id = COACH_ID + idx + (team_idx * 1000)
        return {
            "record_type": "roster_player",
            "roster_id": None,  # fill after roster insert
            "player_discord_id": discord_id,
            "gamertag": f"Player{team_idx+1}-{idx+1}",
            "ea_id": f"EA{team_idx+1}-{idx+1}",
            "console": "PS",
            "added_at": now,
        }

    for t_idx, name in enumerate(TEAM_NAMES):
        roster_doc = {
            "record_type": "team_roster",
            "cycle_id": cycle_id,
            "coach_discord_id": COACH_ID,
            "team_name": name,
            "cap": 25,
            "status": "DRAFT",
            "created_at": now,
            "updated_at": now,
            "submitted_at": None,
        }
        roster_id = rosters_collection.insert_one(roster_doc).inserted_id
        player_docs = [mk_player(p_idx, t_idx) for p_idx in range(8)]
        for p in player_docs:
            p["roster_id"] = roster_id
        if player_docs:
            players_collection.insert_many(player_docs)

    print("Seeded teams:", TEAM_NAMES)


if __name__ == "__main__":
    main()
