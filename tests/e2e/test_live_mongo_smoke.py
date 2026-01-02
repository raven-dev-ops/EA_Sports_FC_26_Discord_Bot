from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from config.settings import Settings
from database import DEFAULT_DB_NAME, close_client, get_collection
from services import (
    clubs_service,
    fc25_stats_service,
    recruitment_service,
    roster_service,
    tournament_service,
)
from utils.env_file import load_env_file

pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_MONGO_SMOKE") != "1",
    reason="Set LIVE_MONGO_SMOKE=1 to run against a real MongoDB instance.",
)


def _build_settings(*, mongo_uri: str, db_name: str, collection_name: str) -> Settings:
    return Settings(
        discord_token="smoke",
        discord_application_id=1,
        discord_client_id=None,
        discord_public_key=None,
        interactions_endpoint_url=None,
        test_mode=True,
        role_broskie_id=None,
        role_team_coach_id=None,
        role_club_manager_id=None,
        role_league_staff_id=None,
        role_league_owner_id=None,
        role_free_agent_id=None,
        role_pro_player_id=None,
        role_retired_id=None,
        channel_staff_portal_id=None,
        channel_club_portal_id=None,
        channel_manager_portal_id=None,
        channel_coach_portal_id=None,
        channel_recruit_portal_id=None,
        channel_staff_monitor_id=None,
        channel_recruit_listing_id=None,
        channel_club_listing_id=None,
        channel_premium_coaches_id=None,
        staff_role_ids=set(),
        mongodb_uri=mongo_uri,
        mongodb_db_name=db_name,
        mongodb_collection=collection_name,
        mongodb_per_guild_db=False,
        mongodb_guild_db_prefix="",
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )


def test_live_mongo_seed_and_smoke() -> None:
    env_path = Path(os.environ.get("OFFSIDE_ENV_FILE", ".env"))
    if env_path.exists():
        load_env_file(env_path, override=False)

    mongo_uri = os.environ.get("MONGODB_URI", "").strip()
    assert mongo_uri, "Missing MONGODB_URI (set env var or provide OFFSIDE_ENV_FILE=.env)."

    guild_id = int(os.environ.get("DISCORD_GUILD_ID", "123"))
    db_name = os.environ.get("MONGODB_DB_NAME", DEFAULT_DB_NAME).strip() or DEFAULT_DB_NAME
    collection_name = os.environ.get("MONGODB_COLLECTION", "").strip() or "Isaac_Elera"

    seed_tag = f"offside-smoke-{uuid.uuid4().hex[:8]}"
    settings = _build_settings(mongo_uri=mongo_uri, db_name=db_name, collection_name=collection_name)
    collection = get_collection(settings)

    cmd = [
        sys.executable,
        "-m",
        "scripts.seed_test_data",
        "--env-file",
        str(env_path),
        "--db-name",
        db_name,
        "--collection",
        collection_name,
        "--guild-id",
        str(guild_id),
        "--tag",
        seed_tag,
        "--purge",
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)

        required_record_types = [
            "guild_settings",
            "tournament_cycle",
            "team_roster",
            "roster_player",
            "submission_message",
            "roster_audit",
            "recruit_profile",
            "club_ad",
            "club_ad_audit",
            "fc25_stats_link",
            "fc25_stats_snapshot",
            "tournament",
            "tournament_participant",
            "tournament_match",
            "tournament_group",
            "group_team",
            "group_match",
            "group_fixture",
        ]
        for record_type in required_record_types:
            assert (
                collection.count_documents({"record_type": record_type, "seed_tag": seed_tag}) > 0
            ), f"Expected at least 1 {record_type} doc for seed_tag={seed_tag}"

        # --- roster flows ---
        seeded_roster = collection.find_one(
            {"record_type": "team_roster", "seed_tag": seed_tag},
            sort=[("cap", -1)],
        )
        assert seeded_roster is not None
        ok, msg = roster_service.validate_roster_identity(seeded_roster["_id"], collection=collection)
        assert ok, msg

        players = roster_service.get_roster_players(seeded_roster["_id"], collection=collection)
        assert len(players) >= 8

        # --- recruit search flows ---
        recruits = recruitment_service.search_recruit_profiles(guild_id, position="ST", collection=collection)
        assert recruits, "Expected seeded recruit profiles to be searchable by position."
        servers = recruitment_service.list_recruit_profile_distinct(
            guild_id, "server_name", limit=10, collection=collection
        )
        assert servers, "Expected distinct server_name values for seeded recruits."

        # --- club flows ---
        seeded_club = collection.find_one({"record_type": "club_ad", "seed_tag": seed_tag})
        assert seeded_club is not None
        club_doc = clubs_service.get_club_ad(guild_id, int(seeded_club["owner_id"]), collection=collection)
        assert club_doc is not None

        # --- FC25 stats flows ---
        links = fc25_stats_service.list_links(guild_id, verified_only=False, collection=collection)
        assert links, "Expected seeded FC25 links."
        latest = fc25_stats_service.get_latest_snapshot(guild_id, int(links[0]["user_id"]), collection=collection)
        assert latest is not None, "Expected seeded FC25 snapshots."

        # --- tournament flows ---
        seeded_tournament = collection.find_one({"record_type": "tournament", "seed_tag": seed_tag})
        assert seeded_tournament is not None
        tournament_name = str(seeded_tournament["name"])
        participants = tournament_service.list_participants(tournament_name, collection=collection)
        assert len(participants) >= 2

        matches = tournament_service.list_matches(tournament_name, collection=collection)
        assert matches, "Expected seeded tournament matches."
        match = next((m for m in matches if m.get("team_b") is not None), matches[0])
        reported = tournament_service.report_score(
            tournament_name=tournament_name,
            match_id=str(match["_id"]),
            reporter_team_id=match["team_a"],
            score_for=2,
            score_against=1,
            collection=collection,
        )
        assert reported.get("scores"), "Expected match to have a reported score."
        confirmed = tournament_service.confirm_match(
            tournament_name=tournament_name,
            match_id=str(match["_id"]),
            confirming_team_id=match["team_a"],
            collection=collection,
        )
        assert confirmed.get("status") == tournament_service.MATCH_STATUS_COMPLETED
        assert confirmed.get("winner") is not None
    finally:
        collection.delete_many({"seed_tag": seed_tag})
        close_client()
