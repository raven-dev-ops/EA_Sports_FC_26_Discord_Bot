from __future__ import annotations

import logging
import re
from typing import Iterable

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from config import Settings, load_settings

INVALID_DB_NAME_PATTERN = re.compile(r'[\\/\.\s"$\x00]')
_CLIENT: MongoClient | None = None


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


def get_client(settings: Settings | None = None) -> MongoClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    settings = _settings_or_default(settings)
    uri = _require_value(settings.mongodb_uri, "MONGODB_URI")
    _CLIENT = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return _CLIENT


def get_database(settings: Settings | None = None) -> Database:
    settings = _settings_or_default(settings)
    db_name = _require_value(settings.mongodb_db_name, "MONGODB_DB_NAME")
    db_name = _normalize_db_name(db_name)
    return get_client(settings)[db_name]


def get_collection(settings: Settings | None = None) -> Collection:
    settings = _settings_or_default(settings)
    collection_name = _require_value(settings.mongodb_collection, "MONGODB_COLLECTION")
    return get_database(settings)[collection_name]


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

    return indexes


def list_record_types() -> Iterable[str]:
    return (
        "tournament_cycle",
        "team_roster",
        "roster_player",
        "submission_message",
        "roster_audit",
    )
