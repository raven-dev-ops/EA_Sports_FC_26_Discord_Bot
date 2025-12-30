from __future__ import annotations

import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from aiohttp import ClientSession, web
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from config import Settings, load_settings
from database import get_global_collection
from services.analytics_service import get_guild_analytics
from services.guild_config_service import get_guild_config, set_guild_config

DISCORD_API_BASE = "https://discord.com/api"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"
ME_URL = f"{DISCORD_API_BASE}/users/@me"
MY_GUILDS_URL = f"{DISCORD_API_BASE}/users/@me/guilds"

COOKIE_NAME = "offside_dashboard_session"
SESSION_TTL_SECONDS = int(os.environ.get("DASHBOARD_SESSION_TTL_SECONDS", "21600").strip() or "21600")
STATE_TTL_SECONDS = 600

# Minimal permissions needed for auto-setup and dashboard posting:
# - Manage Channels, Manage Roles, View Channel, Send Messages, Embed Links, Read Message History
DEFAULT_BOT_PERMISSIONS = 268520464

DASHBOARD_SESSIONS_COLLECTION = "dashboard_sessions"
DASHBOARD_OAUTH_STATES_COLLECTION = "dashboard_oauth_states"


@dataclass
class SessionData:
    created_at: float
    user: dict[str, Any]
    owner_guilds: list[dict[str, Any]]
    csrf_token: str


def _utc_now() -> datetime:
    return datetime.utcnow()


def _ensure_dashboard_collections(settings: Settings) -> tuple[Collection, Collection]:
    sessions = get_global_collection(settings, name=DASHBOARD_SESSIONS_COLLECTION)
    states = get_global_collection(settings, name=DASHBOARD_OAUTH_STATES_COLLECTION)
    sessions.create_index("expires_at", expireAfterSeconds=0, name="ttl_expires_at")
    states.create_index("expires_at", expireAfterSeconds=0, name="ttl_expires_at")
    return sessions, states


def _insert_unique(col: Collection, doc_factory) -> str:
    """
    Insert a document with a unique _id. Returns the inserted _id.
    """
    for _ in range(5):
        doc = doc_factory()
        doc_id = doc.get("_id")
        if not isinstance(doc_id, str) or not doc_id:
            raise RuntimeError("doc_factory() must return a dict with a non-empty string _id")
        try:
            col.insert_one(doc)
            return doc_id
        except DuplicateKeyError:
            continue
    raise RuntimeError("Failed to insert a unique document after multiple attempts.")


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
      .btn.secondary {{ background:#374151; }}
      .btn.blue {{ background:#2563eb; }}
      .btn.red {{ background:#b91c1c; }}
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


def _build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scope: str,
    extra_params: dict[str, str] | None = None,
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
            "prompt": "consent",
        }
    )
    if extra_params:
        query = f"{query}&{urllib.parse.urlencode(extra_params)}"
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
    request["session_id"] = session_id
    session: SessionData | None = None
    if session_id:
        sessions: Collection = request.app["session_collection"]
        doc = sessions.find_one({"_id": session_id}) or {}
        created_at = doc.get("created_at")
        if isinstance(created_at, (int, float)) and time.time() - float(created_at) <= SESSION_TTL_SECONDS:
            user = doc.get("user")
            owner_guilds = doc.get("owner_guilds")
            csrf_token = doc.get("csrf_token")
            if isinstance(user, dict) and isinstance(owner_guilds, list) and isinstance(csrf_token, str) and csrf_token:
                session = SessionData(
                    created_at=float(created_at),
                    user=user,
                    owner_guilds=[g for g in owner_guilds if isinstance(g, dict)],
                    csrf_token=csrf_token,
                )
        if session is None:
            sessions.delete_one({"_id": session_id})
    request["session"] = session
    return await handler(request)


def _require_session(request: web.Request) -> SessionData:
    session = request.get("session")
    if session is None:
        raise web.HTTPFound("/login")
    return session


def _is_https(request: web.Request) -> bool:
    forwarded = request.headers.get("X-Forwarded-Proto", "")
    if forwarded:
        proto = forwarded.split(",")[0].strip().lower()
        return proto == "https"
    return bool(getattr(request, "secure", False))


@web.middleware
async def security_headers_middleware(request: web.Request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc

    if not isinstance(response, web.StreamResponse):
        return response

    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "interest-cohort=()")

    # Inline CSS is used in _html_page, so allow 'unsafe-inline' for styles.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "form-action 'self';",
    )

    if _is_https(request):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    return response


def _sanitize_next_path(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return "/"
    if not value.startswith("/"):
        return "/"
    if value.startswith("//"):
        return "/"
    return value


def _escape_html(value: object) -> str:
    text = str(value) if value is not None else ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _invite_url(
    settings: Settings,
    *,
    guild_id: str | None = None,
    disable_guild_select: bool = False,
) -> str:
    client_id = str(settings.discord_application_id)
    params: dict[str, str] = {
        "client_id": client_id,
        "scope": "bot applications.commands",
        "permissions": str(DEFAULT_BOT_PERMISSIONS),
    }
    if guild_id:
        params["guild_id"] = str(guild_id)
    if disable_guild_select:
        params["disable_guild_select"] = "true"
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


async def index(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    session = request.get("session")
    if session is None:
        invite_href = _invite_url(settings)
        body = f"""
        <h1>Offside Dashboard</h1>
        <p class="muted">Sign in with Discord to view analytics for guilds you own.</p>
        <p><a class="btn" href="/login">Login with Discord</a></p>
        <p><a class="btn blue" href="/install">Invite bot to a server</a></p>
        <p class="muted">Direct invite URL:</p>
        <p><a href="{invite_href}">{invite_href}</a></p>
        """
        return web.Response(text=_html_page(title="Offside Dashboard", body=body), content_type="text/html")

    user = session.user
    username = _escape_html(f"{user.get('username','')}#{user.get('discriminator','')}".strip("#"))
    guild_cards = []
    for g in session.owner_guilds:
        gid = g.get("id")
        name = _escape_html(g.get("name") or gid)
        gid_str = str(gid)
        guild_cards.append(
            f"<div class='card'><div><strong>{name}</strong></div>"
            f"<div class='muted'>Guild ID: <code>{gid}</code></div>"
            f"<div style='margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;'>"
            f"<a class='btn' href='/guild/{gid_str}'>Analytics</a>"
            f"<a class='btn secondary' href='/guild/{gid_str}/settings'>Settings</a>"
            f"<a class='btn blue' href='/install?guild_id={gid_str}'>Invite bot</a>"
            f"</div>"
            f"</div>"
        )
    cards_html = "\n".join(guild_cards) if guild_cards else "<p>No owned guilds found.</p>"
    invite_href = _invite_url(settings)
    body = f"""
      <h1>Offside Dashboard</h1>
      <p class="muted">Logged in as <strong>{username}</strong> (<code>{_escape_html(user.get('id'))}</code>)</p>
      <p><a href="/logout">Logout</a></p>
      <h2>Your servers</h2>
      {cards_html}
      <h2>Invite link</h2>
      <p class="muted">Direct invite URL (shareable):</p>
      <p><a href="{invite_href}">{invite_href}</a></p>
    """
    return web.Response(text=_html_page(title="Offside Dashboard", body=body), content_type="text/html")


async def login(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    client_id, _client_secret, redirect_uri = _oauth_config(settings)
    next_path = _sanitize_next_path(request.query.get("next", ""))
    states: Collection = request.app["state_collection"]
    expires_at = _utc_now() + timedelta(seconds=STATE_TTL_SECONDS)
    state = _insert_unique(
        states,
        lambda: {"_id": secrets.token_urlsafe(24), "issued_at": time.time(), "next": next_path, "expires_at": expires_at},
    )
    raise web.HTTPFound(
        _build_authorize_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scope="identify guilds",
        )
    )


async def install(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    client_id, _client_secret, redirect_uri = _oauth_config(settings)

    requested_guild_id = request.query.get("guild_id", "").strip()
    next_path = "/"
    extra: dict[str, str] = {"permissions": str(DEFAULT_BOT_PERMISSIONS)}
    if requested_guild_id.isdigit():
        extra["guild_id"] = requested_guild_id
        extra["disable_guild_select"] = "true"
        next_path = f"/guild/{requested_guild_id}"

    states: Collection = request.app["state_collection"]
    expires_at = _utc_now() + timedelta(seconds=STATE_TTL_SECONDS)
    state = _insert_unique(
        states,
        lambda: {"_id": secrets.token_urlsafe(24), "issued_at": time.time(), "next": next_path, "expires_at": expires_at},
    )
    raise web.HTTPFound(
        _build_authorize_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scope="identify guilds bot applications.commands",
            extra_params=extra,
        )
    )


async def oauth_callback(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    client_id, client_secret, redirect_uri = _oauth_config(settings)
    http: ClientSession = request.app["http"]

    code = request.query.get("code", "").strip()
    state = request.query.get("state", "").strip()
    if not code or not state:
        raise web.HTTPBadRequest(text="Missing code/state.")

    states: Collection = request.app["state_collection"]
    pending_state = states.find_one_and_delete({"_id": state})
    issued_at_value = pending_state.get("issued_at") if pending_state else None
    try:
        issued_at = float(issued_at_value) if issued_at_value is not None else None
    except (TypeError, ValueError):
        issued_at = None
    next_path = str(pending_state.get("next") or "/") if pending_state else "/"
    next_path = _sanitize_next_path(next_path)
    if issued_at is None or time.time() - issued_at > STATE_TTL_SECONDS:
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

    installed_guild_id = request.query.get("guild_id", "").strip()
    if installed_guild_id.isdigit():
        for g in owner_guilds:
            if str(g.get("id")) == installed_guild_id:
                next_path = f"/guild/{installed_guild_id}"
                break

    sessions: Collection = request.app["session_collection"]
    expires_at = _utc_now() + timedelta(seconds=SESSION_TTL_SECONDS)
    csrf_token = secrets.token_urlsafe(24)
    session_id = _insert_unique(
        sessions,
        lambda: {
            "_id": secrets.token_urlsafe(32),
            "created_at": time.time(),
            "expires_at": expires_at,
            "user": user,
            "owner_guilds": owner_guilds,
            "csrf_token": csrf_token,
        },
    )

    resp = web.HTTPFound(next_path)
    resp.set_cookie(
        COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="Lax",
        secure=_is_https(request),
        max_age=SESSION_TTL_SECONDS,
    )
    raise resp


async def logout(request: web.Request) -> web.Response:
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        sessions: Collection = request.app["session_collection"]
        sessions.delete_one({"_id": session_id})
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


def _parse_int_list(raw: str) -> list[int] | None:
    value = (raw or "").strip()
    if not value:
        return []
    out: list[int] = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if not token.isdigit():
            return None
        out.append(int(token))
    return out


async def guild_settings_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    cfg: dict[str, Any] = {}
    try:
        cfg = get_guild_config(guild_id)
    except Exception:
        cfg = {}

    staff_role_ids_raw = cfg.get("staff_role_ids")
    if isinstance(staff_role_ids_raw, list):
        staff_role_ids_value = ", ".join(str(x) for x in staff_role_ids_raw if isinstance(x, int))
    else:
        staff_role_ids_value = ""

    fc25_value = cfg.get("fc25_stats_enabled")
    if fc25_value is True:
        fc25_selected = "true"
    elif fc25_value is False:
        fc25_selected = "false"
    else:
        fc25_selected = "default"

    selected_default = "selected" if fc25_selected == "default" else ""
    selected_true = "selected" if fc25_selected == "true" else ""
    selected_false = "selected" if fc25_selected == "false" else ""

    invite_href = _invite_url(settings, guild_id=str(guild_id), disable_guild_select=True)
    saved = request.query.get("saved", "").strip()
    message_html = "<p class='muted'>Saved.</p>" if saved else ""

    rows = "\n".join(
        f"<tr><td><code>{_escape_html(k)}</code></td><td><code>{_escape_html(v)}</code></td></tr>"
        for k, v in sorted(cfg.items())
    ) or "<tr><td colspan='2' class='muted'>No config found yet (bot may not be installed).</td></tr>"

    body = f"""
      <p><a href="/">ƒ+? Back</a></p>
      <h1>Guild Settings</h1>
      <div class="row">
        <div class="card">
          <div><strong>Guild</strong></div>
          <div class="muted">ID: <code>{guild_id}</code></div>
          <div style="margin-top:10px;">
            <a class="btn blue" href="{invite_href}">Invite bot to this server</a>
          </div>
        </div>
      </div>
      {message_html}
      <div class="row">
        <div class="card">
          <h2 style="margin-top:0;">Access</h2>
          <form method="post" action="/guild/{guild_id}/settings">
            <input type="hidden" name="csrf" value="{session.csrf_token}" />
            <label>Staff role IDs (comma-separated)</label><br/>
            <input name="staff_role_ids" style="width:100%; padding:10px; margin-top:6px;" value="{_escape_html(staff_role_ids_value)}" />
            <p class="muted">Leave blank to require Manage Server (or env <code>STAFF_ROLE_IDS</code>).</p>
            <label>FC25 stats override</label><br/>
            <select name="fc25_stats_enabled" style="width:100%; padding:10px; margin-top:6px;">
              <option value="default" {selected_default}>Default</option>
              <option value="true" {selected_true}>Enabled</option>
              <option value="false" {selected_false}>Disabled</option>
            </select>
            <div style="margin-top:12px;">
              <button class="btn" type="submit">Save</button>
            </div>
          </form>
        </div>
        <div class="card">
          <h2 style="margin-top:0;">Current Config</h2>
          <table><thead><tr><th>key</th><th>value</th></tr></thead><tbody>{rows}</tbody></table>
        </div>
      </div>
    """
    return web.Response(text=_html_page(title="Guild Settings", body=body), content_type="text/html")


async def guild_settings_save(request: web.Request) -> web.Response:
    session = _require_session(request)
    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    cfg: dict[str, Any] = {}
    try:
        cfg = get_guild_config(guild_id)
    except Exception:
        cfg = {}

    staff_raw = str(data.get("staff_role_ids", "")).strip()
    parsed_staff = _parse_int_list(staff_raw)
    if parsed_staff is None:
        raise web.HTTPBadRequest(text="staff_role_ids must be a comma-separated list of integers.")
    if parsed_staff:
        cfg["staff_role_ids"] = parsed_staff
    else:
        cfg.pop("staff_role_ids", None)

    fc25_raw = str(data.get("fc25_stats_enabled", "default")).strip().lower()
    if fc25_raw in {"", "default"}:
        cfg.pop("fc25_stats_enabled", None)
    elif fc25_raw in {"1", "true", "yes", "on"}:
        cfg["fc25_stats_enabled"] = True
    elif fc25_raw in {"0", "false", "no", "off"}:
        cfg["fc25_stats_enabled"] = False
    else:
        raise web.HTTPBadRequest(text="fc25_stats_enabled must be default/true/false.")

    try:
        set_guild_config(guild_id, cfg)
    except Exception as exc:
        raise web.HTTPInternalServerError(text=f"Failed to save settings: {exc}") from exc

    raise web.HTTPFound(f"/guild/{guild_id}/settings?saved=1")


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
          <div style="margin-top:10px;"><a class="btn secondary" href="/guild/{guild_id}/settings">Settings</a></div>
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


async def _on_startup(app: web.Application) -> None:
    # aiohttp ClientSession must be created with a running event loop.
    app["http"] = ClientSession()


async def _on_cleanup(app: web.Application) -> None:
    http = app.get("http")
    if isinstance(http, ClientSession):
        await http.close()


def create_app(*, settings: Settings | None = None) -> web.Application:
    app = web.Application(middlewares=[security_headers_middleware, session_middleware])
    app_settings = settings or load_settings()
    app["settings"] = app_settings
    session_collection, state_collection = _ensure_dashboard_collections(app_settings)
    app["session_collection"] = session_collection
    app["state_collection"] = state_collection
    app["http"] = None
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    app.router.add_get("/", index)
    app.router.add_get("/login", login)
    app.router.add_get("/install", install)
    app.router.add_get("/oauth/callback", oauth_callback)
    app.router.add_get("/logout", logout)
    app.router.add_get("/guild/{guild_id}", guild_page)
    app.router.add_get("/guild/{guild_id}/settings", guild_settings_page)
    app.router.add_post("/guild/{guild_id}/settings", guild_settings_save)
    app.router.add_get("/api/guild/{guild_id}/analytics.json", guild_analytics_json)
    return app


def main() -> None:
    settings = load_settings()
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port_raw = (os.environ.get("PORT") or os.environ.get("DASHBOARD_PORT", "8080")).strip() or "8080"
    port = int(port_raw)
    app = create_app(settings=settings)
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()
