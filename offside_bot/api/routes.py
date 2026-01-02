from __future__ import annotations

from typing import Any

from aiohttp import web

from offside_bot.api.errors import api_unauthorized


def _require_api_session(request: web.Request) -> Any:
    session = request.get("session")
    if session is None:
        raise api_unauthorized()
    return session


async def api_me(request: web.Request) -> web.Response:
    session = _require_api_session(request)
    user = getattr(session, "user", {})
    owner_guilds = getattr(session, "owner_guilds", []) or []
    all_guilds = getattr(session, "all_guilds", []) or []
    return web.json_response(
        {
            "user": user,
            "guild_counts": {"owner": len(owner_guilds), "all": len(all_guilds)},
            "last_guild_id": getattr(session, "last_guild_id", None),
        }
    )


async def api_guilds(request: web.Request) -> web.Response:
    session = _require_api_session(request)
    return web.json_response(
        {
            "owner_guilds": getattr(session, "owner_guilds", []),
            "all_guilds": getattr(session, "all_guilds", []),
            "last_guild_id": getattr(session, "last_guild_id", None),
        }
    )
