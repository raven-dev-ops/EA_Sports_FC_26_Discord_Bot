"""
Seed demo/test data into MongoDB for local development.

Usage:
  # Option A: rely on environment variables
  set MONGODB_URI=...
  set MONGODB_DB_NAME=OffsideDiscordBot
  set MONGODB_COLLECTION=Isaac_Elera  # legacy single-collection mode (optional)

  python -m scripts.seed_test_data --guild-id 123 --tag offside-demo --purge

  # Option B: load variables from a .env file (recommended for local dev)
  python -m scripts.seed_test_data --env-file .env --collection Isaac_Elera --guild-id 123 --tag offside-demo --purge
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config.settings import Settings
from database import DEFAULT_DB_NAME, get_collection, guild_db_context
from migrations import apply_migrations
from utils.env_file import load_env_file


def _build_settings(
    *,
    mongo_uri: str,
    db_name: str | None,
    collection_name: str | None,
    per_guild_db: bool,
    guild_db_prefix: str,
) -> Settings:
    return Settings(
        discord_token="seed",
        discord_application_id=1,
        discord_client_id=None,
        discord_public_key=None,
        interactions_endpoint_url=None,
        test_mode=True,
        role_broskie_id=None,
        role_team_coach_id=None,
        role_coach_plus_id=None,
        role_club_manager_id=None,
        role_club_manager_plus_id=None,
        role_league_staff_id=None,
        role_league_owner_id=None,
        role_free_agent_id=None,
        role_pro_player_id=None,
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
        mongodb_per_guild_db=bool(per_guild_db),
        mongodb_guild_db_prefix=str(guild_db_prefix or ""),
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed demo/test data for Offside Bot.")
    parser.add_argument(
        "--env-file",
        type=str,
        default=None,
        help="Optional path to a .env file to load (defaults to .env when present).",
    )
    parser.add_argument(
        "--db-name",
        type=str,
        default=None,
        help="Override MONGODB_DB_NAME (default OffsideDiscordBot).",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Override MONGODB_COLLECTION (e.g., Isaac_Elera for legacy single-collection mode).",
    )
    parser.add_argument("--guild-id", type=int, default=123, help="Guild ID to associate with demo data.")
    parser.add_argument(
        "--tag",
        type=str,
        default="offside-demo",
        help="Seed tag stored on documents (used for idempotent re-seeding).",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete existing documents with the same seed tag before inserting.",
    )
    return parser.parse_args()


def _replace_one(col, *, filter_doc: dict[str, Any], doc: dict[str, Any]) -> None:
    col.replace_one(filter_doc, doc, upsert=True)


def _delete_seeded(col, *, tag: str) -> int:
    result = col.delete_many({"seed_tag": tag})
    return int(result.deleted_count or 0)


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    env_path = Path(args.env_file) if args.env_file else Path(".env")
    if env_path.exists():
        load_env_file(env_path, override=False)

    mongo_uri = os.environ.get("MONGODB_URI", "").strip()
    if not mongo_uri:
        raise SystemExit("Set MONGODB_URI (or pass --env-file).")

    db_name = (args.db_name or os.environ.get("MONGODB_DB_NAME", "").strip()) or None
    collection_name = (args.collection or os.environ.get("MONGODB_COLLECTION", "").strip()) or None
    per_guild_db = os.environ.get("MONGODB_PER_GUILD_DB", "").strip().lower() in {"1", "true", "yes", "on"}
    guild_db_prefix = os.environ.get("MONGODB_GUILD_DB_PREFIX", "").strip()

    if db_name is None:
        db_name = DEFAULT_DB_NAME

    settings = _build_settings(
        mongo_uri=mongo_uri,
        db_name=db_name,
        collection_name=collection_name,
        per_guild_db=per_guild_db,
        guild_db_prefix=guild_db_prefix,
    )
    guild_id = int(args.guild_id)
    if settings.mongodb_per_guild_db:
        with guild_db_context(guild_id):
            apply_migrations(settings=settings, logger=logging.getLogger(__name__))
    else:
        apply_migrations(settings=settings, logger=logging.getLogger(__name__))

    seed_tag = str(args.tag).strip() or "offside-demo"
    now = datetime.now(timezone.utc)

    collections: dict[str, Any] = {
        "coaches": get_collection(settings, record_type="coach", guild_id=guild_id),
        "managers": get_collection(settings, record_type="manager", guild_id=guild_id),
        "players": get_collection(settings, record_type="player", guild_id=guild_id),
        "leagues": get_collection(settings, record_type="league", guild_id=guild_id),
        "stats": get_collection(settings, record_type="stat", guild_id=guild_id),
        "guild_settings": get_collection(settings, record_type="guild_settings", guild_id=guild_id),
        "tournament_cycles": get_collection(settings, record_type="tournament_cycle", guild_id=guild_id),
        "team_rosters": get_collection(settings, record_type="team_roster", guild_id=guild_id),
        "roster_players": get_collection(settings, record_type="roster_player", guild_id=guild_id),
        "submission_messages": get_collection(
            settings, record_type="submission_message", guild_id=guild_id
        ),
        "roster_audits": get_collection(settings, record_type="roster_audit", guild_id=guild_id),
        "recruit_profiles": get_collection(settings, record_type="recruit_profile", guild_id=guild_id),
        "club_ads": get_collection(settings, record_type="club_ad", guild_id=guild_id),
        "club_ad_audits": get_collection(settings, record_type="club_ad_audit", guild_id=guild_id),
        "fc25_stats_links": get_collection(settings, record_type="fc25_stats_link", guild_id=guild_id),
        "fc25_stats_snapshots": get_collection(
            settings, record_type="fc25_stats_snapshot", guild_id=guild_id
        ),
        "tournaments": get_collection(settings, record_type="tournament", guild_id=guild_id),
        "tournament_participants": get_collection(
            settings, record_type="tournament_participant", guild_id=guild_id
        ),
        "tournament_matches": get_collection(settings, record_type="tournament_match", guild_id=guild_id),
        "tournament_groups": get_collection(settings, record_type="tournament_group", guild_id=guild_id),
        "group_teams": get_collection(settings, record_type="group_team", guild_id=guild_id),
        "group_matches": get_collection(settings, record_type="group_match", guild_id=guild_id),
        "group_fixtures": get_collection(settings, record_type="group_fixture", guild_id=guild_id),
    }

    if args.purge:
        unique = {}
        for name, col in collections.items():
            unique.setdefault(getattr(col, "full_name", name), col)
        deleted_total = 0
        for col in unique.values():
            deleted_total += _delete_seeded(col, tag=seed_tag)
        logging.info("Purged %s seeded docs (seed_tag=%s).", deleted_total, seed_tag)

    # --- guild_settings ---
    guild_settings_doc = {
        "record_type": "guild_settings",
        "guild_id": guild_id,
        "settings": {
            "fc25_stats_enabled": True,
            "premium_coaches_pin_enabled": True,
        },
        "seed_tag": seed_tag,
        "updated_at": now,
        "created_at": now,
    }
    _replace_one(
        collections["guild_settings"],
        filter_doc={"record_type": "guild_settings", "guild_id": guild_id},
        doc=guild_settings_doc,
    )

    # --- tournament_cycles ---
    cycle_col = collections["tournament_cycles"]
    active_cycle = cycle_col.find_one(
        {"record_type": "tournament_cycle", "is_active": True},
        sort=[("created_at", -1)],
    )
    seed_cycle_name = f"[SEED:{seed_tag}] Demo Cycle"
    seed_cycle_filter = {"record_type": "tournament_cycle", "name": seed_cycle_name}
    seed_cycle = cycle_col.find_one(seed_cycle_filter)
    if seed_cycle is None:
        seed_cycle_doc = {
            "record_type": "tournament_cycle",
            "name": seed_cycle_name,
            "is_active": active_cycle is None,
            "created_at": now,
            "updated_at": now,
            "seed_tag": seed_tag,
        }
        _replace_one(cycle_col, filter_doc=seed_cycle_filter, doc=seed_cycle_doc)
        seed_cycle = cycle_col.find_one(seed_cycle_filter)
    cycle_for_rosters = active_cycle or seed_cycle
    if cycle_for_rosters is None:
        raise RuntimeError("Failed to resolve a tournament cycle for seeding rosters.")

    # --- team_rosters + roster_players + submission_messages + roster_audits ---
    rosters_col = collections["team_rosters"]
    roster_players_col = collections["roster_players"]
    submissions_col = collections["submission_messages"]
    audits_col = collections["roster_audits"]

    seed_staff_id = 999_900_000_000_000_001
    coaches = [
        {
            "coach_discord_id": 999_000_000_000_000_001,
            "team_name": f"[SEED:{seed_tag}] Falcons FC",
            "cap": 16,
            "practice_times": "Mon/Wed 20:00-22:00 UTC",
            "status": "DRAFT",
            "player_count": 12,
        },
        {
            "coach_discord_id": 999_000_000_000_000_002,
            "team_name": f"[SEED:{seed_tag}] Wolves FC",
            "cap": 22,
            "practice_times": "Tue/Thu 19:00-21:00 UTC",
            "status": "SUBMITTED",
            "player_count": 19,
        },
        {
            "coach_discord_id": 999_000_000_000_000_003,
            "team_name": f"[SEED:{seed_tag}] Titans FC",
            "cap": 22,
            "practice_times": "Sat/Sun 18:00-20:00 UTC",
            "status": "APPROVED",
            "player_count": 22,
        },
    ]

    roster_docs: list[dict[str, Any]] = []
    for idx, coach in enumerate(coaches, start=1):
        roster_filter = {
            "record_type": "team_roster",
            "cycle_id": cycle_for_rosters["_id"],
            "coach_discord_id": coach["coach_discord_id"],
        }
        submitted_at = now - timedelta(hours=3) if coach["status"] in {"SUBMITTED", "APPROVED"} else None
        roster_doc = {
            "record_type": "team_roster",
            "cycle_id": cycle_for_rosters["_id"],
            "coach_discord_id": coach["coach_discord_id"],
            "team_name": coach["team_name"],
            "practice_times": coach["practice_times"],
            "cap": coach["cap"],
            "status": coach["status"],
            "created_at": now - timedelta(days=2),
            "updated_at": now,
            "submitted_at": submitted_at,
            "seed_tag": seed_tag,
        }
        _replace_one(rosters_col, filter_doc=roster_filter, doc=roster_doc)
        roster = rosters_col.find_one(roster_filter)
        if roster is None:
            raise RuntimeError("Failed to upsert a seeded roster.")
        roster_docs.append(roster)

        # Players
        count = int(coach["player_count"])
        for p_idx in range(count):
            player_id = 999_100_000_000_000_000 + (idx * 1000) + p_idx + 1
            player_doc = {
                "record_type": "roster_player",
                "roster_id": roster["_id"],
                "player_discord_id": player_id,
                "gamertag": f"SeedPlayer{idx}-{p_idx + 1}",
                "ea_id": f"EA-SEED-{idx}-{p_idx + 1}",
                "console": "PS",
                "added_at": now - timedelta(days=1, minutes=p_idx),
                "seed_tag": seed_tag,
            }
            _replace_one(
                roster_players_col,
                filter_doc={
                    "record_type": "roster_player",
                    "roster_id": roster["_id"],
                    "player_discord_id": player_id,
                },
                doc=player_doc,
            )

        # Submission record (only for submitted/approved)
        if coach["status"] in {"SUBMITTED", "APPROVED"}:
            sub_status = "APPROVED" if coach["status"] == "APPROVED" else "PENDING"
            submission_doc = {
                "record_type": "submission_message",
                "roster_id": roster["_id"],
                "staff_channel_id": 999_700_000_000_000_001,
                "staff_message_id": 999_700_000_000_000_002 + idx,
                "status": sub_status,
                "created_at": now - timedelta(hours=2),
                "updated_at": now,
                "seed_tag": seed_tag,
            }
            _replace_one(
                submissions_col,
                filter_doc={"record_type": "submission_message", "roster_id": roster["_id"]},
                doc=submission_doc,
            )

        # Audit events
        for event_idx, (action, details) in enumerate(
            [
                ("TIER_CHANGED", {"tier": "seed", "desired_cap": coach["cap"]}),
                ("CAP_SYNCED", {"from_cap": coach["cap"], "to_cap": coach["cap"]}),
            ],
            start=1,
        ):
            audit_doc = {
                "record_type": "roster_audit",
                "roster_id": roster["_id"],
                "action": action,
                "staff_discord_id": seed_staff_id,
                "staff_display_name": "Seed Staff",
                "staff_username": "seed_staff#0001",
                "details": details,
                "created_at": now - timedelta(hours=1, minutes=event_idx),
                "seed_tag": seed_tag,
                "seed_key": f"roster:{idx}:{action.lower()}",
            }
            _replace_one(
                audits_col,
                filter_doc={"record_type": "roster_audit", "seed_tag": seed_tag, "seed_key": audit_doc["seed_key"]},
                doc=audit_doc,
            )

    # --- coaches / managers / players / leagues / stats ---
    coaches_col = collections["coaches"]
    managers_col = collections["managers"]
    players_col = collections["players"]
    leagues_col = collections["leagues"]
    stats_col = collections["stats"]

    manager_doc = {
        "record_type": "manager",
        "guild_id": guild_id,
        "user_id": seed_staff_id,
        "display_name": "Seed Staff",
        "username": "seed_staff#0001",
        "created_at": now - timedelta(days=30),
        "updated_at": now,
        "seed_tag": seed_tag,
    }
    _replace_one(
        managers_col,
        filter_doc={"record_type": "manager", "guild_id": guild_id, "user_id": seed_staff_id},
        doc=manager_doc,
    )

    for roster in roster_docs:
        coach_id = roster.get("coach_discord_id")
        if not isinstance(coach_id, int):
            continue
        cap = int(roster.get("cap") or 0)
        tier = "club_manager" if cap >= 22 else "team_coach"
        coach_doc = {
            "record_type": "coach",
            "guild_id": guild_id,
            "user_id": coach_id,
            "tier": tier,
            "cap": cap,
            "team_name": roster.get("team_name"),
            "practice_times": roster.get("practice_times"),
            "active_roster_id": roster.get("_id"),
            "created_at": now - timedelta(days=7),
            "updated_at": now,
            "seed_tag": seed_tag,
        }
        _replace_one(
            coaches_col,
            filter_doc={"record_type": "coach", "guild_id": guild_id, "user_id": coach_id},
            doc=coach_doc,
        )

    for player in roster_players_col.find({"record_type": "roster_player", "seed_tag": seed_tag}):
        user_id = player.get("player_discord_id")
        if not isinstance(user_id, int):
            continue
        player_doc = {
            "record_type": "player",
            "guild_id": guild_id,
            "user_id": user_id,
            "gamertag": player.get("gamertag"),
            "ea_id": player.get("ea_id"),
            "console": player.get("console"),
            "created_at": now - timedelta(days=14),
            "updated_at": now,
            "seed_tag": seed_tag,
        }
        _replace_one(
            players_col,
            filter_doc={"record_type": "player", "guild_id": guild_id, "user_id": user_id},
            doc=player_doc,
        )

    league_name = f"[SEED:{seed_tag}] Offside League"
    league_doc = {
        "record_type": "league",
        "guild_id": guild_id,
        "name": league_name,
        "season": "2025",
        "created_at": now - timedelta(days=10),
        "updated_at": now,
        "seed_tag": seed_tag,
    }
    _replace_one(
        leagues_col,
        filter_doc={"record_type": "league", "guild_id": guild_id, "name": league_name},
        doc=league_doc,
    )

    stat_events = [
        ("seed_run", {"tag": seed_tag}),
        ("rosters_seeded", {"count": len(roster_docs)}),
        ("players_seeded", {"count": roster_players_col.count_documents({"seed_tag": seed_tag})}),
    ]
    for idx, (event_type, payload) in enumerate(stat_events, start=1):
        stat_doc = {
            "record_type": "stat",
            "guild_id": guild_id,
            "type": event_type,
            "payload": payload,
            "created_at": now - timedelta(minutes=idx),
            "seed_tag": seed_tag,
            "seed_key": f"stat:{event_type}",
        }
        _replace_one(
            stats_col,
            filter_doc={"record_type": "stat", "seed_tag": seed_tag, "seed_key": stat_doc["seed_key"]},
            doc=stat_doc,
        )

    # --- recruit_profiles ---
    recruits_col = collections["recruit_profiles"]
    recruit_users = [
        {
            "user_id": 999_200_000_000_000_001,
            "display_name": "Seed Striker",
            "user_tag": "seed_striker#0001",
            "main_position": "ST",
            "secondary_position": "RW",
            "main_archetype": "target man",
            "secondary_archetype": "inverted winger",
            "platform": "PS",
            "mic": True,
            "server_name": "na east",
            "timezone": "UTC",
            "availability_days": [0, 2, 4],
            "availability_start_hour": 19,
            "availability_end_hour": 22,
            "notes": "Looking for competitive clubs. Prefer late evenings.",
        },
        {
            "user_id": 999_200_000_000_000_002,
            "display_name": "Seed Centerback",
            "user_tag": "seed_cb#0002",
            "main_position": "CB",
            "secondary_position": "LB",
            "main_archetype": "ball playing defender",
            "secondary_archetype": "overlap fullback",
            "platform": "XBOX",
            "mic": False,
            "server_name": "eu",
            "timezone": "UTC",
            "availability_days": [1, 3],
            "availability_start_hour": 18,
            "availability_end_hour": 21,
            "notes": "Calm on the ball. Happy to trial.",
        },
        {
            "user_id": 999_200_000_000_000_003,
            "display_name": "Seed Midfielder",
            "user_tag": "seed_cm#0003",
            "main_position": "CM",
            "secondary_position": "CDM",
            "main_archetype": "box to box",
            "secondary_archetype": "deep lying playmaker",
            "platform": "PC",
            "mic": True,
            "server_name": "na west",
            "timezone": "UTC",
            "availability_days": [5, 6],
            "availability_start_hour": 17,
            "availability_end_hour": 20,
            "notes": "Weekend grinder. Likes structured tactics.",
        },
    ]
    for recruit in recruit_users:
        recruit_doc = {
            "record_type": "recruit_profile",
            "guild_id": guild_id,
            "user_id": recruit["user_id"],
            "display_name": recruit["display_name"],
            "user_tag": recruit["user_tag"],
            "age": 21,
            "platform": recruit["platform"],
            "mic": recruit["mic"],
            "main_position": recruit["main_position"],
            "secondary_position": recruit["secondary_position"],
            "main_archetype": recruit["main_archetype"],
            "secondary_archetype": recruit["secondary_archetype"],
            "server_name": recruit["server_name"],
            "timezone": recruit["timezone"],
            "availability_days": recruit["availability_days"],
            "availability_start_hour": recruit["availability_start_hour"],
            "availability_end_hour": recruit["availability_end_hour"],
            "notes": recruit["notes"],
            "created_at": now - timedelta(days=7),
            "updated_at": now,
            "seed_tag": seed_tag,
        }
        _replace_one(
            recruits_col,
            filter_doc={"record_type": "recruit_profile", "guild_id": guild_id, "user_id": recruit["user_id"]},
            doc=recruit_doc,
        )

    # --- club_ads + club_ad_audits ---
    club_ads_col = collections["club_ads"]
    club_audits_col = collections["club_ad_audits"]
    club_ads = [
        {
            "owner_id": 999_300_000_000_000_001,
            "club_name": f"[SEED:{seed_tag}] Offside United",
            "region": "NA",
            "timezone": "UTC",
            "formation": "4-2-3-1",
            "positions_needed": ["ST", "CM", "RB"],
            "keywords": ["competitive", "structured", "mics preferred"],
            "description": "Looking for disciplined players to fill out the squad. Trials open.",
            "contact": "DM the owner or reply in #club-listing.",
            "approval_status": "approved",
        },
        {
            "owner_id": 999_300_000_000_000_002,
            "club_name": f"[SEED:{seed_tag}] Retro FC",
            "region": "EU",
            "timezone": "UTC",
            "formation": "4-3-3",
            "positions_needed": ["LW", "CB"],
            "keywords": ["casual", "friendly"],
            "description": "Chill environment with scheduled practice.",
            "contact": "Ping @ClubOwner.",
            "approval_status": "pending",
        },
    ]
    for idx, ad in enumerate(club_ads, start=1):
        ad_filter = {"record_type": "club_ad", "guild_id": guild_id, "owner_id": ad["owner_id"]}
        ad_doc = {
            "record_type": "club_ad",
            "guild_id": guild_id,
            "owner_id": ad["owner_id"],
            "club_name": ad["club_name"],
            "region": ad["region"],
            "timezone": ad["timezone"],
            "formation": ad["formation"],
            "positions_needed": ad["positions_needed"],
            "keywords": ad["keywords"],
            "description": ad["description"],
            "contact": ad["contact"],
            "tryout_at": now + timedelta(days=2, hours=idx),
            "approval_status": ad["approval_status"],
            "approval_staff_discord_id": seed_staff_id if ad["approval_status"] == "approved" else None,
            "approval_reason": None,
            "approval_at": now - timedelta(days=1) if ad["approval_status"] == "approved" else None,
            "created_at": now - timedelta(days=3),
            "updated_at": now,
            "seed_tag": seed_tag,
        }
        _replace_one(club_ads_col, filter_doc=ad_filter, doc=ad_doc)

        audit_doc = {
            "record_type": "club_ad_audit",
            "guild_id": guild_id,
            "owner_id": ad["owner_id"],
            "action": "APPROVED" if ad["approval_status"] == "approved" else "REJECTED",
            "staff_discord_id": seed_staff_id,
            "reason": None if ad["approval_status"] == "approved" else "Seed rejection example.",
            "created_at": now - timedelta(hours=4, minutes=idx),
            "seed_tag": seed_tag,
            "seed_key": f"club_ad:{idx}:audit",
        }
        _replace_one(
            club_audits_col,
            filter_doc={"record_type": "club_ad_audit", "seed_tag": seed_tag, "seed_key": audit_doc["seed_key"]},
            doc=audit_doc,
        )

    # --- fc25_stats_links + fc25_stats_snapshots ---
    links_col = collections["fc25_stats_links"]
    snapshots_col = collections["fc25_stats_snapshots"]
    for idx, recruit in enumerate(recruit_users[:2], start=1):
        user_id = int(recruit["user_id"])
        link_filter = {"record_type": "fc25_stats_link", "guild_id": guild_id, "user_id": user_id}
        link_doc = {
            "record_type": "fc25_stats_link",
            "guild_id": guild_id,
            "user_id": user_id,
            "platform_key": "common-gen5",
            "club_id": 424242 + idx,
            "club_name": f"Seed Club {idx}",
            "member_name": recruit["display_name"],
            "verified": True,
            "verified_at": now - timedelta(days=2),
            "last_fetched_at": now - timedelta(minutes=15 * idx),
            "last_fetch_status": "ok",
            "created_at": now - timedelta(days=2),
            "updated_at": now,
            "seed_tag": seed_tag,
        }
        _replace_one(links_col, filter_doc=link_filter, doc=link_doc)

        snapshot_filter = {
            "record_type": "fc25_stats_snapshot",
            "seed_tag": seed_tag,
            "seed_key": f"fc25_snapshot:{idx}",
        }
        snapshot_doc = {
            "record_type": "fc25_stats_snapshot",
            "guild_id": guild_id,
            "user_id": user_id,
            "platform_key": "common-gen5",
            "club_id": 424242 + idx,
            "snapshot": {
                "member_stats": {"gamesPlayed": 42, "goals": 12 + idx, "assists": 9, "ratingAve": 7.8},
                "club": {"name": f"Seed Club {idx}", "id": 424242 + idx},
            },
            "fetched_at": now - timedelta(minutes=5 * idx),
            "seed_tag": seed_tag,
            "seed_key": snapshot_filter["seed_key"],
        }
        _replace_one(snapshots_col, filter_doc=snapshot_filter, doc=snapshot_doc)

    # --- tournaments + participants + matches ---
    tournaments_col = collections["tournaments"]
    participants_col = collections["tournament_participants"]
    matches_col = collections["tournament_matches"]

    tournament_name = f"[SEED:{seed_tag}] Demo Cup"
    tournament_filter = {"record_type": "tournament", "name": tournament_name}
    tournament_doc = {
        "record_type": "tournament",
        "name": tournament_name,
        "format": "single_elimination",
        "rules": "Best of 1. Seed data for local testing.",
        "matches_channel_id": None,
        "disputes_channel_id": None,
        "state": "IN_PROGRESS",
        "created_at": now - timedelta(days=10),
        "updated_at": now,
        "seed_tag": seed_tag,
    }
    _replace_one(tournaments_col, filter_doc=tournament_filter, doc=tournament_doc)
    tournament = tournaments_col.find_one(tournament_filter)
    if tournament is None:
        raise RuntimeError("Failed to upsert seeded tournament.")

    teams = [
        ("Seed Team A", coaches[0]["coach_discord_id"], 1),
        ("Seed Team B", coaches[1]["coach_discord_id"], 2),
        ("Seed Team C", coaches[2]["coach_discord_id"], 3),
        ("Seed Team D", coaches[2]["coach_discord_id"], 4),
    ]
    participants: list[dict[str, Any]] = []
    for team_name, coach_id, seed in teams:
        p_filter = {
            "record_type": "tournament_participant",
            "tournament": tournament["_id"],
            "team_name": team_name,
        }
        p_doc = {
            "record_type": "tournament_participant",
            "tournament": tournament["_id"],
            "team_name": team_name,
            "coach_id": coach_id,
            "seed": seed,
            "created_at": now - timedelta(days=10),
            "updated_at": now,
            "seed_tag": seed_tag,
        }
        _replace_one(participants_col, filter_doc=p_filter, doc=p_doc)
        participant = participants_col.find_one(p_filter)
        if participant is None:
            raise RuntimeError("Failed to upsert tournament participant.")
        participants.append(participant)

    def _p(name: str) -> dict[str, Any]:
        for p_doc in participants:
            if p_doc.get("team_name") == name:
                return p_doc
        raise KeyError(name)

    match_defs = [
        (1, 1, _p("Seed Team A")["_id"], _p("Seed Team B")["_id"], "COMPLETED", _p("Seed Team A")["_id"]),
        (1, 2, _p("Seed Team C")["_id"], _p("Seed Team D")["_id"], "PENDING", None),
    ]
    for round_no, seq, a_id, b_id, status, winner in match_defs:
        m_filter = {
            "record_type": "tournament_match",
            "tournament": tournament["_id"],
            "round": round_no,
            "sequence": seq,
        }
        scores: dict[str, Any] = {}
        disputes: list[dict[str, Any]] = []
        if status == "COMPLETED":
            scores = {str(a_id): {"for": 2, "against": 1, "reported_at": now - timedelta(days=1)}}
            disputes = [
                {
                    "filed_by": coaches[1]["coach_discord_id"],
                    "reason": "Seed dispute example.",
                    "filed_at": now - timedelta(hours=20),
                    "resolved": True,
                    "resolution": "Resolved in seed data.",
                    "resolved_at": now - timedelta(hours=19),
                }
            ]
        m_doc = {
            "record_type": "tournament_match",
            "tournament": tournament["_id"],
            "round": round_no,
            "sequence": seq,
            "team_a": a_id,
            "team_b": b_id,
            "status": status,
            "scores": scores,
            "winner": winner,
            "deadline": "2025-12-31 20:00 UTC",
            "disputes": disputes,
            "reschedule_requests": [],
            "created_at": now - timedelta(days=9),
            "updated_at": now,
            "seed_tag": seed_tag,
        }
        _replace_one(matches_col, filter_doc=m_filter, doc=m_doc)

    # --- group stage collections (tournament_group + group_* records) ---
    groups_col = collections["tournament_groups"]
    group_teams_col = collections["group_teams"]
    group_matches_col = collections["group_matches"]
    group_fixtures_col = collections["group_fixtures"]

    group_name = f"[SEED:{seed_tag}] Group A"
    group_filter = {"record_type": "tournament_group", "tournament": tournament["_id"], "name": group_name}
    group_doc = {
        "record_type": "tournament_group",
        "tournament": tournament["_id"],
        "name": group_name,
        "created_at": now - timedelta(days=8),
        "updated_at": now,
        "seed_tag": seed_tag,
    }
    _replace_one(groups_col, filter_doc=group_filter, doc=group_doc)
    group = groups_col.find_one(group_filter)
    if group is None:
        raise RuntimeError("Failed to upsert seeded tournament group.")

    group_team_docs: list[dict[str, Any]] = []
    for t_idx, (team_name, coach_id, _) in enumerate(teams[:3], start=1):
        gt_filter = {
            "record_type": "group_team",
            "group_id": group["_id"],
            "team_name": team_name,
        }
        gt_doc = {
            "record_type": "group_team",
            "group_id": group["_id"],
            "tournament": tournament["_id"],
            "team_name": team_name,
            "coach_id": coach_id,
            "played": 1 if t_idx == 1 else 0,
            "wins": 1 if t_idx == 1 else 0,
            "draws": 0,
            "losses": 0 if t_idx == 1 else 0,
            "gf": 2 if t_idx == 1 else 0,
            "ga": 1 if t_idx == 1 else 0,
            "points": 3 if t_idx == 1 else 0,
            "created_at": now - timedelta(days=8),
            "updated_at": now,
            "seed_tag": seed_tag,
        }
        _replace_one(group_teams_col, filter_doc=gt_filter, doc=gt_doc)
        gt = group_teams_col.find_one(gt_filter)
        if gt is None:
            raise RuntimeError("Failed to upsert seeded group team.")
        group_team_docs.append(gt)

    if len(group_team_docs) >= 2:
        gm_filter = {"record_type": "group_match", "seed_tag": seed_tag, "seed_key": "group_match:1"}
        gm_doc = {
            "record_type": "group_match",
            "group_id": group["_id"],
            "tournament": tournament["_id"],
            "team_a": group_team_docs[0]["_id"],
            "team_b": group_team_docs[1]["_id"],
            "score_a": 2,
            "score_b": 1,
            "played_at": now - timedelta(days=1),
            "seed_tag": seed_tag,
            "seed_key": "group_match:1",
        }
        _replace_one(group_matches_col, filter_doc=gm_filter, doc=gm_doc)

        # A couple fixtures using team IDs (as generated by group fixture logic)
        fixtures = [
            (1, 1, group_team_docs[0]["_id"], group_team_docs[1]["_id"]),
            (1, 2, group_team_docs[1]["_id"], group_team_docs[2]["_id"] if len(group_team_docs) > 2 else None),
        ]
        for rnd, seq, a_id, b_id in fixtures:
            gf_filter = {"record_type": "group_fixture", "group_id": group["_id"], "round": rnd, "sequence": seq}
            gf_doc = {
                "record_type": "group_fixture",
                "group_id": group["_id"],
                "tournament": tournament["_id"],
                "round": rnd,
                "sequence": seq,
                "team_a": a_id,
                "team_b": b_id,
                "created_at": now - timedelta(days=7),
                "seed_tag": seed_tag,
            }
            _replace_one(group_fixtures_col, filter_doc=gf_filter, doc=gf_doc)

    logging.info("Seed data complete (db=%s, seed_tag=%s, guild_id=%s).", db_name, seed_tag, guild_id)


if __name__ == "__main__":
    main()
