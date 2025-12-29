from __future__ import annotations

import time
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """
    Simple in-memory TTL cache for async-friendly code paths.
    Not thread-safe, but adequate for the bot event loop usage.
    """

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> Optional[T]:
        now = time.time()
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < now:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: T) -> None:
        expires_at = time.time() + self.ttl
        self._store[key] = (expires_at, value)

    def clear(self) -> None:
        self._store.clear()
