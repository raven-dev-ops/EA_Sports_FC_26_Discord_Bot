from __future__ import annotations

import json
import os
from pathlib import Path

_LOCALE_CACHE: dict[str, dict[str, str]] = {}
_LOCALES_DIR = Path(__file__).resolve().parents[1] / "locales"


def _load_locale(locale: str) -> dict[str, str]:
    cached = _LOCALE_CACHE.get(locale)
    if cached is not None:
        return cached
    path = _LOCALES_DIR / f"{locale}.json"
    if not path.exists():
        _LOCALE_CACHE[locale] = {}
        return _LOCALE_CACHE[locale]
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    normalized: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str):
            normalized[key] = value
    _LOCALE_CACHE[locale] = normalized
    return normalized


def _current_locale() -> str:
    return os.getenv("APP_LOCALE", "en").strip().lower() or "en"


def t(key: str, default: str | None = None, *, locale: str | None = None) -> str:
    """
    Translate a key using the configured locale, falling back to default or key.
    """
    active_locale = locale or _current_locale()
    table = _load_locale(active_locale)
    if key in table:
        return table[key]
    return default or key


def available_locales() -> list[str]:
    if not _LOCALES_DIR.exists():
        return []
    return sorted(path.stem for path in _LOCALES_DIR.glob("*.json"))
