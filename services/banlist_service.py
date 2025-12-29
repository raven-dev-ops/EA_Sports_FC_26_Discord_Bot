from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from config import Settings
from utils.validation import parse_discord_id

_BANLIST_CACHE: dict[str, Any] = {
    "fetched_at": None,
    "entries": {},
}


def _require_setting(value: str | None, name: str) -> str:
    if not value:
        raise RuntimeError(f"{name} is required for ban list checks.")
    return value


def _banlist_configured(settings: Settings) -> bool:
    return bool(
        settings.banlist_sheet_id
        and settings.banlist_range
        and settings.google_sheets_credentials_json
    )


def _fetch_rows(settings: Settings) -> list[list[str]]:
    sheet_id = _require_setting(settings.banlist_sheet_id, "BANLIST_SHEET_ID")
    sheet_range = _require_setting(settings.banlist_range, "BANLIST_RANGE")
    creds_json = _require_setting(
        settings.google_sheets_credentials_json, "GOOGLE_SHEETS_CREDENTIALS_JSON"
    )

    creds_info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    data = spreadsheet.values_get(sheet_range)
    return data.get("values", [])


def _parse_rows(rows: list[list[str]]) -> dict[int, str]:
    if not rows:
        return {}

    header = [cell.strip().lower() for cell in rows[0]]
    discord_idx = header.index("discord_id") if "discord_id" in header else 0
    reason_idx = None
    for key in ("reason", "reason_for_ban"):
        if key in header:
            reason_idx = header.index(key)
            break

    entries: dict[int, str] = {}
    for row in rows[1:]:
        if len(row) <= discord_idx:
            continue
        discord_raw = row[discord_idx]
        discord_id = parse_discord_id(discord_raw)
        if discord_id is None:
            continue
        reason = ""
        if reason_idx is not None and len(row) > reason_idx:
            reason = row[reason_idx].strip()
        entries[discord_id] = reason or "Banned"
    return entries


def _cache_expired(settings: Settings) -> bool:
    fetched_at = _BANLIST_CACHE.get("fetched_at")
    if fetched_at is None:
        return True
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    return age >= settings.banlist_cache_ttl_seconds


def get_banlist(settings: Settings, *, force_refresh: bool = False) -> dict[int, str]:
    if not _banlist_configured(settings):
        return {}
    if force_refresh or _cache_expired(settings):
        rows = _fetch_rows(settings)
        entries = _parse_rows(rows)
        _BANLIST_CACHE["entries"] = entries
        _BANLIST_CACHE["fetched_at"] = datetime.now(timezone.utc)

    return _BANLIST_CACHE.get("entries", {})


def get_ban_reason(settings: Settings, discord_id: int) -> str | None:
    if not _banlist_configured(settings):
        return None
    entries = get_banlist(settings)
    return entries.get(discord_id)
