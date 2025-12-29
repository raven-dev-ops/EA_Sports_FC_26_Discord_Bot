from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from utils.validation import normalize_platform

FC25_PLATFORM_KEYS: dict[str, str] = {
    "PC": "common-pc",
    "PS5": "common-gen5",
}


def platform_key_from_user_input(value: str | None, *, default: str) -> str | None:
    """
    Map a user-facing platform label (PC/PS5) to the FC25 Clubs API platform key.
    """
    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    normalized = normalize_platform(cleaned)
    if normalized is None:
        return None
    return FC25_PLATFORM_KEYS.get(normalized, default)


def parse_club_id_from_url(value: str) -> int | None:
    """
    Extract a numeric club ID from a raw club ID input or a club URL.
    """
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        try:
            return int(cleaned)
        except ValueError:
            return None

    parsed = None
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        parsed = None

    if parsed and parsed.scheme and parsed.netloc:
        query = parse_qs(parsed.query)
        for key in ("clubId", "clubid", "club_id"):
            values = query.get(key)
            if not values:
                continue
            match = re.search(r"(\d+)", str(values[0]))
            if match:
                return int(match.group(1))

        match = re.search(r"/clubid/(\d+)", parsed.path, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

    match = re.search(r"(\d+)", cleaned)
    if match:
        return int(match.group(1))
    return None

