from __future__ import annotations

from datetime import datetime, timedelta, timezone

import mongomock

from config.settings import Settings
from services.ops_tasks_service import (
    OPS_TASK_ACTION_REPOST_PORTALS,
    OPS_TASK_ACTION_RUN_SETUP,
    OPS_TASK_STATUS_CANCELED,
    OPS_TASK_STATUS_FAILED,
    OPS_TASK_STATUS_RUNNING,
    OPS_TASK_STATUS_SUCCEEDED,
    cancel_ops_task,
    claim_next_ops_task,
    enqueue_ops_task,
    get_active_ops_task,
    list_ops_tasks,
    mark_ops_task_failed,
    mark_ops_task_succeeded,
)


def _settings() -> Settings:
    return Settings(
        discord_token="token",
        discord_application_id=1,
        discord_client_id=None,
        discord_public_key=None,
        interactions_endpoint_url=None,
        test_mode=True,
        role_broskie_id=None,
        role_coach_id=None,
        role_coach_premium_id=None,
        role_coach_premium_plus_id=None,
        channel_staff_portal_id=None,
        channel_club_portal_id=None,
        channel_manager_portal_id=None,
        channel_coach_portal_id=None,
        channel_recruit_portal_id=None,
        channel_staff_monitor_id=None,
        channel_roster_listing_id=None,
        channel_recruit_listing_id=None,
        channel_club_listing_id=None,
        channel_premium_coaches_id=None,
        staff_role_ids=set(),
        mongodb_uri="mongodb://localhost",
        mongodb_db_name="testdb",
        mongodb_collection="testcol",
        mongodb_per_guild_db=False,
        mongodb_guild_db_prefix="",
        banlist_sheet_id=None,
        banlist_range=None,
        banlist_cache_ttl_seconds=300,
        google_sheets_credentials_json=None,
    )


def test_enqueue_is_idempotent_for_active_tasks() -> None:
    settings = _settings()
    col = mongomock.MongoClient()["global"]["ops_tasks"]

    first = enqueue_ops_task(
        settings,
        guild_id=123,
        action=OPS_TASK_ACTION_RUN_SETUP,
        requested_by_discord_id=1,
        requested_by_username="alice#0001",
        collection=col,
    )
    second = enqueue_ops_task(
        settings,
        guild_id=123,
        action=OPS_TASK_ACTION_RUN_SETUP,
        requested_by_discord_id=2,
        requested_by_username="bob#0002",
        collection=col,
    )
    assert first["_id"] == second["_id"]

    mark_ops_task_succeeded(settings, task_id=str(first["_id"]), collection=col)
    third = enqueue_ops_task(
        settings,
        guild_id=123,
        action=OPS_TASK_ACTION_RUN_SETUP,
        requested_by_discord_id=3,
        requested_by_username="carol#0003",
        collection=col,
    )
    assert third["_id"] != first["_id"]


def test_claim_and_complete_task() -> None:
    settings = _settings()
    col = mongomock.MongoClient()["global"]["ops_tasks"]

    enqueue_ops_task(
        settings,
        guild_id=1,
        action=OPS_TASK_ACTION_REPOST_PORTALS,
        requested_by_discord_id=None,
        requested_by_username=None,
        collection=col,
    )

    claimed = claim_next_ops_task(settings, worker="bot", collection=col)
    assert claimed is not None
    assert claimed["status"] == OPS_TASK_STATUS_RUNNING

    mark_ops_task_failed(settings, task_id=str(claimed["_id"]), error="boom", collection=col)
    tasks = list_ops_tasks(settings, guild_id=1, limit=5, collection=col)
    assert tasks and tasks[0]["status"] == OPS_TASK_STATUS_FAILED

    enqueue_ops_task(
        settings,
        guild_id=1,
        action=OPS_TASK_ACTION_REPOST_PORTALS,
        requested_by_discord_id=None,
        requested_by_username=None,
        collection=col,
    )
    claimed2 = claim_next_ops_task(settings, worker="bot", collection=col)
    assert claimed2 is not None
    mark_ops_task_succeeded(settings, task_id=str(claimed2["_id"]), result={"ok": True}, collection=col)
    tasks2 = list_ops_tasks(settings, guild_id=1, limit=5, collection=col)
    assert any(t.get("status") == OPS_TASK_STATUS_SUCCEEDED for t in tasks2)


def test_scheduled_tasks_wait_for_run_after() -> None:
    settings = _settings()
    col = mongomock.MongoClient()["global"]["ops_tasks"]

    run_after = datetime.now(timezone.utc) + timedelta(seconds=60)
    task = enqueue_ops_task(
        settings,
        guild_id=1,
        action=OPS_TASK_ACTION_REPOST_PORTALS,
        requested_by_discord_id=None,
        requested_by_username=None,
        run_after=run_after,
        collection=col,
    )

    assert claim_next_ops_task(settings, worker="bot", collection=col) is None

    col.update_one(
        {"_id": task["_id"]},
        {"$set": {"run_after": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )
    claimed = claim_next_ops_task(settings, worker="bot", collection=col)
    assert claimed is not None
    assert claimed["_id"] == task["_id"]


def test_cancel_ops_task_marks_inactive() -> None:
    settings = _settings()
    col = mongomock.MongoClient()["global"]["ops_tasks"]

    first = enqueue_ops_task(
        settings,
        guild_id=123,
        action=OPS_TASK_ACTION_RUN_SETUP,
        requested_by_discord_id=1,
        requested_by_username="alice#0001",
        collection=col,
    )

    assert get_active_ops_task(settings, guild_id=123, action=OPS_TASK_ACTION_RUN_SETUP, collection=col) is not None
    assert cancel_ops_task(settings, guild_id=123, action=OPS_TASK_ACTION_RUN_SETUP, collection=col) is True

    doc = col.find_one({"_id": first["_id"]})
    assert isinstance(doc, dict)
    assert doc["active"] is False
    assert doc["status"] == OPS_TASK_STATUS_CANCELED
    assert get_active_ops_task(settings, guild_id=123, action=OPS_TASK_ACTION_RUN_SETUP, collection=col) is None

    second = enqueue_ops_task(
        settings,
        guild_id=123,
        action=OPS_TASK_ACTION_RUN_SETUP,
        requested_by_discord_id=2,
        requested_by_username="bob#0002",
        collection=col,
    )
    assert second["_id"] != first["_id"]
