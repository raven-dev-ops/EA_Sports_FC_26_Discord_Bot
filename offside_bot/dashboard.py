from __future__ import annotations

import asyncio
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
GUILD_METADATA_TTL_SECONDS = int(os.environ.get("DASHBOARD_GUILD_METADATA_TTL_SECONDS", "60").strip() or "60")

# Minimal permissions needed for auto-setup and dashboard posting:
# - Manage Channels, Manage Roles, View Channel, Send Messages, Embed Links, Read Message History
DEFAULT_BOT_PERMISSIONS = 268520464

DASHBOARD_SESSIONS_COLLECTION = "dashboard_sessions"
DASHBOARD_OAUTH_STATES_COLLECTION = "dashboard_oauth_states"

GUILD_COACH_ROLE_FIELDS: list[tuple[str, str]] = [
    ("role_coach_id", "Coach role"),
    ("role_coach_premium_id", "Coach Premium role"),
    ("role_coach_premium_plus_id", "Coach Premium+ role"),
]

GUILD_CHANNEL_FIELDS: list[tuple[str, str]] = [
    ("channel_staff_portal_id", "Staff portal channel"),
    ("channel_club_portal_id", "Club portal channel"),
    ("channel_manager_portal_id", "Club Managers portal channel"),
    ("channel_coach_portal_id", "Coach portal channel"),
    ("channel_recruit_portal_id", "Recruit portal channel"),
    ("channel_staff_monitor_id", "Staff monitor channel"),
    ("channel_roster_listing_id", "Roster listing channel"),
    ("channel_recruit_listing_id", "Recruit listing channel"),
    ("channel_club_listing_id", "Club listing channel"),
    ("channel_premium_coaches_id", "Premium Coaches channel"),
]


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


async def _discord_get_json_with_auth(http: ClientSession, *, url: str, authorization: str) -> Any:
    headers = {"Authorization": authorization}
    last_error: str | None = None
    for _ in range(5):
        async with http.get(url, headers=headers) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = await resp.text()

            if resp.status == 429 and isinstance(data, dict):
                retry_after = float(data.get("retry_after") or 1.0)
                await asyncio.sleep(max(0.0, retry_after))
                last_error = f"rate limited; retry_after={retry_after}"
                continue

            if resp.status >= 400:
                raise web.HTTPBadRequest(text=f"Discord API error ({resp.status}): {data}")
            return data

    raise web.HTTPBadRequest(text=f"Discord API request failed after retries: {last_error or 'unknown'}")


async def _discord_get_json(http: ClientSession, *, url: str, access_token: str) -> Any:
    return await _discord_get_json_with_auth(http, url=url, authorization=f"Bearer {access_token}")


async def _discord_bot_get_json(http: ClientSession, *, url: str, bot_token: str) -> Any:
    return await _discord_get_json_with_auth(http, url=url, authorization=f"Bot {bot_token}")


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


async def _fetch_guild_roles(http: ClientSession, *, bot_token: str, guild_id: int) -> list[dict[str, Any]]:
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/roles"
    data = await _discord_bot_get_json(http, url=url, bot_token=bot_token)
    if not isinstance(data, list):
        raise web.HTTPBadRequest(text="Discord returned an invalid roles payload.")
    roles = [r for r in data if isinstance(r, dict)]
    roles.sort(key=lambda r: int(r.get("position") or 0), reverse=True)
    return roles


async def _fetch_guild_channels(http: ClientSession, *, bot_token: str, guild_id: int) -> list[dict[str, Any]]:
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/channels"
    data = await _discord_bot_get_json(http, url=url, bot_token=bot_token)
    if not isinstance(data, list):
        raise web.HTTPBadRequest(text="Discord returned an invalid channels payload.")
    channels = [c for c in data if isinstance(c, dict)]
    channels.sort(key=lambda c: (int(c.get("type") or 0), int(c.get("position") or 0)))
    return channels


async def _get_guild_discord_metadata(
    request: web.Request,
    *,
    guild_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cache: dict[int, dict[str, Any]] = request.app["guild_metadata_cache"]
    now = time.time()
    cached = cache.get(guild_id)
    if isinstance(cached, dict):
        fetched_at = cached.get("fetched_at")
        if isinstance(fetched_at, (int, float)) and now - float(fetched_at) <= GUILD_METADATA_TTL_SECONDS:
            roles = cached.get("roles")
            channels = cached.get("channels")
            if isinstance(roles, list) and isinstance(channels, list):
                return [r for r in roles if isinstance(r, dict)], [c for c in channels if isinstance(c, dict)]

    settings: Settings = request.app["settings"]
    http = request.app.get("http")
    if not isinstance(http, ClientSession):
        raise web.HTTPInternalServerError(text="Dashboard HTTP client is not ready yet.")

    roles = await _fetch_guild_roles(http, bot_token=settings.discord_token, guild_id=guild_id)
    channels = await _fetch_guild_channels(http, bot_token=settings.discord_token, guild_id=guild_id)
    cache[guild_id] = {"fetched_at": now, "roles": roles, "channels": channels}
    return roles, channels


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


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or not stripped.isdigit():
            return None
        return int(stripped)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
    staff_role_ids: set[int] = set()
    if isinstance(staff_role_ids_raw, list):
        staff_role_ids = {x for x in staff_role_ids_raw if isinstance(x, int)}
    staff_role_ids_value = ", ".join(str(x) for x in sorted(staff_role_ids))

    roles: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    metadata_error: str | None = None
    try:
        roles, channels = await _get_guild_discord_metadata(request, guild_id=guild_id)
    except web.HTTPException as exc:
        metadata_error = exc.text or str(exc)
    except Exception as exc:
        metadata_error = str(exc)

    if roles:
        role_options: list[str] = []
        for role in roles:
            role_id = role.get("id")
            if role_id is None:
                continue
            try:
                role_id_int = int(role_id)
            except (TypeError, ValueError):
                continue
            name = _escape_html(role.get("name") or role_id_int)
            selected = "selected" if role_id_int in staff_role_ids else ""
            role_options.append(f"<option value=\"{role_id_int}\" {selected}>{name}</option>")
        options_html = "\n".join(role_options) or "<option disabled>(no roles found)</option>"
        staff_roles_control_html = f"""
            <label>Staff roles</label><br/>
            <select multiple name="staff_role_ids" size="10" style="width:100%; padding:10px; margin-top:6px;">
              {options_html}
            </select>
            <p class="muted">Select one or more roles. Leave empty to require Manage Server (or env <code>STAFF_ROLE_IDS</code>).</p>
        """
    else:
        warning = (
            f"<p class='muted'>Unable to load roles from Discord: <code>{_escape_html(metadata_error)}</code></p>"
            if metadata_error
            else ""
        )
        staff_roles_control_html = f"""
            {warning}
            <label>Staff role IDs (comma-separated)</label><br/>
            <input name="staff_role_ids_csv" style="width:100%; padding:10px; margin-top:6px;" value="{_escape_html(staff_role_ids_value)}" />
            <p class="muted">Leave blank to require Manage Server (or env <code>STAFF_ROLE_IDS</code>).</p>
        """

    metadata_warning_html = (
        f"<p class='muted'>Discord metadata unavailable: <code>{_escape_html(metadata_error)}</code>. Dropdowns may fall back to manual IDs.</p>"
        if metadata_error
        else ""
    )

    coach_role_id = _parse_int(cfg.get("role_coach_id"))
    premium_role_id = _parse_int(cfg.get("role_coach_premium_id"))
    premium_plus_role_id = _parse_int(cfg.get("role_coach_premium_plus_id"))

    if roles:
        valid_role_ids = {_parse_int(r.get("id")) for r in roles}
        valid_role_ids.discard(None)

        def _role_options(selected_id: int | None) -> str:
            default_selected = "selected" if selected_id is None else ""
            option_lines = [f"<option value=\"\" {default_selected}>(Use default)</option>"]
            if selected_id is not None and selected_id not in valid_role_ids:
                option_lines.append(
                    f"<option value=\"{selected_id}\" selected>(missing id: {selected_id})</option>"
                )
            for role in roles:
                rid = _parse_int(role.get("id"))
                if rid is None or rid == guild_id:
                    continue
                name = _escape_html(role.get("name") or rid)
                selected = "selected" if rid == selected_id else ""
                option_lines.append(f"<option value=\"{rid}\" {selected}>{name}</option>")
            return "\n".join(option_lines)

        coach_roles_control_html = f"""
            <h3 style="margin:14px 0 6px;">Coach tiers</h3>
            <label>Coach role</label><br/>
            <select name="role_coach_id" style="width:100%; padding:10px; margin-top:6px;">
              {_role_options(coach_role_id)}
            </select>
            <label style="display:block; margin-top:10px;">Coach Premium role</label>
            <select name="role_coach_premium_id" style="width:100%; padding:10px; margin-top:6px;">
              {_role_options(premium_role_id)}
            </select>
            <label style="display:block; margin-top:10px;">Coach Premium+ role</label>
            <select name="role_coach_premium_plus_id" style="width:100%; padding:10px; margin-top:6px;">
              {_role_options(premium_plus_role_id)}
            </select>
        """
    else:
        coach_roles_control_html = f"""
            <h3 style="margin:14px 0 6px;">Coach tiers</h3>
            <label>Coach role ID</label><br/>
            <input name="role_coach_id" style="width:100%; padding:10px; margin-top:6px;" value="{_escape_html(coach_role_id or '')}" />
            <label style="display:block; margin-top:10px;">Coach Premium role ID</label>
            <input name="role_coach_premium_id" style="width:100%; padding:10px; margin-top:6px;" value="{_escape_html(premium_role_id or '')}" />
            <label style="display:block; margin-top:10px;">Coach Premium+ role ID</label>
            <input name="role_coach_premium_plus_id" style="width:100%; padding:10px; margin-top:6px;" value="{_escape_html(premium_plus_role_id or '')}" />
        """

    selected_channels: dict[str, int | None] = {
        field: _parse_int(cfg.get(field)) for field, _label in GUILD_CHANNEL_FIELDS
    }

    if channels:
        categories: dict[int, str] = {}
        channel_labels: dict[int, str] = {}
        valid_channel_ids: set[int] = set()
        for ch in channels:
            if _parse_int(ch.get("type")) == 4:
                cid = _parse_int(ch.get("id"))
                if cid is not None:
                    categories[cid] = str(ch.get("name") or cid)

        for ch in channels:
            cid = _parse_int(ch.get("id"))
            ctype = _parse_int(ch.get("type"))
            if cid is None or ctype is None:
                continue
            if ctype not in {0, 5, 15}:
                continue
            name = str(ch.get("name") or cid)
            parent_id = _parse_int(ch.get("parent_id"))
            prefix = categories.get(parent_id) if parent_id else None
            display = f"{prefix} / #{name}" if prefix else f"#{name}"
            valid_channel_ids.add(cid)
            channel_labels[cid] = display

        def _channel_options(selected_id: int | None) -> str:
            default_selected = "selected" if selected_id is None else ""
            option_lines = [f"<option value=\"\" {default_selected}>(Use default)</option>"]
            if selected_id is not None and selected_id not in valid_channel_ids:
                option_lines.append(
                    f"<option value=\"{selected_id}\" selected>(missing id: {selected_id})</option>"
                )
            for cid, label in sorted(channel_labels.items(), key=lambda kv: kv[1].lower()):
                selected = "selected" if cid == selected_id else ""
                option_lines.append(
                    f"<option value=\"{cid}\" {selected}>{_escape_html(label)}</option>"
                )
            return "\n".join(option_lines)

        channel_controls: list[str] = ['<h3 style="margin:14px 0 6px;">Channels</h3>']
        for field, label in GUILD_CHANNEL_FIELDS:
            selected_id = selected_channels.get(field)
            channel_controls.append(f"<label>{_escape_html(label)}</label><br/>")
            channel_controls.append(
                f"<select name=\"{field}\" style=\"width:100%; padding:10px; margin-top:6px;\">{_channel_options(selected_id)}</select>"
            )
        channels_control_html = "\n".join(channel_controls)
    else:
        channel_controls = ['<h3 style="margin:14px 0 6px;">Channels</h3>']
        for field, label in GUILD_CHANNEL_FIELDS:
            selected_id = selected_channels.get(field)
            channel_controls.append(f"<label>{_escape_html(label)} ID</label><br/>")
            channel_controls.append(
                f"<input name=\"{field}\" style=\"width:100%; padding:10px; margin-top:6px;\" value=\"{_escape_html(selected_id or '')}\" />"
            )
        channels_control_html = "\n".join(channel_controls)

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
      <p><a href="/">&lt;- Back</a></p>
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
             {metadata_warning_html}
             {staff_roles_control_html}
             {coach_roles_control_html}
             {channels_control_html}
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

    selected_roles: list[str] = []
    try:
        selected_roles = [str(v).strip() for v in data.getall("staff_role_ids") if str(v).strip()]
    except Exception:
        selected_roles = []

    if selected_roles:
        parsed_staff_selected: list[int] = []
        for token in selected_roles:
            if not token.isdigit():
                raise web.HTTPBadRequest(text="staff_role_ids must be a list of role IDs.")
            parsed_staff_selected.append(int(token))
        cfg["staff_role_ids"] = parsed_staff_selected
    else:
        staff_raw = str(data.get("staff_role_ids_csv", "")).strip()
        parsed_staff_csv = _parse_int_list(staff_raw)
        if parsed_staff_csv is None:
            raise web.HTTPBadRequest(text="staff_role_ids must be a comma-separated list of integers.")
        if parsed_staff_csv:
            cfg["staff_role_ids"] = parsed_staff_csv
        else:
            cfg.pop("staff_role_ids", None)

    valid_role_ids: set[int] = set()
    valid_channel_ids: set[int] = set()
    try:
        roles, channels = await _get_guild_discord_metadata(request, guild_id=guild_id)
    except Exception:
        roles, channels = [], []

    for role in roles:
        rid = _parse_int(role.get("id"))
        if rid is not None:
            valid_role_ids.add(rid)

    for channel in channels:
        cid = _parse_int(channel.get("id"))
        ctype = _parse_int(channel.get("type"))
        if cid is None or ctype is None:
            continue
        if ctype in {0, 5, 15}:
            valid_channel_ids.add(cid)

    existing_int_fields: dict[str, int | None] = {
        field: _parse_int(cfg.get(field)) for field, _label in (GUILD_COACH_ROLE_FIELDS + GUILD_CHANNEL_FIELDS)
    }

    def _apply_int_field(*, field: str, raw_value: Any, valid_ids: set[int], kind: str) -> None:
        raw_str = str(raw_value or "").strip()
        if not raw_str:
            cfg.pop(field, None)
            return
        if not raw_str.isdigit():
            raise web.HTTPBadRequest(text=f"{field} must be an integer.")
        value = int(raw_str)
        if valid_ids and value not in valid_ids and existing_int_fields.get(field) != value:
            raise web.HTTPBadRequest(text=f"{field} must be a valid {kind} in this guild.")
        cfg[field] = value

    for field, _label in GUILD_COACH_ROLE_FIELDS:
        _apply_int_field(field=field, raw_value=data.get(field), valid_ids=valid_role_ids, kind="role")

    for field, _label in GUILD_CHANNEL_FIELDS:
        _apply_int_field(
            field=field,
            raw_value=data.get(field),
            valid_ids=valid_channel_ids,
            kind="channel",
        )

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


async def guild_discord_metadata_json(request: web.Request) -> web.Response:
    session = _require_session(request)
    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)
    roles, channels = await _get_guild_discord_metadata(request, guild_id=guild_id)
    return web.json_response({"guild_id": guild_id, "roles": roles, "channels": channels})


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
    app["guild_metadata_cache"] = {}
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
    app.router.add_get("/api/guild/{guild_id}/discord_metadata.json", guild_discord_metadata_json)
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
