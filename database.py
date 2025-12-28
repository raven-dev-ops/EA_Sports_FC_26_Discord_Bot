from __future__ import annotations

from typing import Iterable

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from config import Settings, load_settings


def _require_value(value: str | None, name: str) -> str:
    if not value:
        raise RuntimeError(f"{name} is required for database access.")
    return value


def _settings_or_default(settings: Settings | None) -> Settings:
    return settings or load_settings()


def get_client(settings: Settings | None = None) -> MongoClient:
    settings = _settings_or_default(settings)
    uri = _require_value(settings.mongodb_uri, "MONGODB_URI")
    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def get_database(settings: Settings | None = None) -> Database:
    settings = _settings_or_default(settings)
    db_name = _require_value(settings.mongodb_db_name, "MONGODB_DB_NAME")
    return get_client(settings)[db_name]


def get_collection(settings: Settings | None = None) -> Collection:
    settings = _settings_or_default(settings)
    collection_name = _require_value(settings.mongodb_collection, "MONGODB_COLLECTION")
    return get_database(settings)[collection_name]


def ping(settings: Settings | None = None) -> None:
    client = get_client(settings)
    client.admin.command("ping")


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

    return indexes


def list_record_types() -> Iterable[str]:
    return (
        "tournament_cycle",
        "team_roster",
        "roster_player",
        "submission_message",
        "roster_audit",
    )
