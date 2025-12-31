from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterable, Iterator

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from config import Settings, load_settings

INVALID_DB_NAME_PATTERN = re.compile(r'[\\/\.\s"$\x00]')
_CLIENT: MongoClient | None = None
_CURRENT_GUILD_ID: ContextVar[int | None] = ContextVar("offside_current_guild_id", default=None)

DEFAULT_DB_NAME = "OffsideDiscordBot"

# One collection per record type (recommended). We keep the record_type field in documents for
# backward compatibility and easier debugging, but physical separation makes indexes simpler.
COLLECTION_BY_RECORD_TYPE: dict[str, str] = {
    "coach": "coaches",
    "manager": "managers",
    "player": "players",
    "league": "leagues",
    "stat": "stats",
    "guild_settings": "guild_settings",
    "tournament_cycle": "tournament_cycles",
    "team_roster": "team_rosters",
    "roster_player": "roster_players",
    "submission_message": "submission_messages",
    "roster_audit": "roster_audits",
    "audit_event": "audit_events",
    "recruit_profile": "recruit_profiles",
    "club_ad": "club_ads",
    "club_ad_audit": "club_ad_audits",
    "fc25_stats_link": "fc25_stats_links",
    "fc25_stats_snapshot": "fc25_stats_snapshots",
    "tournament": "tournaments",
    "tournament_participant": "tournament_participants",
    "tournament_match": "tournament_matches",
    "tournament_group": "tournament_groups",
    "group_team": "group_teams",
    "group_match": "group_matches",
    "group_fixture": "group_fixtures",
}

# Legacy single-collection mode (stores many record types in one collection).
LEGACY_DEFAULT_COLLECTION_NAME = "offside_records"


def _require_value(value: str | None, name: str) -> str:
    if not value:
        raise RuntimeError(f"{name} is required for database access.")
    return value


def _normalize_db_name(name: str) -> str:
    normalized = INVALID_DB_NAME_PATTERN.sub("_", name.strip())
    if not normalized:
        raise RuntimeError("MONGODB_DB_NAME resolved to empty after sanitization.")
    if len(normalized.encode("utf-8")) > 63:
        raise RuntimeError("MONGODB_DB_NAME exceeds MongoDB length limits.")
    if normalized != name:
        logging.warning(
            "Normalized MONGODB_DB_NAME from %r to %r to satisfy MongoDB naming rules.",
            name,
            normalized,
        )
    return normalized


def _settings_or_default(settings: Settings | None) -> Settings:
    return settings or load_settings()


def get_current_guild_id() -> int | None:
    return _CURRENT_GUILD_ID.get()


def set_current_guild_id(guild_id: int | None) -> None:
    _CURRENT_GUILD_ID.set(guild_id)


@contextmanager
def guild_db_context(guild_id: int | None) -> Iterator[None]:
    token = _CURRENT_GUILD_ID.set(guild_id)
    try:
        yield
    finally:
        _CURRENT_GUILD_ID.reset(token)


def _resolve_db_name(settings: Settings, *, guild_id: int | None) -> str:
    if settings.mongodb_per_guild_db:
        resolved = guild_id if guild_id is not None else _CURRENT_GUILD_ID.get()
        if resolved is None:
            raise RuntimeError(
                "guild_id is required when MONGODB_PER_GUILD_DB is enabled (set context or pass guild_id)."
            )
        prefix = settings.mongodb_guild_db_prefix or ""
        return f"{prefix}{resolved}"
    return settings.mongodb_db_name or DEFAULT_DB_NAME


def get_client(settings: Settings | None = None) -> MongoClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    settings = _settings_or_default(settings)
    uri = _require_value(settings.mongodb_uri, "MONGODB_URI")
    _CLIENT = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return _CLIENT


def get_database(settings: Settings | None = None, *, guild_id: int | None = None) -> Database:
    settings = _settings_or_default(settings)
    db_name = _resolve_db_name(settings, guild_id=guild_id)
    db_name = _normalize_db_name(db_name)
    return get_client(settings)[db_name]


def get_global_database(settings: Settings | None = None) -> Database:
    """
    Return the global (non per-guild) database used for shared data like web sessions.

    This intentionally ignores MONGODB_PER_GUILD_DB so the web/dashboard can store cross-guild
    state even when the bot uses per-guild databases for feature data.
    """
    settings = _settings_or_default(settings)
    db_name = _normalize_db_name(settings.mongodb_db_name or DEFAULT_DB_NAME)
    return get_client(settings)[db_name]


def get_global_collection(settings: Settings | None = None, *, name: str) -> Collection:
    return get_global_database(settings)[name]


def get_collection(
    settings: Settings | None = None,
    *,
    name: str | None = None,
    record_type: str | None = None,
    guild_id: int | None = None,
) -> Collection:
    settings = _settings_or_default(settings)
    if name is not None and record_type is not None:
        raise RuntimeError("Pass only one of `name` or `record_type` to get_collection().")
    if record_type is not None:
        if settings.mongodb_collection:
            name = settings.mongodb_collection
        else:
            mapped = COLLECTION_BY_RECORD_TYPE.get(record_type)
            if not mapped:
                raise RuntimeError(
                    f"Unknown record_type {record_type!r}; update COLLECTION_BY_RECORD_TYPE."
                )
            name = mapped
    if name is None:
        name = settings.mongodb_collection or LEGACY_DEFAULT_COLLECTION_NAME
    db_name = _resolve_db_name(settings, guild_id=guild_id)
    db = get_client(settings)[_normalize_db_name(db_name)]
    return db[name]


def get_collection_for_record_type(
    record_type: str,
    settings: Settings | None = None,
) -> Collection:
    return get_collection(settings, record_type=record_type)


def ping(settings: Settings | None = None) -> None:
    client = get_client(settings)
    client.admin.command("ping")


def close_client() -> None:
    """
    Close the cached Mongo client (used during graceful shutdown).
    """
    global _CLIENT
    if _CLIENT is not None:
        _CLIENT.close()
        _CLIENT = None


def ensure_indexes(collection: Collection) -> list[str]:
    indexes: list[str] = []

    indexes.append(collection.create_index([("record_type", 1)]))
    indexes.append(collection.create_index("expires_at", expireAfterSeconds=0, name="ttl_expires_at"))
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1), ("created_at", -1)],
            name="idx_audit_event",
            partialFilterExpression={"record_type": "audit_event"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_coach",
            partialFilterExpression={"record_type": "coach"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_manager",
            partialFilterExpression={"record_type": "manager"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_player",
            partialFilterExpression={"record_type": "player"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1), ("name", 1)],
            unique=True,
            name="uniq_league",
            partialFilterExpression={"record_type": "league"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1), ("type", 1), ("created_at", -1)],
            name="idx_stats",
            partialFilterExpression={"record_type": "stat"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("cycle_id", 1), ("coach_discord_id", 1)],
            unique=True,
            name="uniq_roster_by_coach",
            partialFilterExpression={"record_type": "team_roster"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("roster_id", 1), ("player_discord_id", 1)],
            unique=True,
            name="uniq_roster_player",
            partialFilterExpression={"record_type": "roster_player"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("roster_id", 1), ("staff_message_id", 1)],
            unique=True,
            name="uniq_submission_message",
            partialFilterExpression={"record_type": "submission_message"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("roster_id", 1), ("created_at", -1)],
            name="idx_roster_audit",
            partialFilterExpression={"record_type": "roster_audit"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1)],
            name="uniq_guild_settings",
            unique=True,
            partialFilterExpression={"record_type": "guild_settings"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_recruit_profile",
            partialFilterExpression={"record_type": "recruit_profile"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1), ("owner_id", 1)],
            unique=True,
            name="uniq_club_ad_by_owner",
            partialFilterExpression={"record_type": "club_ad"},
        )
    )
    indexes.append(
        collection.create_index(
            [
                ("record_type", 1),
                ("guild_id", 1),
                ("main_position", 1),
                ("main_archetype", 1),
                ("server_name", 1),
                ("updated_at", -1),
            ],
            name="idx_recruit_profile_filters",
            partialFilterExpression={"record_type": "recruit_profile"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_fc25_stats_link",
            partialFilterExpression={"record_type": "fc25_stats_link"},
        )
    )
    indexes.append(
        collection.create_index(
            [("record_type", 1), ("guild_id", 1), ("user_id", 1), ("fetched_at", -1)],
            name="idx_fc25_stats_snapshot_user",
            partialFilterExpression={"record_type": "fc25_stats_snapshot"},
        )
    )

    return indexes


def ensure_offside_indexes(db: Database) -> list[str]:
    """
    Create/update indexes for the recommended multi-collection schema.
    """
    indexes: list[str] = []

    coaches = db[COLLECTION_BY_RECORD_TYPE["coach"]]
    indexes.append(
        coaches.create_index(
            [("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_coach",
        )
    )
    managers = db[COLLECTION_BY_RECORD_TYPE["manager"]]
    indexes.append(
        managers.create_index(
            [("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_manager",
        )
    )
    players = db[COLLECTION_BY_RECORD_TYPE["player"]]
    indexes.append(
        players.create_index(
            [("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_player",
        )
    )
    leagues = db[COLLECTION_BY_RECORD_TYPE["league"]]
    indexes.append(
        leagues.create_index(
            [("guild_id", 1), ("name", 1)],
            unique=True,
            name="uniq_league",
        )
    )
    stats = db[COLLECTION_BY_RECORD_TYPE["stat"]]
    indexes.append(stats.create_index([("guild_id", 1), ("type", 1), ("created_at", -1)], name="idx_stats"))

    guild_settings = db[COLLECTION_BY_RECORD_TYPE["guild_settings"]]
    indexes.append(guild_settings.create_index([("guild_id", 1)], unique=True, name="uniq_guild_settings"))

    tournament_cycles = db[COLLECTION_BY_RECORD_TYPE["tournament_cycle"]]
    indexes.append(tournament_cycles.create_index([("name", 1)], unique=True, name="uniq_cycle_name"))
    indexes.append(tournament_cycles.create_index([("is_active", 1)], name="idx_cycle_active"))

    team_rosters = db[COLLECTION_BY_RECORD_TYPE["team_roster"]]
    indexes.append(
        team_rosters.create_index(
            [("cycle_id", 1), ("coach_discord_id", 1)],
            unique=True,
            name="uniq_roster_by_coach",
        )
    )
    indexes.append(
        team_rosters.create_index(
            [("coach_discord_id", 1), ("created_at", -1)],
            name="idx_rosters_by_coach",
        )
    )
    indexes.append(
        team_rosters.create_index(
            [("cycle_id", 1), ("status", 1), ("updated_at", -1)],
            name="idx_rosters_by_cycle_status",
        )
    )

    roster_players = db[COLLECTION_BY_RECORD_TYPE["roster_player"]]
    indexes.append(
        roster_players.create_index(
            [("roster_id", 1), ("player_discord_id", 1)],
            unique=True,
            name="uniq_roster_player",
        )
    )
    indexes.append(
        roster_players.create_index(
            [("roster_id", 1), ("added_at", 1)],
            name="idx_roster_players_by_roster",
        )
    )

    submission_messages = db[COLLECTION_BY_RECORD_TYPE["submission_message"]]
    indexes.append(
        submission_messages.create_index(
            [("roster_id", 1)],
            unique=True,
            name="uniq_submission_by_roster",
        )
    )
    indexes.append(
        submission_messages.create_index(
            [("staff_message_id", 1)],
            unique=True,
            sparse=True,
            name="uniq_submission_staff_message",
        )
    )

    roster_audits = db[COLLECTION_BY_RECORD_TYPE["roster_audit"]]
    indexes.append(
        roster_audits.create_index(
            [("roster_id", 1), ("created_at", -1)],
            name="idx_roster_audit",
        )
    )
    indexes.append(roster_audits.create_index("expires_at", expireAfterSeconds=0, name="ttl_expires_at"))

    audit_events = db[COLLECTION_BY_RECORD_TYPE["audit_event"]]
    indexes.append(
        audit_events.create_index(
            [("guild_id", 1), ("created_at", -1)],
            name="idx_audit_events_guild",
        )
    )
    indexes.append(
        audit_events.create_index(
            [("category", 1), ("created_at", -1)],
            name="idx_audit_events_category",
        )
    )
    indexes.append(audit_events.create_index("expires_at", expireAfterSeconds=0, name="ttl_expires_at"))

    recruit_profiles = db[COLLECTION_BY_RECORD_TYPE["recruit_profile"]]
    indexes.append(
        recruit_profiles.create_index(
            [("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_recruit_profile",
        )
    )
    indexes.append(
        recruit_profiles.create_index(
            [
                ("guild_id", 1),
                ("main_position", 1),
                ("main_archetype", 1),
                ("server_name", 1),
                ("updated_at", -1),
            ],
            name="idx_recruit_profile_filters",
        )
    )

    club_ads = db[COLLECTION_BY_RECORD_TYPE["club_ad"]]
    indexes.append(
        club_ads.create_index(
            [("guild_id", 1), ("owner_id", 1)],
            unique=True,
            name="uniq_club_ad_by_owner",
        )
    )

    club_ad_audits = db[COLLECTION_BY_RECORD_TYPE["club_ad_audit"]]
    indexes.append(
        club_ad_audits.create_index(
            [("guild_id", 1), ("owner_id", 1), ("created_at", -1)],
            name="idx_club_ad_audit",
        )
    )
    indexes.append(club_ad_audits.create_index("expires_at", expireAfterSeconds=0, name="ttl_expires_at"))

    fc25_links = db[COLLECTION_BY_RECORD_TYPE["fc25_stats_link"]]
    indexes.append(
        fc25_links.create_index(
            [("guild_id", 1), ("user_id", 1)],
            unique=True,
            name="uniq_fc25_stats_link",
        )
    )
    fc25_snapshots = db[COLLECTION_BY_RECORD_TYPE["fc25_stats_snapshot"]]
    indexes.append(
        fc25_snapshots.create_index(
            [("guild_id", 1), ("user_id", 1), ("fetched_at", -1)],
            name="idx_fc25_stats_snapshot_user",
        )
    )

    tournaments = db[COLLECTION_BY_RECORD_TYPE["tournament"]]
    indexes.append(tournaments.create_index([("name", 1)], unique=True, name="uniq_tournament_name"))

    tournament_participants = db[COLLECTION_BY_RECORD_TYPE["tournament_participant"]]
    indexes.append(
        tournament_participants.create_index(
            [("tournament", 1), ("team_name", 1)],
            unique=True,
            name="uniq_tournament_participant_team",
        )
    )
    indexes.append(
        tournament_participants.create_index(
            [("tournament", 1), ("seed", 1)],
            name="idx_tournament_participants_seed",
        )
    )

    tournament_matches = db[COLLECTION_BY_RECORD_TYPE["tournament_match"]]
    indexes.append(
        tournament_matches.create_index(
            [("tournament", 1), ("round", 1), ("sequence", 1)],
            unique=True,
            name="uniq_tournament_match_round_sequence",
        )
    )
    indexes.append(
        tournament_matches.create_index(
            [("tournament", 1), ("status", 1), ("round", 1), ("sequence", 1)],
            name="idx_tournament_matches_status",
        )
    )

    tournament_groups = db[COLLECTION_BY_RECORD_TYPE["tournament_group"]]
    indexes.append(
        tournament_groups.create_index(
            [("tournament", 1), ("name", 1)],
            unique=True,
            name="uniq_tournament_group",
        )
    )

    group_teams = db[COLLECTION_BY_RECORD_TYPE["group_team"]]
    indexes.append(
        group_teams.create_index(
            [("group_id", 1), ("team_name", 1)],
            unique=True,
            name="uniq_group_team",
        )
    )
    indexes.append(
        group_teams.create_index(
            [("group_id", 1), ("points", -1), ("gf", -1), ("ga", 1)],
            name="idx_group_team_standings",
        )
    )

    group_matches = db[COLLECTION_BY_RECORD_TYPE["group_match"]]
    indexes.append(group_matches.create_index([("group_id", 1), ("played_at", -1)], name="idx_group_matches"))

    group_fixtures = db[COLLECTION_BY_RECORD_TYPE["group_fixture"]]
    indexes.append(
        group_fixtures.create_index(
            [("group_id", 1), ("round", 1), ("sequence", 1)],
            unique=True,
            name="uniq_group_fixture",
        )
    )

    return indexes


def list_record_types() -> Iterable[str]:
    return tuple(sorted(COLLECTION_BY_RECORD_TYPE.keys()))
