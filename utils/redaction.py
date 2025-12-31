from __future__ import annotations

import json
import re
from ipaddress import ip_address
from typing import Any

SENSITIVE_KEY_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "private_key",
    "email",
)

_REDACTED = "[Filtered]"
_BEARER_PATTERN = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._-]+")
_KEYVAL_PATTERN = re.compile(
    r"(?i)\b(access_token|refresh_token|token|api_key|apikey|secret|password)=([A-Za-z0-9._-]+)"
)


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(substr in lowered for substr in SENSITIVE_KEY_SUBSTRINGS)


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        scrubbed: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and is_sensitive_key(k):
                scrubbed[k] = _REDACTED
            else:
                scrubbed[k] = scrub(v)
        return scrubbed
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def redact_text(value: str) -> str:
    if not value:
        return value
    stripped = value.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            scrubbed = scrub(data)
            return json.dumps(scrubbed, separators=(",", ":"), ensure_ascii=True)
    redacted = _BEARER_PATTERN.sub(lambda m: f"{m.group(1)} [REDACTED]", value)
    redacted = _KEYVAL_PATTERN.sub(lambda m: f"{m.group(1)}=[REDACTED]", redacted)
    return redacted


def redact_ip(value: str) -> str:
    if not value:
        return value
    try:
        ip = ip_address(value)
    except ValueError:
        return value
    if ip.version == 4:
        parts = value.split(".")
        if len(parts) == 4:
            parts[-1] = "x"
            return ".".join(parts)
        return value
    compressed = ip.compressed
    parts = compressed.split(":")
    if len(parts) <= 2:
        return compressed
    return ":".join(parts[:2] + ["x"] * (len(parts) - 2))
