from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Dict, Tuple

_counters: Counter[str] = Counter()
_timings: Counter[str] = Counter()


def record_command(name: str, *, status: str, duration_ms: float | None = None) -> None:
    key = f"commands.total.{status}.{name}"
    _counters[key] += 1
    if duration_ms is not None:
        bucket = int(duration_ms // 100) * 100  # bucket by 100ms
        _timings[f"commands.latency.bucket.{name}.{bucket}ms"] += 1
        logging.info("command metric name=%s status=%s duration_ms=%.1f", name, status, duration_ms)
    else:
        logging.info("command metric name=%s status=%s", name, status)


def snapshot() -> Tuple[Dict[str, int], Dict[str, int]]:
    return dict(_counters), dict(_timings)


def now_ms() -> float:
    return time.perf_counter() * 1000
