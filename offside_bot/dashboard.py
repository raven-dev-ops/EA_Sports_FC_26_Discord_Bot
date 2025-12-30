from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, web
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from config import Settings, load_settings
from database import get_client, get_collection, get_global_collection
from services import entitlements_service
from services.analytics_service import get_guild_analytics
from services.audit_log_service import list_audit_events, record_audit_event
from services.error_reporting_service import init_error_reporting, set_guild_tag
from services.guild_config_service import get_guild_config, set_guild_config
from services.guild_settings_schema import (
    FC25_STATS_ENABLED_KEY,
    GUILD_CHANNEL_FIELDS,
    GUILD_COACH_ROLE_FIELDS,
    PREMIUM_COACHES_PIN_ENABLED_KEY,
)
from services.heartbeat_service import get_worker_heartbeat
from services.ops_tasks_service import (
    OPS_TASK_ACTION_REPOST_PORTALS,
    OPS_TASK_ACTION_RUN_SETUP,
    enqueue_ops_task,
    ensure_ops_task_indexes,
    list_ops_tasks,
)
from services.stripe_webhook_service import ensure_stripe_webhook_indexes, handle_stripe_webhook
from services.subscription_service import get_guild_subscription

DISCORD_API_BASE = "https://discord.com/api"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"
ME_URL = f"{DISCORD_API_BASE}/users/@me"
MY_GUILDS_URL = f"{DISCORD_API_BASE}/users/@me/guilds"

COOKIE_NAME = "offside_dashboard_session"
SESSION_TTL_SECONDS = int(os.environ.get("DASHBOARD_SESSION_TTL_SECONDS", "21600").strip() or "21600")
STATE_TTL_SECONDS = 600
GUILD_METADATA_TTL_SECONDS = int(os.environ.get("DASHBOARD_GUILD_METADATA_TTL_SECONDS", "60").strip() or "60")

REQUEST_TIMEOUT_SECONDS = float(os.environ.get("DASHBOARD_REQUEST_TIMEOUT_SECONDS", "15").strip() or "15")
MAX_REQUEST_BYTES = int(os.environ.get("DASHBOARD_MAX_REQUEST_BYTES", "1048576").strip() or "1048576")
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("DASHBOARD_RATE_LIMIT_WINDOW_SECONDS", "60").strip() or "60")
RATE_LIMIT_PUBLIC_MAX = int(os.environ.get("DASHBOARD_RATE_LIMIT_PUBLIC_MAX", "20").strip() or "20")
RATE_LIMIT_WEBHOOK_MAX = int(os.environ.get("DASHBOARD_RATE_LIMIT_WEBHOOK_MAX", "120").strip() or "120")
RATE_LIMIT_DEFAULT_MAX = int(os.environ.get("DASHBOARD_RATE_LIMIT_DEFAULT_MAX", "300").strip() or "300")

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
    all_guilds: list[dict[str, Any]]
    csrf_token: str


_RATE_LIMIT_STATE: dict[tuple[str, str], tuple[int, float]] = {}
_RATE_LIMIT_LAST_SWEEP: float = 0.0


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
    from offside_bot.web_templates import render, safe_html

    return render("base.html", title=title, body=safe_html(body))


def _guild_section_url(guild_id: str, *, section: str) -> str:
    gid = urllib.parse.quote(str(guild_id))
    if section == "overview":
        return f"/guild/{gid}/overview"
    if section == "setup":
        return f"/guild/{gid}/setup"
    if section == "settings":
        return f"/guild/{gid}/settings"
    if section == "permissions":
        return f"/guild/{gid}/permissions"
    if section == "audit":
        return f"/guild/{gid}/audit"
    if section == "ops":
        return f"/guild/{gid}/ops"
    if section == "billing":
        return f"/app/billing?guild_id={gid}"
    return f"/guild/{gid}"


def _app_shell(
    *,
    settings: Settings,
    session: SessionData,
    section: str,
    selected_guild_id: int | None,
    installed: bool | None,
    content: str,
) -> str:
    from offside_bot.web_templates import render, safe_html

    user = session.user
    username = f"{user.get('username','')}#{user.get('discriminator','')}".strip("#")

    selected_guild_str = str(selected_guild_id) if selected_guild_id is not None else ""
    guild_selector = [
        {
            "href": _guild_section_url(str(g.get("id")), section=section),
            "label": str(g.get("name") or g.get("id") or ""),
            "selected": str(g.get("id")) == selected_guild_str,
        }
        for g in session.owner_guilds
        if isinstance(g, dict)
    ]

    guild_plan: str | None = None
    plan_badge = ""
    plan_notice = ""
    if selected_guild_id is not None:
        guild_plan = entitlements_service.get_guild_plan(settings, guild_id=selected_guild_id)
        plan_badge = f"<span class='badge {guild_plan}'>{_escape_html(guild_plan.upper())}</span>"
        if settings.mongodb_uri and guild_plan != entitlements_service.PLAN_PRO:
            subscription = get_guild_subscription(settings, guild_id=selected_guild_id) or {}
            if isinstance(subscription, dict) and (
                str(subscription.get("plan") or "").strip().lower() == entitlements_service.PLAN_PRO
                or subscription.get("customer_id")
                or subscription.get("subscription_id")
            ):
                status = str(subscription.get("status") or "").strip().lower()
                period_end = subscription.get("period_end")
                if isinstance(period_end, datetime) and period_end.tzinfo is None:
                    period_end = period_end.replace(tzinfo=timezone.utc)
                expired_at = period_end.strftime("%Y-%m-%d") if isinstance(period_end, datetime) else None
                if status in {"payment_failed", "past_due", "unpaid"}:
                    title = "Payment issue"
                    detail = "Pro features are disabled until billing is resolved."
                else:
                    title = "Pro expired"
                    detail = "Pro features are disabled, but your server data is preserved."
                suffix = f" (ended {expired_at})" if expired_at else ""
                plan_notice = f"""
                  <div class="card">
                    <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;">
                      <div>
                        <div><span class="badge warn">{_escape_html(title.upper())}</span></div>
                        <div style="margin-top:6px;"><strong>{_escape_html(title)}{_escape_html(suffix)}</strong></div>
                        <div class="muted" style="margin-top:6px;">{_escape_html(detail)}</div>
                      </div>
                      <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                        <a class="btn secondary" href="/app/billing?guild_id={selected_guild_id}">Billing</a>
                        <a class="btn blue" href="/app/upgrade?guild_id={selected_guild_id}&from=notice&section={urllib.parse.quote(section)}">Upgrade</a>
                      </div>
                    </div>
                  </div>
                """

    install_badge = ""
    invite_cta = ""
    if selected_guild_id is not None:
        invite_href = _invite_url(settings, guild_id=str(selected_guild_id), disable_guild_select=True)
        safe_invite_href = _escape_html(invite_href)
        if installed is False:
            install_badge = "<span class='badge warn'>NOT INSTALLED</span>"
            invite_cta = f"<a class='btn blue' href=\"{safe_invite_href}\">Invite bot</a>"
        elif installed is None:
            install_badge = "<span class='badge warn'>UNKNOWN</span>"
            invite_cta = f"<a class='btn blue' href=\"{safe_invite_href}\">Invite bot</a>"

    nav_guild = str(selected_guild_id or "")
    is_pro = guild_plan == entitlements_service.PLAN_PRO
    nav_items: list[dict[str, Any]] = []
    if nav_guild:
        nav_items = [
            {"label": "Overview", "href": _guild_section_url(nav_guild, section="overview"), "active": section == "overview"},
            {"label": "Setup", "href": _guild_section_url(nav_guild, section="setup"), "active": section == "setup"},
            {"label": "Analytics", "href": _guild_section_url(nav_guild, section="analytics"), "active": section == "analytics"},
            {"label": "Settings", "href": _guild_section_url(nav_guild, section="settings"), "active": section == "settings"},
            {"label": "Permissions", "href": _guild_section_url(nav_guild, section="permissions"), "active": section == "permissions"},
        ]
        if is_pro:
            nav_items.append(
                {"label": "Audit Log", "href": _guild_section_url(nav_guild, section="audit"), "active": section == "audit"}
            )
        nav_items.extend(
            [
                {"label": "Ops", "href": _guild_section_url(nav_guild, section="ops"), "active": section == "ops"},
                {"label": "Billing", "href": _guild_section_url(nav_guild, section="billing"), "active": section == "billing"},
            ]
        )

    return render(
        "partials/app_shell.html",
        username=username,
        guild_selector=guild_selector,
        plan_badge=safe_html(plan_badge) if plan_badge else "",
        install_badge=safe_html(install_badge) if install_badge else "",
        invite_cta=safe_html(invite_cta) if invite_cta else "",
        nav_items=nav_items,
        plan_notice=safe_html(plan_notice) if plan_notice else "",
        content=safe_html(content),
    )


def _pro_locked_page(
    *,
    settings: Settings,
    session: SessionData,
    guild_id: int,
    installed: bool | None,
    section: str,
    title: str,
    message: str,
) -> web.Response:
    upgrade_href = f"/app/upgrade?guild_id={guild_id}&from=locked&section={urllib.parse.quote(section)}"
    benefits = [
        ("Premium coach tiers", "Coach Premium and Coach Premium+ roles, caps, and workflow."),
        ("Premium Coaches report", "Public listing embed of Premium coaches and openings."),
        ("FC stats integration", "FC25/FC26 stats lookup, caching, and richer player profiles."),
        ("Banlist integration", "Google Sheets-driven banlist checks and moderation tooling."),
        ("Tournament automation", "Automated brackets, fixtures, and match reporting workflows."),
    ]
    benefits_html = "\n".join(
        f"<li><strong>{_escape_html(name)}</strong> — {_escape_html(desc)}</li>"
        for name, desc in benefits
    )
    body = f"""
      <h1 style="margin-top:0;">{_escape_html(title)}</h1>
      <div class="card">
        <div style="display:flex; gap:10px; align-items:center; justify-content:space-between;">
          <div><strong>Pro feature</strong></div>
          <span class="badge warn">LOCKED</span>
        </div>
        <p class="muted" style="margin-top:8px;">{_escape_html(message)}</p>
        <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
          <a class="btn blue" href="{_escape_html(upgrade_href)}">Upgrade to Pro</a>
          <a class="btn secondary" href="/app/billing?guild_id={guild_id}">Billing</a>
          <a class="btn secondary" href="/guild/{guild_id}/overview">Back to overview</a>
        </div>
      </div>
      <div class="card">
        <h2 style="margin-top:0;">What you get with Pro</h2>
        <ul>
          {benefits_html}
        </ul>
      </div>
    """
    return web.Response(
        text=_html_page(
            title=title,
            body=_app_shell(
                settings=settings,
                session=session,
                section=section,
                selected_guild_id=guild_id,
                installed=installed,
                content=body,
            ),
        ),
        content_type="text/html",
    )


async def upgrade_redirect(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    gid = request.query.get("guild_id", "").strip()
    guild_id = _require_owned_guild(session, guild_id=gid) if gid else 0
    if not guild_id:
        raise web.HTTPBadRequest(text="Missing guild_id.")

    from_value = str(request.query.get("from") or "").strip() or "unknown"
    section = str(request.query.get("section") or "").strip() or "unknown"
    try:
        actor_id = _parse_int(session.user.get("id"))
        actor_username = f"{session.user.get('username','')}#{session.user.get('discriminator','')}".strip("#")
        audit_col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
        record_audit_event(
            guild_id=guild_id,
            category="billing",
            action="upgrade.clicked",
            source="dashboard",
            actor_discord_id=actor_id,
            actor_display_name=str(session.user.get("username") or "") or None,
            actor_username=actor_username or None,
            details={"from": from_value, "section": section, "path": request.path_qs},
            collection=audit_col,
        )
    except Exception:
        pass

    raise web.HTTPFound(f"/app/billing?guild_id={guild_id}")


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
                text = f"Discord API error ({resp.status}): {data}"
                if resp.status == 401:
                    raise web.HTTPUnauthorized(text=text)
                if resp.status == 403:
                    raise web.HTTPForbidden(text=text)
                if resp.status == 404:
                    raise web.HTTPNotFound(text=text)
                raise web.HTTPBadRequest(text=text)
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


async def _fetch_guild_member(
    http: ClientSession,
    *,
    bot_token: str,
    guild_id: int,
    user_id: int,
) -> dict[str, Any] | None:
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}"
    try:
        data = await _discord_bot_get_json(http, url=url, bot_token=bot_token)
    except (web.HTTPForbidden, web.HTTPNotFound):
        return None
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="Discord returned an invalid member payload.")
    return data


def _parse_permissions(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return int(raw)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _apply_overwrite(perms: int, *, allow: int, deny: int) -> int:
    return (perms & ~deny) | allow


def _compute_base_permissions(*, roles_by_id: dict[int, dict[str, Any]], role_ids: set[int]) -> int:
    perms = 0
    for rid in role_ids:
        role = roles_by_id.get(rid) or {}
        if isinstance(role, dict):
            perms |= _parse_permissions(role.get("permissions"))
    return perms


def _compute_channel_permissions(
    *,
    base_perms: int,
    channel: dict[str, Any],
    guild_id: int,
    member_role_ids: set[int],
    member_id: int,
) -> int:
    if base_perms & PERM_ADMINISTRATOR:
        return base_perms

    perms = base_perms
    overwrites_raw = channel.get("permission_overwrites")
    overwrites = overwrites_raw if isinstance(overwrites_raw, list) else []

    everyone_allow = 0
    everyone_deny = 0
    roles_allow = 0
    roles_deny = 0
    member_allow = 0
    member_deny = 0

    for ow in overwrites:
        if not isinstance(ow, dict):
            continue
        oid = _parse_int(ow.get("id"))
        if oid is None:
            continue
        otype_raw = ow.get("type")
        if isinstance(otype_raw, str):
            if otype_raw == "role":
                otype = 0
            elif otype_raw == "member":
                otype = 1
            else:
                continue
        else:
            otype = _parse_int(otype_raw) or -1
        allow = _parse_permissions(ow.get("allow"))
        deny = _parse_permissions(ow.get("deny"))

        if otype == 0 and oid == guild_id:
            everyone_allow |= allow
            everyone_deny |= deny
        elif otype == 0 and oid in member_role_ids:
            roles_allow |= allow
            roles_deny |= deny
        elif otype == 1 and oid == member_id:
            member_allow |= allow
            member_deny |= deny

    perms = _apply_overwrite(perms, allow=everyone_allow, deny=everyone_deny)
    perms = _apply_overwrite(perms, allow=roles_allow, deny=roles_deny)
    perms = _apply_overwrite(perms, allow=member_allow, deny=member_deny)
    return perms


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


async def _detect_bot_installed(request: web.Request, *, guild_id: int) -> tuple[bool | None, str | None]:
    settings: Settings = request.app["settings"]
    http = request.app.get("http")
    if not isinstance(http, ClientSession):
        return None, "Dashboard HTTP client is not ready yet."

    url = f"{DISCORD_API_BASE}/guilds/{guild_id}"
    try:
        await _discord_bot_get_json(http, url=url, bot_token=settings.discord_token)
        return True, None
    except (web.HTTPForbidden, web.HTTPNotFound):
        return False, "Bot is not installed in this server yet."
    except web.HTTPException as exc:
        return None, exc.text or str(exc)
    except Exception as exc:
        return None, str(exc)


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
            all_guilds = doc.get("all_guilds")
            csrf_token = doc.get("csrf_token")
            if (
                isinstance(user, dict)
                and isinstance(owner_guilds, list)
                and isinstance(csrf_token, str)
                and csrf_token
            ):
                if not isinstance(all_guilds, list):
                    all_guilds = owner_guilds
                session = SessionData(
                    created_at=float(created_at),
                    user=user,
                    owner_guilds=[g for g in owner_guilds if isinstance(g, dict)],
                    all_guilds=[g for g in all_guilds if isinstance(g, dict)],
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


def _public_base_url(request: web.Request) -> str:
    scheme = "https" if _is_https(request) else "http"
    host = request.headers.get("X-Forwarded-Host", "").strip() or request.host
    return f"{scheme}://{host}"


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


def _client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return str(request.remote or "")


def _rate_limit_bucket_and_max(path: str) -> tuple[str, int]:
    if path in {"/health", "/ready"}:
        return "health", 10_000
    if path in {"/login", "/install", "/oauth/callback"}:
        return "public", RATE_LIMIT_PUBLIC_MAX
    if path == "/api/billing/webhook":
        return "webhook", RATE_LIMIT_WEBHOOK_MAX
    return "default", RATE_LIMIT_DEFAULT_MAX


def _rate_limit_allowed(*, key: tuple[str, str], limit: int, window_seconds: int) -> tuple[bool, int]:
    now = time.time()
    count, window_start = _RATE_LIMIT_STATE.get(key, (0, now))
    if now - window_start >= window_seconds:
        count, window_start = 0, now
    count += 1
    _RATE_LIMIT_STATE[key] = (count, window_start)
    if count <= limit:
        return True, 0
    retry_after = max(0, int(window_seconds - (now - window_start)))
    return False, retry_after


def _sweep_rate_limit_state(*, window_seconds: int) -> None:
    global _RATE_LIMIT_LAST_SWEEP
    now = time.time()
    if now - _RATE_LIMIT_LAST_SWEEP < max(1, window_seconds):
        return
    _RATE_LIMIT_LAST_SWEEP = now
    cutoff = now - (window_seconds * 2)
    to_delete = [key for key, (_count, start) in _RATE_LIMIT_STATE.items() if start < cutoff]
    for key in to_delete:
        _RATE_LIMIT_STATE.pop(key, None)


@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
    bucket, max_requests = _rate_limit_bucket_and_max(request.path)
    window_seconds = max(1, int(RATE_LIMIT_WINDOW_SECONDS))
    _sweep_rate_limit_state(window_seconds=window_seconds)

    ip = _client_ip(request)
    allowed, retry_after = _rate_limit_allowed(
        key=(bucket, ip),
        limit=max(1, int(max_requests)),
        window_seconds=window_seconds,
    )
    if not allowed:
        logging.warning(
            "event=rate_limited bucket=%s ip=%s path=%s retry_after=%s",
            bucket,
            ip,
            request.path,
            retry_after,
        )
        resp = web.json_response(
            {"ok": False, "error": "rate_limited", "bucket": bucket},
            status=429,
        )
        resp.headers["Retry-After"] = str(retry_after)
        return resp

    return await handler(request)


@web.middleware
async def timeout_middleware(request: web.Request, handler):
    try:
        return await asyncio.wait_for(handler(request), timeout=float(REQUEST_TIMEOUT_SECONDS))
    except asyncio.TimeoutError:
        ip = _client_ip(request)
        logging.warning("event=request_timeout ip=%s path=%s", ip, request.path)
        raise web.HTTPRequestTimeout(text="Request timed out.") from None


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


PERM_ADMINISTRATOR = 1 << 3
PERM_MANAGE_CHANNELS = 1 << 4
PERM_MANAGE_GUILD = 1 << 5
PERM_VIEW_CHANNEL = 1 << 10
PERM_SEND_MESSAGES = 1 << 11
PERM_MANAGE_MESSAGES = 1 << 13
PERM_EMBED_LINKS = 1 << 14
PERM_READ_MESSAGE_HISTORY = 1 << 16
PERM_MANAGE_ROLES = 1 << 28


def _guild_is_eligible(guild: dict[str, Any]) -> bool:
    if guild.get("owner") is True:
        return True
    perms_raw = guild.get("permissions")
    try:
        perms = int(perms_raw) if perms_raw is not None else 0
    except (TypeError, ValueError):
        perms = 0
    return bool(perms & (PERM_ADMINISTRATOR | PERM_MANAGE_GUILD))


async def index(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    session = request.get("session")
    if session is None:
        invite_href = _invite_url(settings)
        from offside_bot.web_templates import render

        html = render("pages/index_public.html", title="Offside Dashboard", invite_href=invite_href)
        return web.Response(text=html, content_type="text/html")

    guild_cards = []
    eligible_ids = {str(g.get("id")) for g in session.owner_guilds}
    for g in session.all_guilds:
        gid = g.get("id")
        name = _escape_html(g.get("name") or gid)
        gid_str = str(gid)
        eligible = gid_str in eligible_ids
        plan_badge = ""
        if eligible and gid_str.isdigit():
            plan = entitlements_service.get_guild_plan(settings, guild_id=int(gid_str))
            plan_badge = f"<span class='badge {plan}'>{_escape_html(plan.upper())}</span>"

        actions = ""
        if eligible:
            actions = (
                f"<div style='margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;'>"
                f"<a class='btn' href='/guild/{gid_str}/overview'>Overview</a>"
                f"<a class='btn secondary' href='/guild/{gid_str}'>Analytics</a>"
                f"<a class='btn secondary' href='/guild/{gid_str}/settings'>Settings</a>"
                f"<a class='btn secondary' href='/app/billing?guild_id={gid_str}'>Billing</a>"
                f"<a class='btn blue' href='/install?guild_id={gid_str}'>Invite bot</a>"
                f"</div>"
            )
        else:
            actions = (
                "<div class='card' style='border:0; padding:0; margin-top:10px;'>"
                "<div class='muted'>Not eligible: requires <strong>Manage Server</strong> permission (or ownership).</div>"
                "</div>"
            )

        guild_cards.append(
            f"<div class='card'><div style='display:flex; gap:10px; align-items:center; justify-content:space-between;'>"
            f"<strong>{name}</strong>{plan_badge}</div>"
            f"<div class='muted'>Guild ID: <code>{gid}</code></div>"
            f"{actions}"
            f"</div>"
        )
    cards_html = "\n".join(guild_cards) if guild_cards else "<p>No servers found.</p>"
    invite_href = _invite_url(settings)
    selected_guild_id = None
    if session.owner_guilds:
        gid = str(session.owner_guilds[0].get("id") or "").strip()
        if gid.isdigit():
            selected_guild_id = int(gid)
    installed, _install_error = (
        await _detect_bot_installed(request, guild_id=selected_guild_id)
        if selected_guild_id is not None
        else (None, None)
    )

    content = f"""
      <h1 style="margin-top:0;">Your servers</h1>
      {cards_html}
      <h2>Invite link</h2>
      <p class="muted">Direct invite URL (shareable):</p>
      <p><a href="{invite_href}">{invite_href}</a></p>
    """
    body = _app_shell(
        settings=settings,
        session=session,
        section="overview",
        selected_guild_id=selected_guild_id,
        installed=installed,
        content=content,
    )
    return web.Response(text=_html_page(title="Offside Dashboard", body=body), content_type="text/html")


def _repo_read_text(filename: str) -> str | None:
    path = Path(__file__).resolve().parents[1] / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _markdown_to_html(text: str) -> str:
    try:
        import markdown  # type: ignore[import-not-found]
    except Exception:
        return f"<pre>{_escape_html(text)}</pre>"
    return markdown.markdown(text, extensions=["extra"], output_format="html")


async def terms_page(_request: web.Request) -> web.Response:
    text = _repo_read_text("TERMS_OF_SERVICE.md")
    if text is None:
        raise web.HTTPNotFound(text="TERMS_OF_SERVICE.md not found.")
    html = _markdown_to_html(text)
    content = f"""
      <p><a href="/">&larr; Back</a></p>
      <h1>Terms of Service</h1>
      <div class="card">{html}</div>
    """
    from offside_bot.web_templates import render, safe_html

    page = render("pages/markdown_page.html", title="Terms", content=safe_html(content))
    return web.Response(text=page, content_type="text/html")


async def privacy_page(_request: web.Request) -> web.Response:
    text = _repo_read_text("PRIVACY_POLICY.md")
    if text is None:
        raise web.HTTPNotFound(text="PRIVACY_POLICY.md not found.")
    html = _markdown_to_html(text)
    content = f"""
      <p><a href="/">&larr; Back</a></p>
      <h1>Privacy Policy</h1>
      <div class="card">{html}</div>
    """
    from offside_bot.web_templates import render, safe_html

    page = render("pages/markdown_page.html", title="Privacy", content=safe_html(content))
    return web.Response(text=page, content_type="text/html")


async def support_page(_request: web.Request) -> web.Response:
    content = """
      <p><a href="/">&larr; Back</a></p>
      <h1>Support</h1>
      <div class="card">
        <p><strong>Need help?</strong></p>
        <p class="muted">Use the links below to get support and troubleshooting help.</p>
        <ul>
          <li><a href="https://github.com/raven-dev-ops/EA_Sports_FC_26_Discord_Bot/issues">GitHub Issues</a></li>
          <li><a href="https://github.com/raven-dev-ops/EA_Sports_FC_26_Discord_Bot#readme">README</a></li>
          <li><a href="https://github.com/raven-dev-ops/EA_Sports_FC_26_Discord_Bot/tree/main/docs">Docs</a></li>
        </ul>
      </div>
    """
    from offside_bot.web_templates import render, safe_html

    page = render("pages/markdown_page.html", title="Support", content=safe_html(content))
    return web.Response(text=page, content_type="text/html")


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def ready(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    if not settings.mongodb_uri:
        return web.json_response({"ok": False, "mongo": "not_configured"}, status=503)
    try:
        get_client(settings).admin.command("ping")
    except Exception as exc:
        return web.json_response({"ok": False, "mongo": str(exc)}, status=503)

    max_age_seconds = int(os.environ.get("WORKER_HEARTBEAT_MAX_AGE_SECONDS", "120").strip() or "120")
    heartbeat = get_worker_heartbeat(settings, worker="bot")
    updated_at = heartbeat.get("updated_at") if heartbeat else None
    if isinstance(updated_at, datetime):
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - updated_at).total_seconds()
        if age > max_age_seconds:
            return web.json_response(
                {"ok": False, "mongo": "ok", "worker": "stale", "worker_age_seconds": age},
                status=503,
            )
        return web.json_response(
            {
                "ok": True,
                "mongo": "ok",
                "worker": "ok",
                "worker_age_seconds": age,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
    return web.json_response({"ok": False, "mongo": "ok", "worker": "missing"}, status=503)


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
        next_path = f"/guild/{requested_guild_id}/overview"

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
    all_guilds = [g for g in guilds if isinstance(g, dict)]
    owner_guilds = [g for g in all_guilds if _guild_is_eligible(g)]

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
            "all_guilds": all_guilds,
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
            set_guild_tag(gid_int)
            return gid_int
    raise web.HTTPForbidden(text="You do not have access to this guild.")


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


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off", ""}:
            return False
    return False


async def guild_settings_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    installed, install_error = await _detect_bot_installed(request, guild_id=guild_id)
    if installed is False:
        invite_href = _invite_url(settings, guild_id=str(guild_id), disable_guild_select=True)
        body = f"""
          <p><a href="/">&larr; Back</a></p>
          <h1>Settings</h1>
          <div class="card">
            <h2 style="margin-top:0;">Invite bot to this server</h2>
            <p class="muted">This server is in your Discord list, but the bot is not installed yet.</p>
            <p><a class="btn blue" href="/install?guild_id={guild_id}">Invite bot to server</a></p>
            <p class="muted">Direct invite URL:</p>
            <p><a href="{invite_href}">{invite_href}</a></p>
          </div>
        """
        return web.Response(
            text=_html_page(
                title="Guild Settings",
                body=_app_shell(
                    settings=settings,
                    session=session,
                    section="settings",
                    selected_guild_id=guild_id,
                    installed=installed,
                    content=body,
                ),
            ),
            content_type="text/html",
        )

    cfg: dict[str, Any] = {}
    try:
        cfg = get_guild_config(guild_id)
    except Exception:
        cfg = {}

    guild_plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    is_pro = guild_plan == entitlements_service.PLAN_PRO
    premium_tiers_enabled = is_pro
    premium_report_enabled = is_pro
    fc25_stats_enabled = is_pro
    upgrade_href = f"/app/upgrade?guild_id={guild_id}&from=settings&section=settings"

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

    if installed is None and install_error:
        if metadata_error:
            metadata_error = f"{metadata_error}; install_check={install_error}"
        else:
            metadata_error = install_error

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
    premium_tiers_disabled_attr = "disabled" if not premium_tiers_enabled else ""
    premium_tiers_note = (
        f"<p class='muted'>Premium coach tiers require Pro. <a href=\"{_escape_html(upgrade_href)}\">Upgrade</a></p>"
        if not premium_tiers_enabled
        else ""
    )

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
            <select name="role_coach_premium_id" {premium_tiers_disabled_attr} style="width:100%; padding:10px; margin-top:6px;">
              {_role_options(premium_role_id)}
            </select>
            <label style="display:block; margin-top:10px;">Coach Premium+ role</label>
            <select name="role_coach_premium_plus_id" {premium_tiers_disabled_attr} style="width:100%; padding:10px; margin-top:6px;">
              {_role_options(premium_plus_role_id)}
            </select>
            {premium_tiers_note}
        """
    else:
        coach_roles_control_html = f"""
            <h3 style="margin:14px 0 6px;">Coach tiers</h3>
            <label>Coach role ID</label><br/>
            <input name="role_coach_id" style="width:100%; padding:10px; margin-top:6px;" value="{_escape_html(coach_role_id or '')}" />
            <label style="display:block; margin-top:10px;">Coach Premium role ID</label>
            <input name="role_coach_premium_id" {premium_tiers_disabled_attr} style="width:100%; padding:10px; margin-top:6px;" value="{_escape_html(premium_role_id or '')}" />
            <label style="display:block; margin-top:10px;">Coach Premium+ role ID</label>
            <input name="role_coach_premium_plus_id" {premium_tiers_disabled_attr} style="width:100%; padding:10px; margin-top:6px;" value="{_escape_html(premium_plus_role_id or '')}" />
            {premium_tiers_note}
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

    premium_pin_enabled = _parse_bool(cfg.get(PREMIUM_COACHES_PIN_ENABLED_KEY))
    premium_pin_checked = "checked" if premium_pin_enabled else ""
    premium_report_disabled_attr = "disabled" if not premium_report_enabled else ""
    premium_report_note = (
        f"<p class='muted'>Premium Coaches report controls require Pro. <a href=\"{_escape_html(upgrade_href)}\">Upgrade</a></p>"
        if not premium_report_enabled
        else ""
    )
    premium_pin_control_html = f"""
            <h3 style="margin:14px 0 6px;">Premium Coaches</h3>
            <label><input type="checkbox" name="{PREMIUM_COACHES_PIN_ENABLED_KEY}" value="1" {premium_pin_checked} {premium_report_disabled_attr} /> Pin listing message</label>
            <p class="muted">Pins the bot's Premium Coaches listing message in the Premium Coaches channel (requires Manage Messages).</p>
            {premium_report_note}
        """

    fc25_value = cfg.get(FC25_STATS_ENABLED_KEY)
    if fc25_value is True:
        fc25_selected = "true"
    elif fc25_value is False:
        fc25_selected = "false"
    else:
        fc25_selected = "default"

    selected_default = "selected" if fc25_selected == "default" else ""
    selected_true = "selected" if fc25_selected == "true" else ""
    selected_false = "selected" if fc25_selected == "false" else ""
    fc25_disabled_attr = "disabled" if not fc25_stats_enabled else ""
    fc25_note = (
        f"<p class='muted'>FC25 stats controls require Pro. <a href=\"{_escape_html(upgrade_href)}\">Upgrade</a></p>"
        if not fc25_stats_enabled
        else ""
    )

    invite_href = _invite_url(settings, guild_id=str(guild_id), disable_guild_select=True)
    saved = request.query.get("saved", "").strip()
    message_html = "<p class='muted'>Saved.</p>" if saved else ""

    rows = "\n".join(
        f"<tr><td><code>{_escape_html(k)}</code></td><td><code>{_escape_html(v)}</code></td></tr>"
        for k, v in sorted(cfg.items())
    ) or "<tr><td colspan='2' class='muted'>No config found yet (bot may not be installed).</td></tr>"

    body = f"""
      <p><a href="/">&larr; Back</a></p>
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
              {premium_pin_control_html}
              <label>FC25 stats override</label><br/>
              <select name="fc25_stats_enabled" {fc25_disabled_attr} style="width:100%; padding:10px; margin-top:6px;">
                <option value="default" {selected_default}>Default</option>
                <option value="true" {selected_true}>Enabled</option>
               <option value="false" {selected_false}>Disabled</option>
             </select>
             {fc25_note}
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
    return web.Response(
        text=_html_page(
            title="Guild Settings",
            body=_app_shell(
                settings=settings,
                session=session,
                section="settings",
                selected_guild_id=guild_id,
                installed=installed,
                content=body,
            ),
        ),
        content_type="text/html",
    )


async def guild_settings_save(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]
    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    installed, _install_error = await _detect_bot_installed(request, guild_id=guild_id)
    if installed is False:
        raise web.HTTPBadRequest(text="Bot is not installed in this server yet. Invite it first.")

    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    is_pro = plan == entitlements_service.PLAN_PRO
    premium_tiers_enabled = is_pro
    premium_report_enabled = is_pro
    fc25_stats_enabled = is_pro

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

    if not premium_tiers_enabled:
        for field in ("role_coach_premium_id", "role_coach_premium_plus_id"):
            attempted = str(data.get(field) or "").strip()
            if attempted:
                raise web.HTTPForbidden(text="Premium coach tiers require Pro.")

    for field, _label in GUILD_COACH_ROLE_FIELDS:
        if field in {"role_coach_premium_id", "role_coach_premium_plus_id"} and not premium_tiers_enabled:
            continue
        _apply_int_field(field=field, raw_value=data.get(field), valid_ids=valid_role_ids, kind="role")

    for field, _label in GUILD_CHANNEL_FIELDS:
        _apply_int_field(
            field=field,
            raw_value=data.get(field),
            valid_ids=valid_channel_ids,
            kind="channel",
        )

    if premium_report_enabled:
        pin_enabled = data.get(PREMIUM_COACHES_PIN_ENABLED_KEY) is not None
        if pin_enabled:
            cfg[PREMIUM_COACHES_PIN_ENABLED_KEY] = True
        else:
            cfg.pop(PREMIUM_COACHES_PIN_ENABLED_KEY, None)
    else:
        if data.get(PREMIUM_COACHES_PIN_ENABLED_KEY) is not None:
            raise web.HTTPForbidden(text="Premium Coaches report controls require Pro.")

    if fc25_stats_enabled:
        fc25_raw = str(data.get(FC25_STATS_ENABLED_KEY, "default")).strip().lower()
        if fc25_raw in {"", "default"}:
            cfg.pop(FC25_STATS_ENABLED_KEY, None)
        elif fc25_raw in {"1", "true", "yes", "on"}:
            cfg[FC25_STATS_ENABLED_KEY] = True
        elif fc25_raw in {"0", "false", "no", "off"}:
            cfg[FC25_STATS_ENABLED_KEY] = False
        else:
            raise web.HTTPBadRequest(text="fc25_stats_enabled must be default/true/false.")
    else:
        fc25_raw = str(data.get(FC25_STATS_ENABLED_KEY) or "").strip().lower()
        if fc25_raw not in {"", "default"}:
            raise web.HTTPForbidden(text="FC25 stats controls require Pro.")

    try:
        actor_id = _parse_int(session.user.get("id"))
        actor_username = f"{session.user.get('username','')}#{session.user.get('discriminator','')}".strip("#")
        set_guild_config(
            guild_id,
            cfg,
            actor_discord_id=actor_id,
            actor_display_name=str(session.user.get("username") or "") or None,
            actor_username=actor_username or None,
            source="dashboard",
        )
    except Exception as exc:
        raise web.HTTPInternalServerError(text=f"Failed to save settings: {exc}") from exc

    raise web.HTTPFound(f"/guild/{guild_id}/settings?saved=1")


async def guild_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    installed, _install_error = await _detect_bot_installed(request, guild_id=guild_id)
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
      <p><a href="/">&larr; Back</a></p>
      <h1>Guild Analytics</h1>
      <div class="row">
        <div class="card">
          <div><strong>Guild</strong></div>
          <div class="muted">ID: <code>{guild_id}</code></div>
          <div class="muted">MongoDB DB: <code>{analytics.db_name}</code></div>
          <div class="muted">Generated: {analytics.generated_at.isoformat()}</div>
          <div style="margin-top:10px;"><a href="/api/guild/{guild_id}/analytics.json">Download JSON</a></div>
          <div style="margin-top:10px;"><a class="btn secondary" href="/guild/{guild_id}/settings">Settings</a></div>
          <div style="margin-top:10px;"><a class="btn secondary" href="/guild/{guild_id}/permissions">Permissions</a></div>
          <div style="margin-top:10px;"><a class="btn secondary" href="/guild/{guild_id}/audit">Audit Log</a></div>
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
    return web.Response(
        text=_html_page(
            title="Guild Analytics",
            body=_app_shell(
                settings=settings,
                session=session,
                section="analytics",
                selected_guild_id=guild_id,
                installed=installed,
                content=body,
            ),
        ),
        content_type="text/html",
    )


async def _channel_has_recent_bot_message(
    http: ClientSession,
    *,
    bot_token: str,
    channel_id: int,
    bot_user_id: int,
    limit: int = 10,
) -> tuple[bool | None, str | None]:
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages?limit={int(limit)}"
    try:
        data = await _discord_bot_get_json(http, url=url, bot_token=bot_token)
    except web.HTTPForbidden as exc:
        return None, exc.text or "Forbidden."
    except web.HTTPNotFound:
        return False, "Channel not found."
    except web.HTTPException as exc:
        return None, exc.text or str(exc)
    except Exception as exc:
        return None, str(exc)

    if not isinstance(data, list):
        return None, "Discord returned an invalid messages payload."
    for message in data:
        if not isinstance(message, dict):
            continue
        author = message.get("author")
        if not isinstance(author, dict):
            continue
        if str(author.get("id")) == str(bot_user_id):
            return True, None
    return False, None


async def guild_overview_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    invite_href = _invite_url(settings, guild_id=str(guild_id), disable_guild_select=True)
    installed, install_error = await _detect_bot_installed(request, guild_id=guild_id)

    cfg: dict[str, Any] = {}
    config_error: str | None = None
    if settings.mongodb_uri:
        try:
            cfg = get_guild_config(guild_id)
        except Exception as exc:
            cfg = {}
            config_error = str(exc)
    else:
        config_error = "MongoDB is not configured."

    roles: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    metadata_error: str | None = None
    if installed is True:
        try:
            roles, channels = await _get_guild_discord_metadata(request, guild_id=guild_id)
        except web.HTTPException as exc:
            metadata_error = exc.text or str(exc)
        except Exception as exc:
            metadata_error = str(exc)

    roles_by_id: dict[int, dict[str, Any]] = {}
    for role_doc in roles:
        rid = _parse_int(role_doc.get("id"))
        if rid is not None:
            roles_by_id[rid] = role_doc

    channel_ids: set[int] = set()
    for channel_doc in channels:
        cid = _parse_int(channel_doc.get("id"))
        if cid is not None:
            channel_ids.add(cid)

    def _badge(label: str, kind: str) -> str:
        return f"<span class='badge {kind}'>{_escape_html(label)}</span>"

    def _check_row(*, name: str, status: str, details: str, href: str) -> str:
        return (
            "<tr>"
            f"<td><strong>{_escape_html(name)}</strong></td>"
            f"<td>{status}</td>"
            f"<td class='muted'>{_escape_html(details)}</td>"
            f"<td><a href=\"{_escape_html(href)}\">Fix</a></td>"
            "</tr>"
        )

    install_status = _badge("OK", "ok") if installed is True else _badge("WARN", "warn")
    install_details = "Installed and reachable via bot token."
    install_fix = f"/guild/{guild_id}/settings"
    if installed is False:
        install_details = install_error or "Bot is not installed in this server yet."
        install_fix = invite_href
    elif installed is None:
        install_status = _badge("UNKNOWN", "warn")
        install_details = install_error or "Unable to verify install status."
        install_fix = f"/guild/{guild_id}/permissions"

    missing_role_fields: list[str] = []
    missing_roles_in_discord: list[str] = []
    for field, _label in GUILD_COACH_ROLE_FIELDS:
        value = _parse_int(cfg.get(field))
        if value is None:
            missing_role_fields.append(field)
        elif roles and value not in roles_by_id:
            missing_roles_in_discord.append(field)

    roles_status = _badge("OK", "ok")
    roles_details = "All required coach roles are configured."
    if config_error:
        roles_status = _badge("UNKNOWN", "warn")
        roles_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        roles_status = _badge("WARN", "warn")
        roles_details = "Install the bot to validate roles."
    elif metadata_error:
        roles_status = _badge("UNKNOWN", "warn")
        roles_details = f"Unable to load Discord roles: {metadata_error}"
    elif missing_role_fields or missing_roles_in_discord:
        roles_status = _badge("WARN", "warn")
        parts: list[str] = []
        if missing_role_fields:
            parts.append(f"Missing in settings: {', '.join(missing_role_fields)}")
        if missing_roles_in_discord:
            parts.append(f"Not found in Discord: {', '.join(missing_roles_in_discord)}")
        roles_details = " · ".join(parts) or "Roles are not fully configured."

    required_channel_fields = [
        (field, label)
        for field, label in GUILD_CHANNEL_FIELDS
        if field != "channel_staff_monitor_id" or settings.test_mode
    ]
    missing_channel_fields: list[str] = []
    missing_channels_in_discord: list[str] = []
    for field, _label in required_channel_fields:
        value = _parse_int(cfg.get(field))
        if value is None:
            missing_channel_fields.append(field)
        elif channels and value not in channel_ids:
            missing_channels_in_discord.append(field)

    channels_status = _badge("OK", "ok")
    channels_details = "All required channels are configured."
    if config_error:
        channels_status = _badge("UNKNOWN", "warn")
        channels_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        channels_status = _badge("WARN", "warn")
        channels_details = "Install the bot to validate channels."
    elif metadata_error:
        channels_status = _badge("UNKNOWN", "warn")
        channels_details = f"Unable to load Discord channels: {metadata_error}"
    elif missing_channel_fields or missing_channels_in_discord:
        channels_status = _badge("WARN", "warn")
        parts = []
        if missing_channel_fields:
            parts.append(f"Missing in settings: {', '.join(missing_channel_fields)}")
        if missing_channels_in_discord:
            parts.append(f"Not found in Discord: {', '.join(missing_channels_in_discord)}")
        channels_details = " · ".join(parts) or "Channels are not fully configured."

    posts_status = _badge("OK", "ok")
    posts_details = "Dashboard and listing embeds detected."
    if config_error:
        posts_status = _badge("UNKNOWN", "warn")
        posts_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        posts_status = _badge("WARN", "warn")
        posts_details = "Install the bot to validate posted embeds."
    else:
        http = request.app.get("http")
        if not isinstance(http, ClientSession):
            posts_status = _badge("UNKNOWN", "warn")
            posts_details = "Dashboard HTTP client is not ready yet."
        else:
            bot_user_id = int(settings.discord_application_id)
            post_fields = [
                "channel_staff_portal_id",
                "channel_manager_portal_id",
                "channel_club_portal_id",
                "channel_coach_portal_id",
                "channel_recruit_portal_id",
                "channel_roster_listing_id",
                "channel_recruit_listing_id",
                "channel_club_listing_id",
                "channel_premium_coaches_id",
            ]
            missing_posts: list[str] = []
            unknown_posts: list[str] = []
            missing_config: list[str] = []
            for field in post_fields:
                channel_id = _parse_int(cfg.get(field))
                if channel_id is None:
                    missing_config.append(field)
                    continue
                ok, err = await _channel_has_recent_bot_message(
                    http,
                    bot_token=settings.discord_token,
                    channel_id=channel_id,
                    bot_user_id=bot_user_id,
                    limit=10,
                )
                if ok is True:
                    continue
                if ok is False:
                    missing_posts.append(field)
                else:
                    unknown_posts.append(field)
                    if err:
                        posts_details = f"Unable to read messages in some channels: {err}"

            if missing_config:
                posts_status = _badge("WARN", "warn")
                posts_details = f"Missing channel settings: {', '.join(missing_config)}"
            elif unknown_posts:
                posts_status = _badge("UNKNOWN", "warn")
                posts_details = "Unable to verify some channels (missing Read Message History?)."
            elif missing_posts:
                posts_status = _badge("WARN", "warn")
                posts_details = f"Missing embeds in: {', '.join(missing_posts)}"

    checks = "\n".join(
        [
            _check_row(
                name="Bot installed",
                status=install_status,
                details=install_details,
                href=install_fix,
            ),
            _check_row(
                name="Coach roles",
                status=roles_status,
                details=roles_details,
                href=f"/guild/{guild_id}/settings",
            ),
            _check_row(
                name="Channels",
                status=channels_status,
                details=channels_details,
                href=f"/guild/{guild_id}/settings",
            ),
            _check_row(
                name="Portals posted",
                status=posts_status,
                details=posts_details,
                href=f"/guild/{guild_id}/ops",
            ),
        ]
    )

    db_name = "not_configured"
    submissions_display = "—"
    approvals_display = "—"
    tournaments_display = "—"
    if settings.mongodb_uri:
        analytics = get_guild_analytics(settings, guild_id=guild_id)
        db_name = analytics.db_name
        submissions_display = str(int(analytics.record_type_counts.get("submission_message", 0)))
        tournaments_display = str(int(analytics.record_type_counts.get("tournament", 0)))
        try:
            roster_audits = get_collection(settings, record_type="roster_audit", guild_id=guild_id)
            approvals_display = str(
                int(roster_audits.count_documents({"record_type": "roster_audit", "action": "APPROVED"}))
            )
        except Exception:
            approvals_display = "0"

    disabled_attr = "disabled" if installed is False else ""
    actions_block = ""
    if not settings.mongodb_uri:
        actions_block = "<div class='card'><p class='muted'>MongoDB is not configured; ops actions are unavailable.</p></div>"
    else:
        actions_block = f"""
          <div class="card">
            <div><strong>Quick actions</strong></div>
            <div class="muted" style="margin-top:8px;">Run setup and repost portals from the bot worker.</div>
            <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
              <form method="post" action="/api/guild/{guild_id}/ops/run_setup">
                <input type="hidden" name="csrf" value="{_escape_html(session.csrf_token)}" />
                <button class="btn" type="submit" {disabled_attr}>Run setup now</button>
              </form>
              <form method="post" action="/api/guild/{guild_id}/ops/repost_portals">
                <input type="hidden" name="csrf" value="{_escape_html(session.csrf_token)}" />
                <button class="btn secondary" type="submit" {disabled_attr}>Repost portals</button>
              </form>
              <a class="btn secondary" href="/guild/{guild_id}/settings">Open settings</a>
            </div>
          </div>
        """

    body = f"""
      <h1 style="margin-top:0;">Overview</h1>
      <div class="row">
        <div class="card">
          <div><strong>Guild</strong></div>
          <div class="muted">ID: <code>{guild_id}</code></div>
          <div class="muted">MongoDB DB: <code>{_escape_html(db_name)}</code></div>
          <div class="muted">Test mode: <code>{'true' if settings.test_mode else 'false'}</code></div>
        </div>
        {actions_block}
      </div>
      <div class="card">
        <h2 style="margin-top:0;">Setup checklist</h2>
        <table>
          <thead><tr><th>item</th><th>status</th><th>details</th><th></th></tr></thead>
          <tbody>{checks}</tbody>
        </table>
      </div>
      <div class="row">
        <div class="card">
          <div class="muted">Roster submissions</div>
          <div style="font-size:32px; font-weight:800;">{_escape_html(submissions_display)}</div>
        </div>
        <div class="card">
          <div class="muted">Approvals</div>
          <div style="font-size:32px; font-weight:800;">{_escape_html(approvals_display)}</div>
        </div>
        <div class="card">
          <div class="muted">Tournaments created</div>
          <div style="font-size:32px; font-weight:800;">{_escape_html(tournaments_display)}</div>
        </div>
      </div>
      <p class="muted">Need help? Use the Permissions and Ops pages to troubleshoot setup.</p>
    """

    return web.Response(
        text=_html_page(
            title="Overview",
            body=_app_shell(
                settings=settings,
                session=session,
                section="overview",
                selected_guild_id=guild_id,
                installed=installed,
                content=body,
            ),
        ),
        content_type="text/html",
    )


async def guild_setup_wizard_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    is_pro = plan == entitlements_service.PLAN_PRO

    installed, install_error = await _detect_bot_installed(request, guild_id=guild_id)

    cfg: dict[str, Any] = {}
    config_error: str | None = None
    if settings.mongodb_uri:
        try:
            cfg = get_guild_config(guild_id)
        except Exception as exc:
            cfg = {}
            config_error = str(exc)
    else:
        config_error = "MongoDB is not configured."

    roles: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    metadata_error: str | None = None
    if installed is True:
        try:
            roles, channels = await _get_guild_discord_metadata(request, guild_id=guild_id)
        except web.HTTPException as exc:
            metadata_error = exc.text or str(exc)
        except Exception as exc:
            metadata_error = str(exc)

    roles_by_id: dict[int, dict[str, Any]] = {}
    for role_doc in roles:
        rid = _parse_int(role_doc.get("id"))
        if rid is not None:
            roles_by_id[rid] = role_doc

    channel_ids: set[int] = set()
    for channel_doc in channels:
        cid = _parse_int(channel_doc.get("id"))
        if cid is not None:
            channel_ids.add(cid)

    def _badge(label: str, kind: str) -> str:
        return f"<span class='badge {kind}'>{_escape_html(label)}</span>"

    def _step_row(*, step: str, status: str, details: str, action_html: str) -> str:
        return (
            "<tr>"
            f"<td><strong>{_escape_html(step)}</strong></td>"
            f"<td>{status}</td>"
            f"<td class='muted'>{_escape_html(details)}</td>"
            f"<td>{action_html}</td>"
            "</tr>"
        )

    # Step 1: Permissions (quick summary; full details on /permissions)
    perms_status = _badge("UNKNOWN", "warn")
    perms_details = "Unable to verify bot permissions."
    perms_ok = False
    if installed is False:
        perms_status = _badge("WARN", "warn")
        perms_details = install_error or "Bot is not installed in this server yet."
    elif installed is True:
        http = request.app.get("http")
        if not isinstance(http, ClientSession):
            perms_details = "Dashboard HTTP client is not ready yet."
        else:
            bot_user_id = int(settings.discord_application_id)
            bot_member = await _fetch_guild_member(
                http,
                bot_token=settings.discord_token,
                guild_id=guild_id,
                user_id=bot_user_id,
            )
            if bot_member is None or not roles:
                perms_details = metadata_error or "Unable to load bot member/roles."
            else:
                member_role_ids: set[int] = {guild_id}
                member_roles_raw = bot_member.get("roles")
                if isinstance(member_roles_raw, list):
                    for rid in member_roles_raw:
                        rid_int = _parse_int(rid)
                        if rid_int is not None:
                            member_role_ids.add(rid_int)

                base_perms = _compute_base_permissions(roles_by_id=roles_by_id, role_ids=member_role_ids)
                is_admin = bool(base_perms & PERM_ADMINISTRATOR)
                required = [("Manage Channels", PERM_MANAGE_CHANNELS), ("Manage Roles", PERM_MANAGE_ROLES)]
                missing_required = [name for name, bit in required if not (base_perms & bit)]
                missing_optional = ["Manage Messages"] if not (base_perms & PERM_MANAGE_MESSAGES) else []

                if is_admin or not missing_required:
                    perms_ok = True
                    perms_status = _badge("OK", "ok")
                    perms_details = (
                        "Required permissions are present."
                        if not missing_optional
                        else f"Missing optional: {', '.join(missing_optional)}"
                    )
                else:
                    perms_status = _badge("WARN", "warn")
                    perms_details = f"Missing: {', '.join(missing_required)}"

    # Step 2: Channels + categories
    required_channel_fields = [
        (field, label)
        for field, label in GUILD_CHANNEL_FIELDS
        if field != "channel_staff_monitor_id" or settings.test_mode
        if field != "channel_premium_coaches_id" or is_pro
    ]
    channels_missing_settings: list[str] = []
    channels_missing_discord: list[str] = []
    for field, _label in required_channel_fields:
        value = _parse_int(cfg.get(field))
        if value is None:
            channels_missing_settings.append(field)
        elif channels and value not in channel_ids:
            channels_missing_discord.append(field)

    channels_ok = False
    if config_error:
        channels_status = _badge("UNKNOWN", "warn")
        channels_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        channels_status = _badge("WARN", "warn")
        channels_details = "Install the bot to validate channels."
    elif metadata_error:
        channels_status = _badge("UNKNOWN", "warn")
        channels_details = f"Unable to load Discord channels: {metadata_error}"
    elif channels_missing_settings or channels_missing_discord:
        channels_status = _badge("WARN", "warn")
        parts: list[str] = []
        if channels_missing_settings:
            parts.append(f"Missing in settings: {', '.join(channels_missing_settings)}")
        if channels_missing_discord:
            parts.append(f"Not found in Discord: {', '.join(channels_missing_discord)}")
        channels_details = " · ".join(parts) or "Channels are not ready."
    else:
        channels_ok = True
        channels_status = _badge("OK", "ok")
        channels_details = "Channels are configured."

    # Step 3: Roles
    required_role_fields = [("role_coach_id", "Coach role")]
    if is_pro:
        required_role_fields.extend(
            [
                ("role_coach_premium_id", "Coach Premium role"),
                ("role_coach_premium_plus_id", "Coach Premium+ role"),
            ]
        )
    roles_missing_settings: list[str] = []
    roles_missing_discord: list[str] = []
    for field, _label in required_role_fields:
        value = _parse_int(cfg.get(field))
        if value is None:
            roles_missing_settings.append(field)
        elif roles and value not in roles_by_id:
            roles_missing_discord.append(field)

    roles_ok = False
    if config_error:
        roles_status = _badge("UNKNOWN", "warn")
        roles_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        roles_status = _badge("WARN", "warn")
        roles_details = "Install the bot to validate roles."
    elif metadata_error:
        roles_status = _badge("UNKNOWN", "warn")
        roles_details = f"Unable to load Discord roles: {metadata_error}"
    elif roles_missing_settings or roles_missing_discord:
        roles_status = _badge("WARN", "warn")
        parts = []
        if roles_missing_settings:
            parts.append(f"Missing in settings: {', '.join(roles_missing_settings)}")
        if roles_missing_discord:
            parts.append(f"Not found in Discord: {', '.join(roles_missing_discord)}")
        roles_details = " · ".join(parts) or "Roles are not ready."
    else:
        roles_ok = True
        roles_status = _badge("OK", "ok")
        roles_details = "Roles are configured."

    # Step 4: Portals posted
    portals_ok = False
    portals_status = _badge("UNKNOWN", "warn")
    portals_details = "Unable to verify posted portals."
    if config_error:
        portals_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        portals_status = _badge("WARN", "warn")
        portals_details = "Install the bot to validate posted portals."
    else:
        http = request.app.get("http")
        if not isinstance(http, ClientSession):
            portals_details = "Dashboard HTTP client is not ready yet."
        else:
            bot_user_id = int(settings.discord_application_id)
            portal_fields = [
                "channel_staff_portal_id",
                "channel_manager_portal_id",
                "channel_club_portal_id",
                "channel_coach_portal_id",
                "channel_recruit_portal_id",
                "channel_roster_listing_id",
                "channel_recruit_listing_id",
                "channel_club_listing_id",
            ]
            if is_pro:
                portal_fields.append("channel_premium_coaches_id")

            missing_config: list[str] = []
            missing_posts: list[str] = []
            unknown_posts: list[str] = []
            for field in portal_fields:
                channel_id = _parse_int(cfg.get(field))
                if channel_id is None:
                    missing_config.append(field)
                    continue
                ok, _err = await _channel_has_recent_bot_message(
                    http,
                    bot_token=settings.discord_token,
                    channel_id=channel_id,
                    bot_user_id=bot_user_id,
                    limit=10,
                )
                if ok is True:
                    continue
                if ok is False:
                    missing_posts.append(field)
                else:
                    unknown_posts.append(field)

            if missing_config:
                portals_status = _badge("WARN", "warn")
                portals_details = f"Missing channel settings: {', '.join(missing_config)}"
            elif unknown_posts:
                portals_status = _badge("UNKNOWN", "warn")
                portals_details = "Unable to verify some channels (missing Read Message History?)."
            elif missing_posts:
                portals_status = _badge("WARN", "warn")
                portals_details = f"Missing embeds in: {', '.join(missing_posts)}"
            else:
                portals_ok = True
                portals_status = _badge("OK", "ok")
                portals_details = "Portals/instructions detected."

    ready = bool(installed is True and perms_ok and channels_ok and roles_ok and portals_ok)
    ready_badge = _badge("READY", "ok") if ready else _badge("NOT READY", "warn")
    ready_details = "This server looks ready to use." if ready else "Complete the steps below to finish setup."

    disabled_attr = "disabled" if installed is False or not settings.mongodb_uri else ""

    tasks: list[dict[str, Any]] = []
    tasks_error: str | None = None
    if settings.mongodb_uri:
        try:
            tasks = list_ops_tasks(settings, guild_id=guild_id, limit=10)
        except Exception as exc:
            tasks_error = str(exc)
            tasks = []

    task_rows: list[str] = []
    for task in tasks:
        created_at = task.get("created_at")
        created = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at or "")
        action = str(task.get("action") or "")
        status = str(task.get("status") or "")
        task_rows.append(
            "<tr>"
            f"<td><code>{_escape_html(created)}</code></td>"
            f"<td><code>{_escape_html(action)}</code></td>"
            f"<td><code>{_escape_html(status)}</code></td>"
            "</tr>"
        )
    tasks_table = (
        "\n".join(task_rows)
        if task_rows
        else "<tr><td colspan='3' class='muted'>No recent ops tasks yet.</td></tr>"
    )
    tasks_note = (
        f"<p class='muted'>Tasks unavailable: <code>{_escape_html(tasks_error)}</code></p>" if tasks_error else ""
    )

    steps_table = "\n".join(
        [
            _step_row(
                step="Step 1: Permissions",
                status=perms_status,
                details=perms_details,
                action_html=f"<a href=\"/guild/{guild_id}/permissions\">Open</a>",
            ),
            _step_row(
                step="Step 2: Channels",
                status=channels_status,
                details=channels_details,
                action_html=f"<a href=\"/guild/{guild_id}/settings\">Review</a>",
            ),
            _step_row(
                step="Step 3: Roles",
                status=roles_status,
                details=roles_details,
                action_html=f"<a href=\"/guild/{guild_id}/settings\">Review</a>",
            ),
            _step_row(
                step="Step 4: Post portals",
                status=portals_status,
                details=portals_details,
                action_html=f"<a href=\"/guild/{guild_id}/ops\">Ops</a>",
            ),
            _step_row(
                step="Step 5: Verify",
                status=_badge("OK", "ok") if ready else _badge("PENDING", "warn"),
                details="Setup wizard complete." if ready else "Run setup and repost portals, then refresh.",
                action_html=f"<a href=\"/guild/{guild_id}/overview\">Overview</a>",
            ),
        ]
    )

    queued = request.query.get("queued", "").strip()
    queued_msg = "<div class='card'><strong>Setup queued.</strong> Refresh this page in a few seconds.</div>" if queued else ""

    body = f"""
      <h1 style="margin-top:0;">Setup Wizard</h1>
      {queued_msg}
      <div class="row">
        <div class="card">
          <div><strong>Status</strong></div>
          <div style="margin-top:6px;">{ready_badge}</div>
          <p class="muted" style="margin-top:10px;">{_escape_html(ready_details)}</p>
          <p class="muted">Plan: <span class="badge {plan}">{_escape_html(plan.upper())}</span></p>
        </div>
        <div class="card">
          <div><strong>One-click setup</strong></div>
          <p class="muted" style="margin-top:8px;">Queues <code>run_setup</code> then <code>repost_portals</code> on the bot worker.</p>
          <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
            <form method="post" action="/api/guild/{guild_id}/ops/run_full_setup">
              <input type="hidden" name="csrf" value="{_escape_html(session.csrf_token)}" />
              <button class="btn blue" type="submit" {disabled_attr}>Run full setup</button>
            </form>
            <form method="post" action="/api/guild/{guild_id}/ops/run_setup">
              <input type="hidden" name="csrf" value="{_escape_html(session.csrf_token)}" />
              <button class="btn" type="submit" {disabled_attr}>Run setup</button>
            </form>
            <form method="post" action="/api/guild/{guild_id}/ops/repost_portals">
              <input type="hidden" name="csrf" value="{_escape_html(session.csrf_token)}" />
              <button class="btn secondary" type="submit" {disabled_attr}>Repost portals</button>
            </form>
          </div>
          <p class="muted" style="margin-top:10px;">If tasks don't run, check worker heartbeat on the Ops page.</p>
        </div>
      </div>
      <div class="card">
        <h2 style="margin-top:0;">Steps</h2>
        <table>
          <thead><tr><th>step</th><th>status</th><th>details</th><th></th></tr></thead>
          <tbody>{steps_table}</tbody>
        </table>
      </div>
      <div class="card">
        <h2 style="margin-top:0;">Recent ops tasks</h2>
        {tasks_note}
        <table>
          <thead><tr><th>created</th><th>action</th><th>status</th></tr></thead>
          <tbody>{tasks_table}</tbody>
        </table>
        <p class="muted" style="margin-top:10px;"><a href="/guild/{guild_id}/ops">Open Ops</a></p>
      </div>
    """
    return web.Response(
        text=_html_page(
            title="Setup Wizard",
            body=_app_shell(
                settings=settings,
                session=session,
                section="setup",
                selected_guild_id=guild_id,
                installed=installed,
                content=body,
            ),
        ),
        content_type="text/html",
    )


async def guild_permissions_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    invite_href = _invite_url(settings, guild_id=str(guild_id), disable_guild_select=True)
    installed, install_error = await _detect_bot_installed(request, guild_id=guild_id)
    if installed is False:
        body = f"""
          <p><a href="/guild/{guild_id}">&larr; Back</a></p>
          <h1>Permissions Check</h1>
          <div class="card">
            <p class="muted">{_escape_html(install_error or 'Bot is not installed in this server yet.')}</p>
            <div style="margin-top:10px;">
              <a class="btn blue" href="{invite_href}">Invite bot to this server</a>
            </div>
          </div>
        """
        return web.Response(
            text=_html_page(
                title="Permissions",
                body=_app_shell(
                    settings=settings,
                    session=session,
                    section="permissions",
                    selected_guild_id=guild_id,
                    installed=installed,
                    content=body,
                ),
            ),
            content_type="text/html",
        )

    roles: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    metadata_error: str | None = None
    try:
        roles, channels = await _get_guild_discord_metadata(request, guild_id=guild_id)
    except web.HTTPException as exc:
        metadata_error = exc.text or str(exc)
    except Exception as exc:
        metadata_error = str(exc)

    http = request.app.get("http")
    if not isinstance(http, ClientSession):
        raise web.HTTPInternalServerError(text="Dashboard HTTP client is not ready yet.")

    bot_user_id = int(settings.discord_application_id)
    bot_member = await _fetch_guild_member(
        http,
        bot_token=settings.discord_token,
        guild_id=guild_id,
        user_id=bot_user_id,
    )

    if bot_member is None or not roles:
        message = metadata_error or install_error or "Unable to load bot membership details."
        body = f"""
          <p><a href="/guild/{guild_id}">&larr; Back</a></p>
          <h1>Permissions Check</h1>
          <div class="card">
            <p class="muted">{_escape_html(message)}</p>
            <div style="margin-top:10px;">
              <a class="btn blue" href="{invite_href}">Invite bot to this server</a>
            </div>
          </div>
        """
        return web.Response(
            text=_html_page(
                title="Permissions",
                body=_app_shell(
                    settings=settings,
                    session=session,
                    section="permissions",
                    selected_guild_id=guild_id,
                    installed=installed,
                    content=body,
                ),
            ),
            content_type="text/html",
        )

    roles_by_id: dict[int, dict[str, Any]] = {}
    for role_doc in roles:
        rid = _parse_int(role_doc.get("id"))
        if rid is not None:
            roles_by_id[rid] = role_doc

    member_role_ids: set[int] = {guild_id}
    member_roles_raw = bot_member.get("roles")
    if isinstance(member_roles_raw, list):
        for rid in member_roles_raw:
            rid_int = _parse_int(rid)
            if rid_int is not None:
                member_role_ids.add(rid_int)

    base_perms = _compute_base_permissions(roles_by_id=roles_by_id, role_ids=member_role_ids)
    is_admin = bool(base_perms & PERM_ADMINISTRATOR)

    required_guild_perms = [
        ("Manage Channels", PERM_MANAGE_CHANNELS, "Create/repair Offside channels and categories."),
        ("Manage Roles", PERM_MANAGE_ROLES, "Create/assign Coach tier roles."),
        ("Manage Messages", PERM_MANAGE_MESSAGES, "Pin/unpin listings and clean up bot messages."),
    ]
    guild_rows = []
    for name, bit, why in required_guild_perms:
        ok = is_admin or bool(base_perms & bit)
        status = "OK" if ok else "Missing"
        guild_rows.append(
            "<tr>"
            f"<td>{_escape_html(name)}</td>"
            f"<td><code>{status}</code></td>"
            f"<td class='muted'>{_escape_html(why)}</td>"
            "</tr>"
        )
    guild_table = "\n".join(guild_rows)

    top_role_name = ""
    top_role_pos = 0
    for rid in member_role_ids:
        if rid == guild_id:
            continue
        role_doc = roles_by_id.get(rid) or {}
        if not isinstance(role_doc, dict):
            continue
        pos = _parse_int(role_doc.get("position")) or 0
        if pos > top_role_pos:
            top_role_pos = pos
            top_role_name = str(role_doc.get("name") or rid)

    cfg: dict[str, Any]
    try:
        cfg = get_guild_config(guild_id)
    except Exception:
        cfg = {}

    def _best_role_id_by_name(name: str) -> int | None:
        best_id = None
        best_pos = -1
        target = name.casefold()
        for role_doc in roles:
            if str(role_doc.get("name") or "").casefold() != target:
                continue
            rid = _parse_int(role_doc.get("id"))
            pos = _parse_int(role_doc.get("position")) or 0
            if rid is not None and pos > best_pos:
                best_id = rid
                best_pos = pos
        return best_id

    coach_role_ids = [
        ("Coach", _parse_int(cfg.get("role_coach_id")) or _best_role_id_by_name("Coach")),
        ("Coach Premium", _parse_int(cfg.get("role_coach_premium_id")) or _best_role_id_by_name("Coach Premium")),
        (
            "Coach Premium+",
            _parse_int(cfg.get("role_coach_premium_plus_id")) or _best_role_id_by_name("Coach Premium+"),
        ),
    ]

    hierarchy_rows: list[str] = []
    for label, rid in coach_role_ids:
        if rid is None:
            hierarchy_rows.append(
                f"<tr><td>{_escape_html(label)}</td><td><code>Not configured</code></td><td class='muted'>Run setup to create roles.</td></tr>"
            )
            continue
        target_role = roles_by_id.get(rid)
        if target_role is None:
            hierarchy_rows.append(
                f"<tr><td>{_escape_html(label)}</td><td><code>Missing role</code></td><td class='muted'>Role ID <code>{rid}</code> not found.</td></tr>"
            )
            continue
        role_pos = _parse_int(target_role.get("position")) or 0
        ok = top_role_pos > role_pos
        status = "OK" if ok else "Bot role too low"
        details = (
            f"Bot top role: <code>{_escape_html(top_role_name or 'unknown')}</code> (pos {top_role_pos}); "
            f"Target: <code>{_escape_html(target_role.get('name') or rid)}</code> (pos {role_pos})"
        )
        hint = (
            "Move the bot's role above the Coach roles in Server Settings &rarr; Roles."
            if not ok
            else details
        )
        hierarchy_rows.append(
            "<tr>"
            f"<td>{_escape_html(label)}</td>"
            f"<td><code>{status}</code></td>"
            f"<td class='muted'>{hint}</td>"
            "</tr>"
        )
    hierarchy_table = "\n".join(hierarchy_rows)

    channels_by_id: dict[int, dict[str, Any]] = {}
    for ch in channels:
        cid = _parse_int(ch.get("id"))
        if cid is not None:
            channels_by_id[cid] = ch

    required_channel_bits = [
        ("View Channel", PERM_VIEW_CHANNEL),
        ("Send Messages", PERM_SEND_MESSAGES),
        ("Embed Links", PERM_EMBED_LINKS),
        ("Read History", PERM_READ_MESSAGE_HISTORY),
    ]
    channel_rows: list[str] = []
    for field, label in GUILD_CHANNEL_FIELDS:
        channel_id = _parse_int(cfg.get(field))
        if channel_id is None:
            continue
        channel = channels_by_id.get(channel_id)
        if channel is None:
            channel_rows.append(
                f"<tr><td>{_escape_html(label)}</td><td><code>Missing channel</code></td><td class='muted'>Channel ID <code>{channel_id}</code> not found.</td></tr>"
            )
            continue
        perms = _compute_channel_permissions(
            base_perms=base_perms,
            channel=channel,
            guild_id=guild_id,
            member_role_ids=member_role_ids,
            member_id=bot_user_id,
        )
        missing = [name for name, bit in required_channel_bits if not (is_admin or bool(perms & bit))]
        status = "OK" if not missing else "Missing: " + ", ".join(missing)
        channel_name = str(channel.get("name") or channel_id)
        channel_rows.append(
            "<tr>"
            f"<td>{_escape_html(label)}</td>"
            f"<td><code>{_escape_html(status)}</code></td>"
            f"<td class='muted'>#{_escape_html(channel_name)} (<code>{channel_id}</code>)</td>"
            "</tr>"
        )
    channel_table = "\n".join(channel_rows) or "<tr><td colspan='3' class='muted'>No channels configured yet.</td></tr>"

    admin_badge = "<span class='badge pro'>ADMIN</span>" if is_admin else ""
    body = f"""
      <p><a href="/guild/{guild_id}">&larr; Back</a></p>
      <h1>Permissions Check {admin_badge}</h1>
      <div class="row">
        <div class="card">
          <div><strong>Guild</strong></div>
          <div class="muted">ID: <code>{guild_id}</code></div>
          <div class="muted">Bot top role: <code>{_escape_html(top_role_name or 'unknown')}</code> (pos {top_role_pos})</div>
          <div style="margin-top:10px;">
            <a class="btn secondary" href="/guild/{guild_id}/settings">Open settings</a>
          </div>
        </div>
        <div class="card">
          <div><strong>Fix steps</strong></div>
          <div class="muted" style="margin-top:8px;">
            1) Server Settings &rarr; Roles: ensure the bot role has Manage Channels/Roles/Messages.<br/>
            2) Drag the bot role above Coach roles (role hierarchy).<br/>
            3) Channel settings: ensure the bot can View/Send/Embed/Read in Offside channels.
          </div>
          <div style="margin-top:10px;">
            <a class="btn blue" href="{invite_href}">Re-invite with permissions</a>
          </div>
        </div>
      </div>
      <div class="card">
        <h2 style="margin-top:0;">Guild-level permissions</h2>
        <table><thead><tr><th>permission</th><th>status</th><th>why</th></tr></thead><tbody>{guild_table}</tbody></table>
      </div>
      <div class="card">
        <h2 style="margin-top:0;">Role hierarchy</h2>
        <table><thead><tr><th>role</th><th>status</th><th>details</th></tr></thead><tbody>{hierarchy_table}</tbody></table>
      </div>
      <div class="card">
        <h2 style="margin-top:0;">Configured channels access</h2>
        <table><thead><tr><th>channel</th><th>status</th><th>details</th></tr></thead><tbody>{channel_table}</tbody></table>
        <p class="muted" style="margin-top:10px;">Only checks channels currently saved in guild settings.</p>
      </div>
    """
    return web.Response(
        text=_html_page(
            title="Permissions",
            body=_app_shell(
                settings=settings,
                session=session,
                section="permissions",
                selected_guild_id=guild_id,
                installed=installed,
                content=body,
            ),
        ),
        content_type="text/html",
    )


async def guild_audit_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    installed, _install_error = await _detect_bot_installed(request, guild_id=guild_id)
    plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    if plan != entitlements_service.PLAN_PRO:
        return _pro_locked_page(
            settings=settings,
            session=session,
            guild_id=guild_id,
            installed=installed,
            section="audit",
            title="Audit Log",
            message="The Audit Log is available on the Pro plan.",
        )
    limit = _parse_int(request.query.get("limit")) or 200
    limit = max(1, min(500, limit))

    try:
        col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
        events = list_audit_events(guild_id=guild_id, limit=limit, collection=col)
    except Exception as exc:
        raise web.HTTPInternalServerError(text=f"Failed to load audit events: {exc}") from exc

    rows: list[str] = []
    for ev in events:
        created = ev.get("created_at")
        created_text = created.isoformat() if isinstance(created, datetime) else str(created or "")
        category = str(ev.get("category") or "")
        action = str(ev.get("action") or "")
        source = str(ev.get("source") or "")

        actor = str(ev.get("actor_display_name") or "") or str(ev.get("actor_username") or "")
        actor_id = ev.get("actor_discord_id")
        if not actor and isinstance(actor_id, int):
            actor = str(actor_id)

        details_raw = ev.get("details")
        details_text = ""
        if details_raw is not None:
            try:
                details_text = json.dumps(details_raw, default=str, sort_keys=True)
            except Exception:
                details_text = str(details_raw)
        details_short = details_text
        if len(details_short) > 240:
            details_short = details_short[:237] + "..."

        rows.append(
            "<tr>"
            f"<td><code>{_escape_html(created_text)}</code></td>"
            f"<td><code>{_escape_html(category)}</code></td>"
            f"<td><code>{_escape_html(action)}</code></td>"
            f"<td>{_escape_html(actor) or '&mdash;'}</td>"
            f"<td><code>{_escape_html(source)}</code></td>"
            f"<td title=\"{_escape_html(details_text)}\"><code>{_escape_html(details_short)}</code></td>"
            "</tr>"
        )

    table_body = "\n".join(rows) if rows else "<tr><td colspan='6' class='muted'>No events yet.</td></tr>"

    body = f"""
      <p><a href="/guild/{guild_id}">&larr; Back</a></p>
      <h1>Audit Log</h1>
      <div class="row">
        <div class="card">
          <div><strong>Guild</strong></div>
          <div class="muted">ID: <code>{guild_id}</code></div>
          <div class="muted">Showing latest: <code>{limit}</code></div>
          <div style="margin-top:10px;"><a href="/guild/{guild_id}/audit.csv?limit={limit}">Download CSV</a></div>
        </div>
      </div>
      <div class="card">
        <table>
          <thead><tr><th>created_at</th><th>category</th><th>action</th><th>actor</th><th>source</th><th>details</th></tr></thead>
          <tbody>{table_body}</tbody>
        </table>
      </div>
    """
    return web.Response(
        text=_html_page(
            title="Audit Log",
            body=_app_shell(
                settings=settings,
                session=session,
                section="audit",
                selected_guild_id=guild_id,
                installed=installed,
                content=body,
            ),
        ),
        content_type="text/html",
    )


async def guild_audit_csv(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    if plan != entitlements_service.PLAN_PRO:
        raise web.HTTPForbidden(text="Audit Log export is available on the Pro plan.")

    limit = _parse_int(request.query.get("limit")) or 500
    limit = max(1, min(500, limit))

    try:
        col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
        events = list_audit_events(guild_id=guild_id, limit=limit, collection=col)
    except Exception as exc:
        raise web.HTTPInternalServerError(text=f"Failed to load audit events: {exc}") from exc

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "created_at",
            "category",
            "action",
            "source",
            "actor_discord_id",
            "actor_display_name",
            "actor_username",
            "details",
        ]
    )
    for ev in events:
        created = ev.get("created_at")
        created_text = created.isoformat() if isinstance(created, datetime) else str(created or "")
        details_raw = ev.get("details")
        details_text = ""
        if details_raw is not None:
            try:
                details_text = json.dumps(details_raw, default=str, sort_keys=True)
            except Exception:
                details_text = str(details_raw)
        writer.writerow(
            [
                created_text,
                str(ev.get("category") or ""),
                str(ev.get("action") or ""),
                str(ev.get("source") or ""),
                str(ev.get("actor_discord_id") or ""),
                str(ev.get("actor_display_name") or ""),
                str(ev.get("actor_username") or ""),
                details_text,
            ]
        )

    text = output.getvalue()
    headers = {"Content-Disposition": f"attachment; filename=audit_{guild_id}.csv"}
    return web.Response(text=text, headers=headers, content_type="text/csv")


async def guild_ops_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    installed, install_error = await _detect_bot_installed(request, guild_id=guild_id)
    if not settings.mongodb_uri:
        body = """
          <h1 style="margin-top:0;">Ops</h1>
          <div class="card"><p class="muted">MongoDB is not configured; ops tasks cannot be queued.</p></div>
        """
        return web.Response(
            text=_html_page(
                title="Ops",
                body=_app_shell(
                    settings=settings,
                    session=session,
                    section="ops",
                    selected_guild_id=guild_id,
                    installed=installed,
                    content=body,
                ),
            ),
            content_type="text/html",
        )

    heartbeat = get_worker_heartbeat(settings, worker="bot") or {}
    updated_at = heartbeat.get("updated_at")
    heartbeat_text = "missing"
    if isinstance(updated_at, datetime):
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - updated_at).total_seconds()
        heartbeat_text = f"{updated_at.isoformat()} (age={int(age)}s)"

    tasks: list[dict[str, Any]] = []
    tasks_error: str | None = None
    try:
        tasks = list_ops_tasks(settings, guild_id=guild_id, limit=25)
    except Exception as exc:
        tasks_error = str(exc)
        tasks = []

    task_rows: list[str] = []
    for task in tasks:
        created_at = task.get("created_at")
        created = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at or "")
        started_at = task.get("started_at")
        started = started_at.isoformat() if isinstance(started_at, datetime) else str(started_at or "")
        finished_at = task.get("finished_at")
        finished = finished_at.isoformat() if isinstance(finished_at, datetime) else str(finished_at or "")
        action = str(task.get("action") or "")
        status = str(task.get("status") or "")
        requested_by = str(task.get("requested_by_username") or task.get("requested_by_discord_id") or "")
        error = str(task.get("error") or "")
        task_rows.append(
            "<tr>"
            f"<td><code>{_escape_html(created)}</code></td>"
            f"<td><code>{_escape_html(action)}</code></td>"
            f"<td><code>{_escape_html(status)}</code></td>"
            f"<td>{_escape_html(requested_by)}</td>"
            f"<td><code>{_escape_html(started)}</code></td>"
            f"<td><code>{_escape_html(finished)}</code></td>"
            f"<td class='muted'>{_escape_html(error)[:200]}</td>"
            "</tr>"
        )
    tasks_table = (
        "\n".join(task_rows)
        if task_rows
        else "<tr><td colspan='7' class='muted'>No ops tasks yet.</td></tr>"
    )

    disabled_attr = "disabled" if installed is False else ""
    install_note = (
        f"<div class='card'><p class='muted'>{_escape_html(install_error or '')}</p></div>"
        if installed is False and install_error
        else ""
    )
    if tasks_error:
        install_note += f"<div class='card'><p class='muted'>Tasks unavailable: <code>{_escape_html(tasks_error)}</code></p></div>"

    body = f"""
      <h1 style="margin-top:0;">Ops</h1>
      {install_note}
      <div class="row">
        <div class="card">
          <div><strong>Worker heartbeat</strong></div>
          <div class="muted">{_escape_html(heartbeat_text)}</div>
          <p class="muted" style="margin-top:10px;">If the worker is missing/stale, queued tasks will not run.</p>
        </div>
        <div class="card">
          <div><strong>Actions</strong></div>
          <div class="muted" style="margin-top:8px;">These actions run on the bot worker dyno.</div>
          <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
            <form method="post" action="/api/guild/{guild_id}/ops/run_setup">
              <input type="hidden" name="csrf" value="{_escape_html(session.csrf_token)}" />
              <button class="btn" type="submit" {disabled_attr}>Run setup now</button>
            </form>
            <form method="post" action="/api/guild/{guild_id}/ops/repost_portals">
              <input type="hidden" name="csrf" value="{_escape_html(session.csrf_token)}" />
              <button class="btn secondary" type="submit" {disabled_attr}>Repost portals</button>
            </form>
          </div>
        </div>
      </div>
      <div class="card">
        <h2 style="margin-top:0;">Recent tasks</h2>
        <table>
          <thead><tr><th>created</th><th>action</th><th>status</th><th>requested by</th><th>started</th><th>finished</th><th>error</th></tr></thead>
          <tbody>{tasks_table}</tbody>
        </table>
        <p class="muted" style="margin-top:10px;">All actions are also recorded in the audit log.</p>
      </div>
    """
    return web.Response(
        text=_html_page(
            title="Ops",
            body=_app_shell(
                settings=settings,
                session=session,
                section="ops",
                selected_guild_id=guild_id,
                installed=installed,
                content=body,
            ),
        ),
        content_type="text/html",
    )


async def _enqueue_ops_from_dashboard(
    request: web.Request,
    *,
    action: str,
) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]
    if not settings.mongodb_uri:
        raise web.HTTPInternalServerError(text="MongoDB is not configured.")

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    installed, _install_error = await _detect_bot_installed(request, guild_id=guild_id)
    if installed is False:
        raise web.HTTPBadRequest(text="Bot is not installed in this server yet. Invite it first.")

    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    actor_id = _parse_int(session.user.get("id"))
    actor_username = f"{session.user.get('username','')}#{session.user.get('discriminator','')}".strip("#")

    task = enqueue_ops_task(
        settings,
        guild_id=guild_id,
        action=action,
        requested_by_discord_id=actor_id,
        requested_by_username=actor_username or None,
        source="dashboard",
    )

    try:
        audit_col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
        record_audit_event(
            guild_id=guild_id,
            category="ops",
            action="ops_task.enqueued",
            source="dashboard",
            actor_discord_id=actor_id,
            actor_display_name=str(session.user.get("username") or "") or None,
            actor_username=actor_username or None,
            details={
                "task_id": str(task.get("_id") or ""),
                "task_action": str(task.get("action") or ""),
                "task_status": str(task.get("status") or ""),
            },
            collection=audit_col,
        )
    except Exception:
        pass

    raise web.HTTPFound(f"/guild/{guild_id}/ops")


async def guild_ops_run_setup(request: web.Request) -> web.Response:
    return await _enqueue_ops_from_dashboard(request, action=OPS_TASK_ACTION_RUN_SETUP)


async def guild_ops_run_full_setup(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]
    if not settings.mongodb_uri:
        raise web.HTTPInternalServerError(text="MongoDB is not configured.")

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, guild_id=guild_id_str)

    installed, _install_error = await _detect_bot_installed(request, guild_id=guild_id)
    if installed is False:
        raise web.HTTPBadRequest(text="Bot is not installed in this server yet. Invite it first.")

    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    actor_id = _parse_int(session.user.get("id"))
    actor_username = f"{session.user.get('username','')}#{session.user.get('discriminator','')}".strip("#")

    actions = [OPS_TASK_ACTION_RUN_SETUP, OPS_TASK_ACTION_REPOST_PORTALS]
    for action in actions:
        task = enqueue_ops_task(
            settings,
            guild_id=guild_id,
            action=action,
            requested_by_discord_id=actor_id,
            requested_by_username=actor_username or None,
            source="dashboard",
        )
        try:
            audit_col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
            record_audit_event(
                guild_id=guild_id,
                category="ops",
                action="ops_task.enqueued",
                source="dashboard",
                actor_discord_id=actor_id,
                actor_display_name=str(session.user.get("username") or "") or None,
                actor_username=actor_username or None,
                details={
                    "task_id": str(task.get("_id") or ""),
                    "task_action": str(task.get("action") or ""),
                    "task_status": str(task.get("status") or ""),
                    "wizard": True,
                },
                collection=audit_col,
            )
        except Exception:
            pass

    raise web.HTTPFound(f"/guild/{guild_id}/setup?queued=1")


async def guild_ops_repost_portals(request: web.Request) -> web.Response:
    return await _enqueue_ops_from_dashboard(request, action=OPS_TASK_ACTION_REPOST_PORTALS)


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


async def billing_webhook(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    if not settings.mongodb_uri:
        raise web.HTTPInternalServerError(text="MongoDB is not configured.")

    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise web.HTTPInternalServerError(text="STRIPE_WEBHOOK_SECRET is not configured.")

    sig_header = request.headers.get("Stripe-Signature", "").strip()
    if not sig_header:
        raise web.HTTPBadRequest(text="Missing Stripe-Signature header.")

    payload = await request.read()
    try:
        result = handle_stripe_webhook(
            settings,
            payload=payload,
            sig_header=sig_header,
            secret=secret,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    except Exception as exc:
        logging.exception("Stripe webhook processing failed (event unknown).")
        raise web.HTTPInternalServerError(text="Webhook processing failed.") from exc

    return web.json_response(
        {
            "ok": True,
            "status": result.status,
            "event_id": result.event_id,
            "event_type": result.event_type,
            "handled": result.handled,
            "guild_id": result.guild_id,
        }
    )


async def billing_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]

    selected_guild_id = request.query.get("guild_id", "").strip()
    if selected_guild_id:
        guild_id = _require_owned_guild(session, guild_id=selected_guild_id)
    elif session.owner_guilds:
        guild_id = _require_owned_guild(session, guild_id=str(session.owner_guilds[0].get("id") or ""))
    else:
        guild_id = 0

    if not guild_id:
        body = """
          <p><a href="/">&larr; Back</a></p>
          <h1>Billing</h1>
          <p class="muted">No owned guilds found.</p>
        """
        return web.Response(
            text=_html_page(
                title="Billing",
                body=_app_shell(
                    settings=settings,
                    session=session,
                    section="billing",
                    selected_guild_id=None,
                    installed=None,
                    content=body,
                ),
            ),
            content_type="text/html",
        )

    installed, _install_error = await _detect_bot_installed(request, guild_id=guild_id)
    current_plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    subscription = get_guild_subscription(settings, guild_id=guild_id) if settings.mongodb_uri else None
    customer_id = str(subscription.get("customer_id") or "") if subscription else ""
    options = "\n".join(
        f"<option value=\"{_escape_html(g.get('id'))}\""
        f"{' selected' if str(g.get('id')) == str(guild_id) else ''}>"
        f"{_escape_html(g.get('name') or g.get('id'))}</option>"
        for g in session.owner_guilds
    )

    status = request.query.get("status", "").strip()
    status_msg = ""
    if status == "cancelled":
        status_msg = "<div class='card'><strong>Checkout cancelled.</strong></div>"
    elif status == "success":
        if current_plan == entitlements_service.PLAN_PRO:
            status_msg = "<div class='card'><strong>Checkout complete.</strong> Pro is enabled.</div>"
        else:
            status_msg = (
                "<div class='card'><strong>Checkout complete.</strong> Activation may take a few seconds.</div>"
            )

    upgrade_disabled = "disabled" if current_plan == entitlements_service.PLAN_PRO else ""
    upgrade_text = "Already Pro" if current_plan == entitlements_service.PLAN_PRO else "Upgrade to Pro"

    manage_card = ""
    if customer_id:
        manage_card = f"""
          <div class="card">
            <h2 style="margin-top:0;">Manage subscription</h2>
            <p class="muted">Update payment method, view invoices, or cancel your subscription.</p>
            <form method="post" action="/app/billing/portal">
              <input type="hidden" name="csrf" value="{_escape_html(session.csrf_token)}" />
              <input type="hidden" name="guild_id" value="{guild_id}" />
              <button class="btn secondary" type="submit">Open Stripe Billing Portal</button>
            </form>
          </div>
        """

    body = f"""
      <p><a href="/">&larr; Back</a></p>
      <h1>Billing</h1>
      {status_msg}
      <div class="card">
        <div><strong>Current plan</strong></div>
        <div style="margin-top:6px;"><span class="badge {current_plan}">{_escape_html(current_plan.upper())}</span></div>
      </div>
      {manage_card}
      <div class="card">
        <h2 style="margin-top:0;">Upgrade this server</h2>
        <form method="post" action="/app/billing/checkout">
          <input type="hidden" name="csrf" value="{_escape_html(session.csrf_token)}" />
          <label><strong>Guild</strong></label>
          <select name="guild_id" style="width:100%; padding:10px; margin-top:6px;">{options}</select>
          <label style="display:block; margin-top:12px;"><strong>Plan</strong></label>
          <select name="plan" style="width:100%; padding:10px; margin-top:6px;">
            <option value="pro">Pro</option>
          </select>
          <div style="margin-top:12px;">
            <button class="btn blue" type="submit" {upgrade_disabled}>{_escape_html(upgrade_text)}</button>
          </div>
        </form>
      </div>
    """
    return web.Response(
        text=_html_page(
            title="Billing",
            body=_app_shell(
                settings=settings,
                session=session,
                section="billing",
                selected_guild_id=guild_id,
                installed=installed,
                content=body,
            ),
        ),
        content_type="text/html",
    )


async def billing_portal(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]
    if not settings.mongodb_uri:
        raise web.HTTPInternalServerError(text="MongoDB is not configured.")

    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    guild_id = _require_owned_guild(session, guild_id=str(data.get("guild_id") or ""))

    subscription = get_guild_subscription(settings, guild_id=guild_id) or {}
    customer_id = str(subscription.get("customer_id") or "").strip()
    if not customer_id:
        raise web.HTTPBadRequest(
            text="No Stripe customer found for this server yet. Complete checkout first."
        )

    secret_key = _require_env("STRIPE_SECRET_KEY")
    return_url = f"{_public_base_url(request)}/app/billing?guild_id={guild_id}"

    try:
        import stripe  # type: ignore[import-not-found]
    except Exception as exc:
        raise web.HTTPInternalServerError(text="Stripe SDK is not installed.") from exc

    stripe.api_key = secret_key
    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    url = getattr(portal, "url", None) or (portal.get("url") if isinstance(portal, dict) else None)
    if not url:
        raise web.HTTPInternalServerError(text="Stripe did not return a billing portal URL.")
    raise web.HTTPFound(str(url))


async def billing_checkout(request: web.Request) -> web.Response:
    session = _require_session(request)
    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    guild_id = _require_owned_guild(session, guild_id=str(data.get("guild_id") or ""))
    plan = str(data.get("plan") or "pro").strip().lower()
    if plan != entitlements_service.PLAN_PRO:
        raise web.HTTPBadRequest(text="Unsupported plan.")

    secret_key = _require_env("STRIPE_SECRET_KEY")
    price_id = _require_env("STRIPE_PRICE_PRO_ID")

    base_url = _public_base_url(request)
    success_url = f"{base_url}/app/billing/success?guild_id={guild_id}&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base_url}/app/billing/cancel?guild_id={guild_id}"

    try:
        import stripe  # type: ignore[import-not-found]
    except Exception as exc:
        raise web.HTTPInternalServerError(text="Stripe SDK is not installed.") from exc

    stripe.api_key = secret_key
    checkout = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"guild_id": str(guild_id), "plan": plan},
        subscription_data={"metadata": {"guild_id": str(guild_id), "plan": plan}},
        client_reference_id=str(guild_id),
    )
    url = getattr(checkout, "url", None) or (checkout.get("url") if isinstance(checkout, dict) else None)
    if not url:
        raise web.HTTPInternalServerError(text="Stripe did not return a checkout URL.")
    raise web.HTTPFound(str(url))


async def billing_success(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app["settings"]
    gid = request.query.get("guild_id", "").strip()
    checkout_session_id = request.query.get("session_id", "").strip()
    guild_id = _require_owned_guild(session, guild_id=gid) if gid else 0
    if not guild_id:
        raise web.HTTPBadRequest(text="Missing guild_id.")

    synced = False
    sync_error: str | None = None
    if settings.mongodb_uri and checkout_session_id:
        try:
            import stripe  # type: ignore[import-not-found]
        except Exception:
            sync_error = "Stripe SDK is not installed."
        else:
            try:
                stripe.api_key = _require_env("STRIPE_SECRET_KEY")
                checkout = stripe.checkout.Session.retrieve(
                    checkout_session_id,
                    expand=["subscription"],
                )
                meta = getattr(checkout, "metadata", None)
                if not isinstance(meta, dict) and isinstance(checkout, dict):
                    meta = checkout.get("metadata")
                meta = meta if isinstance(meta, dict) else {}

                meta_gid = str(meta.get("guild_id") or "").strip()
                if meta_gid and meta_gid.isdigit() and int(meta_gid) != guild_id:
                    raise RuntimeError("Checkout session does not match selected guild.")

                plan_raw = str(meta.get("plan") or entitlements_service.PLAN_PRO).strip().lower()
                plan = entitlements_service.PLAN_PRO if plan_raw != entitlements_service.PLAN_PRO else plan_raw

                customer_id = getattr(checkout, "customer", None)
                if customer_id is None and isinstance(checkout, dict):
                    customer_id = checkout.get("customer")

                sub_obj = getattr(checkout, "subscription", None)
                if sub_obj is None and isinstance(checkout, dict):
                    sub_obj = checkout.get("subscription")

                subscription_id: str | None = None
                sub_status = "unknown"
                period_end: datetime | None = None

                if isinstance(sub_obj, str):
                    subscription_id = sub_obj.strip() or None
                elif isinstance(sub_obj, dict):
                    subscription_id = str(sub_obj.get("id") or "").strip() or None
                    sub_status = str(sub_obj.get("status") or "").strip().lower() or sub_status
                    period_end_raw = sub_obj.get("current_period_end")
                    if isinstance(period_end_raw, (int, float)):
                        period_end = datetime.fromtimestamp(float(period_end_raw), tz=timezone.utc)
                elif sub_obj is not None:
                    subscription_id = str(getattr(sub_obj, "id", "") or "").strip() or None
                    sub_status = str(getattr(sub_obj, "status", "") or "").strip().lower() or sub_status
                    period_end_raw = getattr(sub_obj, "current_period_end", None)
                    if isinstance(period_end_raw, (int, float)):
                        period_end = datetime.fromtimestamp(float(period_end_raw), tz=timezone.utc)

                if subscription_id and (sub_status == "unknown" or period_end is None):
                    sub = stripe.Subscription.retrieve(subscription_id)
                    if isinstance(sub, dict):
                        sub_status = str(sub.get("status") or "").strip().lower() or sub_status
                        period_end_raw = sub.get("current_period_end")
                    else:
                        sub_status = str(getattr(sub, "status", "") or "").strip().lower() or sub_status
                        period_end_raw = getattr(sub, "current_period_end", None)
                    if isinstance(period_end_raw, (int, float)):
                        period_end = datetime.fromtimestamp(float(period_end_raw), tz=timezone.utc)

                if sub_status == "unknown":
                    sub_status = "active"

                from services.subscription_service import upsert_guild_subscription

                upsert_guild_subscription(
                    settings,
                    guild_id=guild_id,
                    plan=plan,
                    status=sub_status,
                    period_end=period_end,
                    customer_id=str(customer_id) if customer_id else None,
                    subscription_id=subscription_id,
                )
                entitlements_service.invalidate_guild_plan(guild_id)
                synced = True
            except Exception as exc:
                sync_error = str(exc)

    plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    message = (
        "Pro enabled for this server."
        if plan == entitlements_service.PLAN_PRO
        else "Checkout complete. Activation may take a few seconds. Refresh in a moment."
    )
    if synced and plan != entitlements_service.PLAN_PRO:
        message = "Checkout confirmed. Waiting for activation. Refresh in a moment."
    if sync_error and plan != entitlements_service.PLAN_PRO:
        message = f"Checkout complete. Activation pending ({sync_error})."
    body = f"""
      <p><a href="/app/billing?guild_id={guild_id}&status=success">&larr; Billing</a></p>
      <h1>Checkout Success</h1>
      <div class="card">
        <div><strong>{_escape_html(message)}</strong></div>
        <div style="margin-top:8px;">Plan: <span class="badge {plan}">{_escape_html(plan.upper())}</span></div>
        <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
          <a class="btn secondary" href="/app/billing?guild_id={guild_id}">View billing</a>
          <a class="btn" href="/guild/{guild_id}">Analytics</a>
          <a class="btn secondary" href="/guild/{guild_id}/settings">Settings</a>
        </div>
      </div>
    """
    return web.Response(text=_html_page(title="Checkout Success", body=body), content_type="text/html")


async def billing_cancel(request: web.Request) -> web.Response:
    session = _require_session(request)
    gid = request.query.get("guild_id", "").strip()
    guild_id = _require_owned_guild(session, guild_id=gid) if gid else 0
    if not guild_id:
        raise web.HTTPBadRequest(text="Missing guild_id.")
    raise web.HTTPFound(f"/app/billing?guild_id={guild_id}&status=cancelled")


async def _on_startup(app: web.Application) -> None:
    # aiohttp ClientSession must be created with a running event loop.
    app["http"] = ClientSession()


async def _on_cleanup(app: web.Application) -> None:
    http = app.get("http")
    if isinstance(http, ClientSession):
        await http.close()


def create_app(*, settings: Settings | None = None) -> web.Application:
    app = web.Application(
        client_max_size=max(1, int(MAX_REQUEST_BYTES)),
        middlewares=[
            security_headers_middleware,
            rate_limit_middleware,
            timeout_middleware,
            session_middleware,
        ]
    )
    app_settings = settings or load_settings()
    app["settings"] = app_settings
    init_error_reporting(settings=app_settings, service_name="dashboard")
    session_collection, state_collection = _ensure_dashboard_collections(app_settings)
    app["session_collection"] = session_collection
    app["state_collection"] = state_collection
    if app_settings.mongodb_uri:
        ensure_stripe_webhook_indexes(app_settings)
        ensure_ops_task_indexes(app_settings)
    app["guild_metadata_cache"] = {}
    app["http"] = None
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    try:
        from offside_bot.web_templates import static_dir

        static_path = static_dir()
        if static_path.is_dir():
            app.router.add_static("/static/", path=str(static_path), name="static")
    except Exception:
        pass

    app.router.add_get("/health", health)
    app.router.add_get("/ready", ready)
    app.router.add_get("/", index)
    app.router.add_get("/terms", terms_page)
    app.router.add_get("/privacy", privacy_page)
    app.router.add_get("/support", support_page)
    app.router.add_get("/login", login)
    app.router.add_get("/install", install)
    app.router.add_get("/oauth/callback", oauth_callback)
    app.router.add_get("/logout", logout)
    app.router.add_get("/app/upgrade", upgrade_redirect)
    app.router.add_get("/app/billing", billing_page)
    app.router.add_post("/app/billing/portal", billing_portal)
    app.router.add_post("/app/billing/checkout", billing_checkout)
    app.router.add_get("/app/billing/success", billing_success)
    app.router.add_get("/app/billing/cancel", billing_cancel)
    app.router.add_get("/guild/{guild_id}", guild_page)
    app.router.add_get("/guild/{guild_id}/overview", guild_overview_page)
    app.router.add_get("/guild/{guild_id}/setup", guild_setup_wizard_page)
    app.router.add_get("/guild/{guild_id}/permissions", guild_permissions_page)
    app.router.add_get("/guild/{guild_id}/audit", guild_audit_page)
    app.router.add_get("/guild/{guild_id}/audit.csv", guild_audit_csv)
    app.router.add_get("/guild/{guild_id}/ops", guild_ops_page)
    app.router.add_get("/guild/{guild_id}/settings", guild_settings_page)
    app.router.add_post("/guild/{guild_id}/settings", guild_settings_save)
    app.router.add_get("/api/guild/{guild_id}/analytics.json", guild_analytics_json)
    app.router.add_get("/api/guild/{guild_id}/discord_metadata.json", guild_discord_metadata_json)
    app.router.add_post("/api/guild/{guild_id}/ops/run_setup", guild_ops_run_setup)
    app.router.add_post("/api/guild/{guild_id}/ops/run_full_setup", guild_ops_run_full_setup)
    app.router.add_post("/api/guild/{guild_id}/ops/repost_portals", guild_ops_repost_portals)
    app.router.add_post("/api/billing/webhook", billing_webhook)
    return app


def main() -> None:
    settings = load_settings()
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port_raw = (os.environ.get("PORT") or os.environ.get("DASHBOARD_PORT") or "8080").strip() or "8080"
    port = int(port_raw)
    app = create_app(settings=settings)
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()
