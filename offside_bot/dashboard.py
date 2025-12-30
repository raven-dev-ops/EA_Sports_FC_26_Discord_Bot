from __future__ import annotations

import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientSession, web

from config import Settings, load_settings
from services.analytics_service import get_guild_analytics

DISCORD_API_BASE = "https://discord.com/api"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"
ME_URL = f"{DISCORD_API_BASE}/users/@me"
MY_GUILDS_URL = f"{DISCORD_API_BASE}/users/@me/guilds"

COOKIE_NAME = "offside_dashboard_session"


@dataclass
class SessionData:
    created_at: float
    access_token: str
    user: dict[str, Any]
    owner_guilds: list[dict[str, Any]]


def _html_page(*, title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>
      body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; padding: 24px; color: #111; }}
      a {{ color: #2563eb; text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
      .card {{ border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; margin: 12px 0; }}
      .muted {{ color: #6b7280; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px 10px; text-align: left; }}
      th {{ background: #f9fafb; }}
      code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }}
      .row {{ display: flex; gap: 12px; flex-wrap: wrap; }}
      .row > .card {{ flex: 1 1 360px; }}
      .btn {{ display:inline-block; background:#111827; color:white; padding:10px 14px; border-radius:10px; }}
      .btn:hover {{ text-decoration:none; opacity:0.9; }}
    </style>
  </head>
  <body>
    {body}
  </body>
</html>"""


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _oauth_config(settings: Settings) -> tuple[str, str, str]:
    client_id = str(settings.discord_client_id or settings.discord_application_id)
    client_secret = _require_env("DISCORD_CLIENT_SECRET")
    redirect_uri = _require_env("DASHBOARD_REDIRECT_URI")
    return client_id, client_secret, redirect_uri


def _build_authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
            "prompt": "consent",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


async def _discord_get_json(http: ClientSession, *, url: str, access_token: str) -> Any:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with http.get(url, headers=headers) as resp:
        data = await resp.json()
        if resp.status >= 400:
            raise web.HTTPBadRequest(text=f"Discord API error ({resp.status}): {data}")
        return data


async def _exchange_code(
    http: ClientSession,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> dict[str, Any]:
    form = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with http.post(TOKEN_URL, data=form) as resp:
        data = await resp.json()
        if resp.status >= 400:
            raise web.HTTPBadRequest(text=f"OAuth token exchange failed ({resp.status}): {data}")
        return data


@web.middleware
async def session_middleware(request: web.Request, handler):
    session_id = request.cookies.get(COOKIE_NAME)
    sessions: dict[str, SessionData] = request.app["sessions"]
    request["session_id"] = session_id
    request["session"] = sessions.get(session_id) if session_id else None
    return await handler(request)


def _require_session(request: web.Request) -> SessionData:
    session = request.get("session")
    if session is None:
        raise web.HTTPFound("/login")
    return session


async def index(request: web.Request) -> web.Response:
    session = request.get("session")
    if session is None:
        body = """
        <h1>Offside Dashboard</h1>
        <p class="muted">Sign in with Discord to view analytics for guilds you own.</p>
        <p><a class="btn" href="/login">Login with Discord</a></p>
        """
        return web.Response(text=_html_page(title="Offside Dashboard", body=body), content_type="text/html")

    user = session.user
    username = f"{user.get('username','')}#{user.get('discriminator','')}".strip("#")
    guild_cards = []
    for g in session.owner_guilds:
        gid = g.get("id")
        name = g.get("name") or gid
        guild_cards.append(
            f"<div class='card'><div><strong>{name}</strong></div>"
            f"<div class='muted'>Guild ID: <code>{gid}</code></div>"
            f"<div style='margin-top:10px;'><a class='btn' href='/guild/{gid}'>View analytics</a></div>"
            f"</div>"
        )
    cards_html = "\n".join(guild_cards) if guild_cards else "<p>No owned guilds found.</p>"
    body = f"""
      <h1>Offside Dashboard</h1>
      <p class="muted">Logged in as <strong>{username}</strong> (<code>{user.get('id')}</code>)</p>
      <p><a href="/logout">Logout</a></p>
      <h2>Your servers</h2>
      {cards_html}
    """
    return web.Response(text=_html_page(title="Offside Dashboard", body=body), content_type="text/html")


async def login(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    client_id, _client_secret, redirect_uri = _oauth_config(settings)
    state = secrets.token_urlsafe(24)
    pending: dict[str, float] = request.app["pending_states"]
    pending[state] = time.time()
    raise web.HTTPFound(_build_authorize_url(client_id=client_id, redirect_uri=redirect_uri, state=state))


async def oauth_callback(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    client_id, client_secret, redirect_uri = _oauth_config(settings)
    http: ClientSession = request.app["http"]

    code = request.query.get("code", "").strip()
    state = request.query.get("state", "").strip()
    if not code or not state:
        raise web.HTTPBadRequest(text="Missing code/state.")

    pending: dict[str, float] = request.app["pending_states"]
    issued_at = pending.pop(state, None)
    if issued_at is None or time.time() - issued_at > 600:
        raise web.HTTPBadRequest(text="Invalid or expired state.")

    token = await _exchange_code(
        http,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        code=code,
    )
    access_token = str(token.get("access_token") or "")
    if not access_token:
        raise web.HTTPBadRequest(text="OAuth did not return an access_token.")

    user = await _discord_get_json(http, url=ME_URL, access_token=access_token)
    guilds = await _discord_get_json(http, url=MY_GUILDS_URL, access_token=access_token)
    owner_guilds = [g for g in guilds if isinstance(g, dict) and g.get("owner") is True]

    session_id = secrets.token_urlsafe(32)
    sessions: dict[str, SessionData] = request.app["sessions"]
    sessions[session_id] = SessionData(
        created_at=time.time(),
        access_token=access_token,
        user=user,
        owner_guilds=owner_guilds,
    )

    resp = web.HTTPFound("/")
    resp.set_cookie(COOKIE_NAME, session_id, httponly=True, samesite="Lax")
    raise resp


async def logout(request: web.Request) -> web.Response:
    session_id = request.cookies.get(COOKIE_NAME)
    sessions: dict[str, SessionData] = request.app["sessions"]
    if session_id:
        sessions.pop(session_id, None)
    resp = web.HTTPFound("/")
    resp.del_cookie(COOKIE_NAME)
    raise resp


def _require_owned_guild(session: SessionData, *, guild_id: str) -> int:
    try:
        gid_int = int(guild_id)
    except ValueError as exc:
        raise web.HTTPBadRequest(text="Invalid guild id.") from exc
    for g in session.owner_guilds:
        if str(g.get("id")) == str(guild_id):
            return gid_int
    raise web.HTTPForbidden(text="You do not own this guild.")


async def guild_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    analytics = get_guild_analytics(settings, guild_id=guild_id)

    count_rows = "\n".join(
        f"<tr><td><code>{rt}</code></td><td>{count}</td></tr>"
        for rt, count in sorted(analytics.record_type_counts.items())
    )
    collection_rows = "\n".join(
        f"<tr><td><code>{name}</code></td><td>{info.get('count')}</td></tr>"
        for name, info in sorted(analytics.collections.items())
    )

    body = f"""
      <p><a href="/">← Back</a></p>
      <h1>Guild Analytics</h1>
      <div class="row">
        <div class="card">
          <div><strong>Guild</strong></div>
          <div class="muted">ID: <code>{guild_id}</code></div>
          <div class="muted">MongoDB DB: <code>{analytics.db_name}</code></div>
          <div class="muted">Generated: {analytics.generated_at.isoformat()}</div>
          <div style="margin-top:10px;"><a href="/api/guild/{guild_id}/analytics.json">Download JSON</a></div>
        </div>
      </div>
      <div class="row">
        <div class="card">
          <h2 style="margin-top:0;">Record Types</h2>
          <table><thead><tr><th>record_type</th><th>count</th></tr></thead><tbody>{count_rows}</tbody></table>
        </div>
        <div class="card">
          <h2 style="margin-top:0;">Collections</h2>
          <table><thead><tr><th>collection</th><th>count</th></tr></thead><tbody>{collection_rows}</tbody></table>
        </div>
      </div>
    """
    return web.Response(text=_html_page(title="Guild Analytics", body=body), content_type="text/html")


async def guild_analytics_json(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)
    analytics = get_guild_analytics(settings, guild_id=guild_id)

    return web.json_response(
        {
            "guild_id": analytics.guild_id,
            "db_name": analytics.db_name,
            "generated_at": analytics.generated_at.isoformat(),
            "record_type_counts": analytics.record_type_counts,
            "collections": analytics.collections,
        }
    )


async def _on_cleanup(app: web.Application) -> None:
    http: ClientSession = app["http"]
    await http.close()


def create_app(*, settings: Settings | None = None) -> web.Application:
    app = web.Application(middlewares=[session_middleware])
    app["settings"] = settings or load_settings()
    app["sessions"] = {}
    app["pending_states"] = {}
    app["http"] = ClientSession()
    app.on_cleanup.append(_on_cleanup)

    app.router.add_get("/", index)
    app.router.add_get("/login", login)
    app.router.add_get("/oauth/callback", oauth_callback)
    app.router.add_get("/logout", logout)
    app.router.add_get("/guild/{guild_id}", guild_page)
    app.router.add_get("/api/guild/{guild_id}/analytics.json", guild_analytics_json)
    return app


def main() -> None:
    settings = load_settings()
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port_raw = os.environ.get("DASHBOARD_PORT", "8080").strip() or "8080"
    port = int(port_raw)
    app = create_app(settings=settings)
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()

