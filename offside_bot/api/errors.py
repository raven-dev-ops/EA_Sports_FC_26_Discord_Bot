from __future__ import annotations

import json
from typing import Any

from aiohttp import web


def _payload(code: str, message: str, details: dict[str, Any] | None = None) -> str:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return json.dumps(body)


def api_error(
    *,
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> web.HTTPException:
    text = _payload(code, message, details)
    if status == 401:
        return web.HTTPUnauthorized(text=text, content_type="application/json")
    if status == 402:
        return web.HTTPPaymentRequired(text=text, content_type="application/json")
    if status == 403:
        return web.HTTPForbidden(text=text, content_type="application/json")
    if status == 404:
        return web.HTTPNotFound(text=text, content_type="application/json")
    return web.HTTPBadRequest(text=text, content_type="application/json")


def api_unauthorized(message: str = "Authentication required.") -> web.HTTPException:
    return api_error(status=401, code="auth_required", message=message)


def api_forbidden(message: str = "Forbidden.") -> web.HTTPException:
    return api_error(status=403, code="forbidden", message=message)


def api_upgrade_required(
    message: str = "Upgrade required.",
    *,
    upgrade_href: str | None = None,
    guild_id: int | None = None,
) -> web.HTTPException:
    details: dict[str, Any] = {}
    if upgrade_href:
        details["upgrade_href"] = upgrade_href
    if guild_id is not None:
        details["guild_id"] = guild_id
    return api_error(status=402, code="upgrade_required", message=message, details=details or None)
