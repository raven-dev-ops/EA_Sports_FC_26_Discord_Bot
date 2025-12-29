from __future__ import annotations

from config.settings import Settings


def feature_enabled(flag: str, settings: Settings | None) -> bool:
    if settings is None:
        return False
    return flag.lower() in {f.lower() for f in getattr(settings, "feature_flags", set())}
