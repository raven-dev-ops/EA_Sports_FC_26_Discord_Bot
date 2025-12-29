from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class CooldownResult:
    allowed: bool
    retry_after_seconds: float | None = None


class Cooldown:
    def __init__(self, *, seconds: float) -> None:
        self.seconds = float(seconds)
        self._last: dict[str, float] = {}

    def check(self, key: str) -> CooldownResult:
        now = time.monotonic()
        last = self._last.get(key)
        if last is None or (now - last) >= self.seconds:
            self._last[key] = now
            return CooldownResult(allowed=True)
        return CooldownResult(allowed=False, retry_after_seconds=max(0.0, self.seconds - (now - last)))

