from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def format_dt(dt: datetime, tz: str = "UTC") -> str:
    """
    Format a timezone-aware datetime in the provided IANA timezone.
    Falls back to UTC if the zone is invalid.
    """
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = ZoneInfo("UTC")
    localized = dt.astimezone(zone)
    return localized.strftime("%Y-%m-%d %H:%M %Z")
