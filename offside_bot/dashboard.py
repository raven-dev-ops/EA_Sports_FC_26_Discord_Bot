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
from typing import Any, Final

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
from services.guild_install_service import ensure_guild_install_indexes, list_guild_installs
from services.guild_settings_schema import (
    FC25_STATS_ENABLED_KEY,
    GUILD_CHANNEL_FIELDS,
    GUILD_COACH_ROLE_FIELDS,
    PREMIUM_COACHES_PIN_ENABLED_KEY,
)
from services.heartbeat_service import get_worker_heartbeat
from services.ops_tasks_service import (
    OPS_TASK_ACTION_DELETE_GUILD_DATA,
    OPS_TASK_ACTION_REPOST_PORTALS,
    OPS_TASK_ACTION_RUN_SETUP,
    OPS_TASKS_COLLECTION,
    cancel_ops_task,
    enqueue_ops_task,
    ensure_ops_task_indexes,
    get_active_ops_task,
    list_ops_tasks,
)
from services.stripe_webhook_service import (
    STRIPE_DEAD_LETTERS_COLLECTION,
    STRIPE_EVENTS_COLLECTION,
    ensure_stripe_webhook_indexes,
    handle_stripe_webhook,
)
from services.subscription_service import (
    get_guild_subscription,
    get_guild_subscription_by_subscription_id,
    get_subscription_collection,
    upsert_guild_subscription,
)
from utils.environment import validate_stripe_environment
from utils.i18n import t
from utils.redaction import redact_ip, redact_text

DISCORD_API_BASE = "https://discord.com/api"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"
ME_URL = f"{DISCORD_API_BASE}/users/@me"
MY_GUILDS_URL = f"{DISCORD_API_BASE}/users/@me/guilds"

COOKIE_NAME = "offside_dashboard_session"
NEXT_COOKIE_NAME = "offside_dashboard_next"
REQUEST_ID_HEADER = "X-Request-Id"
SESSION_TTL_SECONDS = int(os.environ.get("DASHBOARD_SESSION_TTL_SECONDS", "21600").strip() or "21600")
SESSION_IDLE_TIMEOUT_SECONDS = int(
    os.environ.get("DASHBOARD_SESSION_IDLE_TIMEOUT_SECONDS", "1800").strip() or "1800"
)
SESSION_TOUCH_INTERVAL_SECONDS = int(
    os.environ.get("DASHBOARD_SESSION_TOUCH_INTERVAL_SECONDS", "300").strip() or "300"
)
STATE_TTL_SECONDS = 600
GUILD_METADATA_TTL_SECONDS = int(os.environ.get("DASHBOARD_GUILD_METADATA_TTL_SECONDS", "60").strip() or "60")

REQUEST_TIMEOUT_SECONDS = float(os.environ.get("DASHBOARD_REQUEST_TIMEOUT_SECONDS", "15").strip() or "15")
MAX_REQUEST_BYTES = int(os.environ.get("DASHBOARD_MAX_REQUEST_BYTES", "1048576").strip() or "1048576")
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("DASHBOARD_RATE_LIMIT_WINDOW_SECONDS", "60").strip() or "60")
RATE_LIMIT_PUBLIC_MAX = int(os.environ.get("DASHBOARD_RATE_LIMIT_PUBLIC_MAX", "20").strip() or "20")
RATE_LIMIT_WEBHOOK_MAX = int(os.environ.get("DASHBOARD_RATE_LIMIT_WEBHOOK_MAX", "120").strip() or "120")
RATE_LIMIT_DEFAULT_MAX = int(os.environ.get("DASHBOARD_RATE_LIMIT_DEFAULT_MAX", "300").strip() or "300")
GUILD_DATA_DELETE_GRACE_HOURS = int(
    os.environ.get("GUILD_DATA_DELETE_GRACE_HOURS", "24").strip() or "24"
)

# Minimal permissions needed for auto-setup and dashboard posting:
# - Manage Channels, Manage Roles, View Channel, Send Messages, Embed Links, Read Message History
DEFAULT_BOT_PERMISSIONS = 268520464

DEFAULT_PUBLIC_REPO_URL = "https://github.com/raven-dev-ops/EA_Sports_FC_26_Discord_Bot"

DOCS_PAGES: list[dict[str, str]] = [
    {
        "slug": "server-setup-checklist",
        "title": "Server setup checklist",
        "path": "docs/server-setup-checklist.md",
        "summary": "Step-by-step setup for new servers.",
    },
    {
        "slug": "billing",
        "title": "Billing",
        "path": "docs/billing.md",
        "summary": "Stripe setup, pricing, and subscription details.",
    },
    {
        "slug": "data-lifecycle",
        "title": "Data lifecycle",
        "path": "docs/data-lifecycle.md",
        "summary": "Retention, deletion, and data export guidance.",
    },
    {
        "slug": "environments",
        "title": "Environments",
        "path": "docs/environments.md",
        "summary": "Dev/staging/prod separation for Discord + Stripe.",
    },
    {
        "slug": "disaster-recovery",
        "title": "Disaster recovery",
        "path": "docs/disaster-recovery.md",
        "summary": "Backup/restore, Stripe replay, and credential rotation checklist.",
    },
    {
        "slug": "monitoring",
        "title": "Monitoring",
        "path": "docs/monitoring.md",
        "summary": "Health checks, uptime checks, and operational signals.",
    },
    {
        "slug": "admin-console",
        "title": "Admin console",
        "path": "docs/admin-console.md",
        "summary": "Internal allowlisted tools for subscriptions and webhooks.",
    },
    {
        "slug": "qa-checklist",
        "title": "QA checklist",
        "path": "docs/qa-checklist.md",
        "summary": "Staging validation flow before release.",
    },
    {
        "slug": "release-playbook",
        "title": "Release playbook",
        "path": "docs/release-playbook.md",
        "summary": "Deployment steps, migrations, and rollback notes.",
    },
    {
        "slug": "performance",
        "title": "Performance",
        "path": "docs/performance.md",
        "summary": "Performance targets and tuning notes.",
    },
    {
        "slug": "ci",
        "title": "CI",
        "path": "docs/ci.md",
        "summary": "CI setup, runners, and release workflows.",
    },
    {
        "slug": "localization",
        "title": "Localization",
        "path": "docs/localization.md",
        "summary": "i18n scaffold and locale workflow.",
    },
    {
        "slug": "fc25-stats-policy",
        "title": "FC stats policy",
        "path": "docs/fc25-stats-policy.md",
        "summary": "Stats data handling policy and expectations.",
    },
]
DOCS_BY_SLUG = {page["slug"]: page for page in DOCS_PAGES}
DOCS_EXTRAS = [
    {
        "title": "Commands reference",
        "summary": "Slash command list grouped by category.",
        "href": "/commands",
    }
]

DASHBOARD_SESSIONS_COLLECTION = "dashboard_sessions"
DASHBOARD_OAUTH_STATES_COLLECTION = "dashboard_oauth_states"
DASHBOARD_USERS_COLLECTION = "dashboard_users"
SETTINGS_KEY: Final = web.AppKey("settings", Settings)
SESSION_COLLECTION_KEY: Final = web.AppKey("session_collection", Collection)
STATE_COLLECTION_KEY: Final = web.AppKey("state_collection", Collection)
USER_COLLECTION_KEY: Final = web.AppKey("user_collection", Collection)
GUILD_METADATA_CACHE_KEY: Final = web.AppKey("guild_metadata_cache", dict[int, dict[str, Any]])
HTTP_SESSION_KEY: Final = web.AppKey("http", ClientSession | None)


@dataclass
class SessionData:
    created_at: float
    user: dict[str, Any]
    owner_guilds: list[dict[str, Any]]
    all_guilds: list[dict[str, Any]]
    csrf_token: str
    last_seen_at: float
    guilds_fetched_at: float
    last_guild_id: int | None = None


_RATE_LIMIT_STATE: dict[tuple[str, str], tuple[int, float]] = {}
_RATE_LIMIT_LAST_SWEEP: float = 0.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_dashboard_collections(settings: Settings) -> tuple[Collection, Collection, Collection]:
    sessions = get_global_collection(settings, name=DASHBOARD_SESSIONS_COLLECTION)
    states = get_global_collection(settings, name=DASHBOARD_OAUTH_STATES_COLLECTION)
    users = get_global_collection(settings, name=DASHBOARD_USERS_COLLECTION)
    sessions.create_index("expires_at", expireAfterSeconds=0, name="ttl_expires_at")
    states.create_index("expires_at", expireAfterSeconds=0, name="ttl_expires_at")
    users.create_index("discord_user_id", unique=True, name="uniq_discord_user_id")
    users.create_index("updated_at", name="idx_updated_at")
    return sessions, states, users


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


def _insert_oauth_state(*, states: Collection, next_path: str, expires_at: datetime) -> str:
    for _ in range(5):
        state = secrets.token_urlsafe(24)
        doc = {
            "_id": state,
            "issued_at": time.time(),
            "next": next_path,
            "expires_at": expires_at,
        }
        try:
            states.insert_one(doc)
            return state
        except DuplicateKeyError:
            continue
    raise RuntimeError("Failed to insert a unique OAuth state after multiple attempts.")


def _html_page(*, title: str, body: str) -> str:
    from offside_bot.web_templates import render, safe_html

    return render("base.html", title=title, body=safe_html(body))


def _upsert_user_record(settings: Settings, user: dict[str, Any]) -> None:
    """
    Persist the Discord user profile so we have a server-side audit trail of logins.
    """
    try:
        discord_user_id = str(user.get("id") or "").strip()
        if not discord_user_id:
            return
        now = datetime.now(timezone.utc)
        users = get_global_collection(settings, name=DASHBOARD_USERS_COLLECTION)
        users.update_one(
            {"discord_user_id": discord_user_id},
            {
                "$set": {
                    "discord_user_id": discord_user_id,
                    "username": user.get("username"),
                    "discriminator": user.get("discriminator"),
                    "global_name": user.get("global_name"),
                    "avatar": user.get("avatar"),
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    except Exception:
        logging.exception("event=upsert_user_record_failed")


def _guild_icon_url(guild: dict[str, Any]) -> str | None:
    gid = str(guild.get("id") or "").strip()
    icon = str(guild.get("icon") or "").strip()
    if gid and icon:
        return f"https://cdn.discordapp.com/icons/{gid}/{icon}.png?size=64"
    return None


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
    nav_items_override: list[dict[str, Any]] | None = None,
    nav_groups_override: list[dict[str, Any]] | None = None,
    breadcrumbs_override: list[dict[str, str]] | None = None,
    guild_selector_override: list[dict[str, str]] | None = None,
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
    if guild_selector_override is not None:
        guild_selector = guild_selector_override

    guild_plan: str | None = None
    plan_badge: dict[str, str] | None = None
    plan_notice: dict[str, Any] | None = None
    if selected_guild_id is not None:
        guild_plan = entitlements_service.get_guild_plan(settings, guild_id=selected_guild_id)
        plan_badge = {"label": str(guild_plan).upper(), "kind": str(guild_plan)}
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
                plan_notice = {
                    "status_label": title.upper(),
                    "status_kind": "warn",
                    "title": f"{title}{suffix}",
                    "detail": detail,
                    "ctas": [
                        {
                            "label": "Billing",
                            "href": f"/app/billing?guild_id={selected_guild_id}",
                            "variant": "secondary",
                        },
                        {
                            "label": "Upgrade",
                            "href": f"/app/upgrade?guild_id={selected_guild_id}&from=notice&section={urllib.parse.quote(section)}",
                            "variant": "blue",
                        },
                    ],
                }

    install_badge: dict[str, str] | None = None
    invite_cta: dict[str, str] | None = None
    if selected_guild_id is not None:
        invite_href = _invite_url(settings, guild_id=str(selected_guild_id), disable_guild_select=True)
        if installed is False:
            install_badge = {"label": "NOT INSTALLED", "kind": "warn"}
            invite_cta = {"label": "Invite bot", "href": invite_href, "variant": "blue"}
        elif installed is None:
            install_badge = {"label": "UNKNOWN", "kind": "warn"}
            invite_cta = {"label": "Invite bot", "href": invite_href, "variant": "blue"}

    nav_guild = str(selected_guild_id or "")
    is_pro = guild_plan == entitlements_service.PLAN_PRO
    is_owner = bool(selected_guild_id and _guild_is_owner(session, selected_guild_id))
    nav_items: list[dict[str, Any]] = []
    nav_groups: list[dict[str, Any]] = []
    breadcrumbs: list[dict[str, str]] = [{"label": "Dashboard", "href": "/app"}]
    if nav_guild:
        selected_guild_label = next(
            (
                str(g.get("name") or g.get("id") or "")
                for g in session.owner_guilds
                if str(g.get("id")) == nav_guild
            ),
            nav_guild,
        )
        if selected_guild_label:
            breadcrumbs.append(
                {"label": selected_guild_label, "href": _guild_section_url(nav_guild, section="overview")}
            )

        section_labels = {
            "overview": "Overview",
            "setup": "Setup Wizard",
            "analytics": "Analytics",
            "settings": "Settings",
            "permissions": "Permissions",
            "audit": "Audit Log",
            "ops": "Ops",
            "billing": "Billing",
        }
        section_label = section_labels.get(section)
        if section_label:
            breadcrumbs.append({"label": section_label, "href": _guild_section_url(nav_guild, section=section)})

        nav_groups = [
            {
                "label": "Setup",
                "items": [
                    {"label": "Overview", "href": _guild_section_url(nav_guild, section="overview"), "active": section == "overview"},
                    {"label": "Setup Wizard", "href": _guild_section_url(nav_guild, section="setup"), "active": section == "setup"},
                    {"label": "Settings", "href": _guild_section_url(nav_guild, section="settings"), "active": section == "settings"},
                    {"label": "Permissions", "href": _guild_section_url(nav_guild, section="permissions"), "active": section == "permissions"},
                ],
            },
            {
                "label": "Operations",
                "items": [
                    {"label": "Analytics", "href": _guild_section_url(nav_guild, section="analytics"), "active": section == "analytics"},
                    {
                        "label": "Audit Log",
                        "href": _guild_section_url(nav_guild, section="audit"),
                        "active": section == "audit",
                        "locked": not is_pro,
                        "lock_reason": "Pro plan required for audit log.",
                    },
                    {
                        "label": "Ops",
                        "href": _guild_section_url(nav_guild, section="ops"),
                        "active": section == "ops",
                        "locked": not is_pro,
                        "lock_reason": "Pro plan required for ops tasks.",
                    },
                ],
            },
            {
                "label": "Billing",
                "items": [
                    {
                        "label": "Billing",
                        "href": _guild_section_url(nav_guild, section="billing"),
                        "active": section == "billing",
                        "locked": not is_owner,
                        "lock_reason": "Billing is available to guild owners.",
                    },
                ],
            },
            {
                "label": "Resources",
                "items": [
                    {"label": "Docs hub", "href": "/docs", "active": False},
                    {"label": "Setup checklist", "href": "/docs/server-setup-checklist", "active": False},
                    {"label": "Billing guide", "href": "/docs/billing", "active": False},
                    {"label": "Data lifecycle", "href": "/docs/data-lifecycle", "active": False},
                ],
            },
        ]

    if nav_items_override is not None:
        nav_items = nav_items_override
        nav_groups = nav_groups_override or []
    elif nav_groups_override is not None:
        nav_groups = nav_groups_override
    if breadcrumbs_override is not None:
        breadcrumbs = breadcrumbs_override

    return render(
        "partials/app_shell.html",
        username=username,
        guild_selector=guild_selector,
        plan_badge=plan_badge,
        install_badge=install_badge,
        invite_cta=invite_cta,
        nav_items=nav_items,
        nav_groups=nav_groups,
        breadcrumbs=breadcrumbs,
        plan_notice=plan_notice,
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
    benefits: list[tuple[str, str]] | None = None,
    upgrade_href: str | None = None,
) -> web.Response:
    from offside_bot.web_templates import render

    upgrade_href = upgrade_href or f"/app/upgrade?guild_id={guild_id}&from=locked&section={urllib.parse.quote(section)}"
    if benefits is None:
        benefits = [
            ("Premium coach tiers", "Coach Premium and Coach Premium+ roles, caps, and workflow."),
            ("Premium Coaches report", "Public listing embed of Premium coaches and openings."),
            ("FC stats integration", "FC25/FC26 stats lookup, caching, and richer player profiles."),
            ("Banlist integration", "Google Sheets-driven banlist checks and moderation tooling."),
            ("Tournament automation", "Automated brackets, fixtures, and match reporting workflows."),
        ]
    benefit_items = [{"name": name, "desc": desc} for name, desc in benefits]
    content = render(
        "pages/dashboard/locked_pro.html",
        title=title,
        message=message,
        benefits=benefit_items,
        upgrade_href=upgrade_href,
        guild_id=guild_id,
    )
    return web.Response(
        text=_html_page(
            title=title,
            body=_app_shell(
                settings=settings,
                session=session,
                section=section,
                selected_guild_id=guild_id,
                installed=installed,
                content=content,
            ),
        ),
        content_type="text/html",
    )


def _owner_locked_page(
    *,
    settings: Settings,
    session: SessionData,
    guild_id: int,
    installed: bool | None,
    section: str,
    title: str,
    message: str,
) -> web.Response:
    from offside_bot.web_templates import render

    content = render(
        "pages/dashboard/locked_owner.html",
        title=title,
        message=message,
        guild_id=guild_id,
    )
    return web.Response(
        text=_html_page(
            title=title,
            body=_app_shell(
                settings=settings,
                session=session,
                section=section,
                selected_guild_id=guild_id,
                installed=installed,
                content=content,
            ),
        ),
        content_type="text/html",
    )


def _require_pro_plan_for_ops(settings: Settings, guild_id: int) -> None:
    plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    if plan != entitlements_service.PLAN_PRO:
        raise web.HTTPForbidden(text="Ops tasks are available on the Pro plan.")


async def upgrade_redirect(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]

    gid = request.query.get("guild_id", "").strip()
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=gid) if gid else 0
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
    cache: dict[int, dict[str, Any]] = request.app[GUILD_METADATA_CACHE_KEY]
    now = time.time()
    cached = cache.get(guild_id)
    if isinstance(cached, dict):
        fetched_at = cached.get("fetched_at")
        if isinstance(fetched_at, (int, float)) and now - float(fetched_at) <= GUILD_METADATA_TTL_SECONDS:
            roles = cached.get("roles")
            channels = cached.get("channels")
            if isinstance(roles, list) and isinstance(channels, list):
                return [r for r in roles if isinstance(r, dict)], [c for c in channels if isinstance(c, dict)]

    settings: Settings = request.app[SETTINGS_KEY]
    http = request.app.get(HTTP_SESSION_KEY)
    if not isinstance(http, ClientSession):
        raise web.HTTPInternalServerError(text="Dashboard HTTP client is not ready yet.")

    roles = await _fetch_guild_roles(http, bot_token=settings.discord_token, guild_id=guild_id)
    channels = await _fetch_guild_channels(http, bot_token=settings.discord_token, guild_id=guild_id)
    cache[guild_id] = {"fetched_at": now, "roles": roles, "channels": channels}
    return roles, channels


async def _detect_bot_installed(request: web.Request, *, guild_id: int) -> tuple[bool | None, str | None]:
    settings: Settings = request.app[SETTINGS_KEY]
    http = request.app.get(HTTP_SESSION_KEY)
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
    now = time.time()
    if session_id:
        sessions: Collection = request.app[SESSION_COLLECTION_KEY]
        doc = sessions.find_one({"_id": session_id}) or {}
        created_at = doc.get("created_at")
        expires_at_dt = doc.get("expires_at")
        expires_at_ts = expires_at_dt.timestamp() if isinstance(expires_at_dt, datetime) else None
        last_seen_at = doc.get("last_seen_at", created_at)
        guilds_fetched_at = doc.get("guilds_fetched_at", created_at)
        last_guild_id = doc.get("last_guild_id")
        last_guild_id_value = None
        if isinstance(last_guild_id, int):
            last_guild_id_value = last_guild_id
        elif isinstance(last_guild_id, str) and last_guild_id.isdigit():
            last_guild_id_value = int(last_guild_id)

        within_absolute_ttl = isinstance(created_at, (int, float)) and now - float(created_at) <= SESSION_TTL_SECONDS
        within_expires_at = expires_at_ts is None or now <= expires_at_ts
        idle_timeout = max(1, int(SESSION_IDLE_TIMEOUT_SECONDS)) if SESSION_IDLE_TIMEOUT_SECONDS > 0 else None
        within_idle = (
            idle_timeout is None
            or (isinstance(last_seen_at, (int, float)) and now - float(last_seen_at) <= idle_timeout)
        )
        guild_cache_ttl = max(1, int(GUILD_METADATA_TTL_SECONDS)) if GUILD_METADATA_TTL_SECONDS > 0 else None
        within_guild_cache = (
            guild_cache_ttl is None
            or (isinstance(guilds_fetched_at, (int, float)) and now - float(guilds_fetched_at) <= guild_cache_ttl)
        )

        if within_absolute_ttl and within_expires_at and within_idle and within_guild_cache:
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
                    last_seen_at=float(last_seen_at) if isinstance(last_seen_at, (int, float)) else float(created_at),
                    guilds_fetched_at=float(guilds_fetched_at)
                    if isinstance(guilds_fetched_at, (int, float))
                    else float(created_at),
                    last_guild_id=last_guild_id_value,
                )
        if session is None:
            sessions.delete_one({"_id": session_id})
        else:
            touch_interval = max(1, int(SESSION_TOUCH_INTERVAL_SECONDS))
            should_touch = now - session.last_seen_at >= touch_interval
            if should_touch:
                sessions.update_one({"_id": session_id}, {"$set": {"last_seen_at": now}})
                session.last_seen_at = now
            requested_guild_id = _extract_guild_id_from_request(request)
            if requested_guild_id and requested_guild_id != session.last_guild_id:
                sessions.update_one({"_id": session_id}, {"$set": {"last_guild_id": requested_guild_id}})
                session.last_guild_id = requested_guild_id
    request["session"] = session
    return await handler(request)


def _require_session(request: web.Request) -> SessionData:
    session = request.get("session")
    if session is None:
        next_path = _sanitize_next_path(request.path)
        if len(next_path) > 1024:
            next_path = "/"
        states: Collection = request.app[STATE_COLLECTION_KEY]
        expires_at = _utc_now() + timedelta(seconds=STATE_TTL_SECONDS)
        state = _insert_oauth_state(states=states, next_path=next_path, expires_at=expires_at)
        resp = web.HTTPFound("/login")
        resp.set_cookie(
            NEXT_COOKIE_NAME,
            state,
            httponly=True,
            samesite="Lax",
            secure=_is_https(request),
            max_age=STATE_TTL_SECONDS,
        )
        raise resp
    return session


def _admin_ids() -> set[int]:
    raw = os.environ.get("ADMIN_DISCORD_IDS", "").strip()
    if not raw:
        return set()
    ids: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if token.isdigit():
            ids.add(int(token))
    return ids


def _require_admin(session: SessionData) -> None:
    allowlist = _admin_ids()
    if not allowlist:
        raise web.HTTPForbidden(text="Admin console is not configured.")
    user = session.user
    user_id = str(user.get("id") or "")
    if not user_id.isdigit() or int(user_id) not in allowlist:
        raise web.HTTPForbidden(text="Admin access required.")


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


def _extract_guild_id_from_request(request: web.Request) -> int | None:
    path = request.path or ""
    if path.startswith("/guild/"):
        parts = path.split("/")
        if len(parts) > 2 and parts[2].isdigit():
            return int(parts[2])
    gid = str(request.query.get("guild_id") or "").strip()
    if gid.isdigit():
        return int(gid)
    return None


@web.middleware
async def security_headers_middleware(request: web.Request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc

    if not isinstance(response, (web.StreamResponse, web.HTTPException)):
        return response

    if request.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=3600")
    else:
        response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "interest-cohort=()")

    csp_parts = [
        "default-src 'self'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
        "img-src 'self' data: https://cdn.discordapp.com https://cdn.discordapp.net",
        "style-src 'self'",
        "script-src 'self'",
        "connect-src 'self' https://discord.com https://discordapp.com",
        "font-src 'self'",
        "form-action 'self'",
        "frame-src https://checkout.stripe.com",
        "object-src 'none'",
    ]
    response.headers.setdefault("Content-Security-Policy", "; ".join(csp_parts) + ";")

    if _is_https(request):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    if isinstance(response, web.HTTPException):
        raise response
    return response


def _client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return str(request.remote or "")


def _request_id(request: web.Request) -> str:
    return str(request.get("request_id") or "")


def _request_guild_id(request: web.Request) -> int | None:
    raw = request.match_info.get("guild_id") or request.query.get("guild_id")
    if raw is None:
        return None
    text = str(raw).strip()
    if text.isdigit():
        return int(text)
    return None


def _log_extra(request: web.Request, **extra: object) -> dict[str, object]:
    data = {"request_id": _request_id(request)}
    data.update(extra)
    return data


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
async def request_id_middleware(request: web.Request, handler):
    request_id = str(request.headers.get(REQUEST_ID_HEADER, "")).strip()
    if not request_id:
        request_id = secrets.token_urlsafe(8)
    request["request_id"] = request_id
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        exc.headers[REQUEST_ID_HEADER] = request_id
        raise
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


@web.middleware
async def request_metrics_middleware(request: web.Request, handler):
    if request.path.startswith("/static/"):
        return await handler(request)
    start = time.perf_counter()
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        logging.info(
            "event=http_request method=%s path=%s status=%s duration_ms=%.1f request_id=%s",
            request.method,
            request.path,
            exc.status,
            duration_ms,
            _request_id(request),
            extra=_log_extra(
                request,
                method=request.method,
                path=request.path,
                status=exc.status,
                duration_ms=duration_ms,
                guild_id=_request_guild_id(request),
            ),
        )
        raise
    duration_ms = (time.perf_counter() - start) * 1000.0
    logging.info(
        "event=http_request method=%s path=%s status=%s duration_ms=%.1f request_id=%s",
        request.method,
        request.path,
        response.status,
        duration_ms,
        _request_id(request),
        extra=_log_extra(
            request,
            method=request.method,
            path=request.path,
            status=response.status,
            duration_ms=duration_ms,
            guild_id=_request_guild_id(request),
        ),
    )
    return response


@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
    bucket, max_requests = _rate_limit_bucket_and_max(request.path)
    window_seconds = max(1, int(RATE_LIMIT_WINDOW_SECONDS))
    _sweep_rate_limit_state(window_seconds=window_seconds)

    ip = redact_ip(_client_ip(request))
    request_id = _request_id(request)
    allowed, retry_after = _rate_limit_allowed(
        key=(bucket, ip),
        limit=max(1, int(max_requests)),
        window_seconds=window_seconds,
    )
    if not allowed:
        logging.warning(
            "event=rate_limited request_id=%s bucket=%s ip=%s path=%s retry_after=%s",
            request_id,
            bucket,
            ip,
            request.path,
            retry_after,
            extra=_log_extra(
                request,
                bucket=bucket,
                client_ip=ip,
                path=request.path,
                retry_after=retry_after,
            ),
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
        ip = redact_ip(_client_ip(request))
        request_id = _request_id(request)
        logging.warning(
            "event=request_timeout request_id=%s ip=%s path=%s",
            request_id,
            ip,
            request.path,
            extra=_log_extra(request, client_ip=ip, path=request.path),
        )
        raise web.HTTPRequestTimeout(text="Request timed out.") from None


def _sanitize_next_path(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return "/"
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not value.startswith("/"):
        return "/"
    if value.startswith("//"):
        return "/"
    if value.startswith("/\\"):
        return "/"
    if "\\" in value:
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


def _guild_is_owner(session: SessionData, guild_id: int) -> bool:
    for guild in session.all_guilds:
        if str(guild.get("id")) == str(guild_id):
            return guild.get("owner") is True
    return False


async def index(request: web.Request) -> web.Response:
    settings: Settings = request.app[SETTINGS_KEY]
    invite_href = _invite_url(settings)
    from offside_bot.web_templates import render

    html = render("pages/index_public.html", title="Offside", invite_href=invite_href)
    return web.Response(text=html, content_type="text/html")


async def app_index(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]

    from offside_bot.web_templates import render

    eligible_ids = {str(g.get("id")) for g in session.owner_guilds}
    install_statuses: dict[int, dict[str, Any]] = {}
    if settings.mongodb_uri and eligible_ids:
        install_statuses = list_guild_installs(
            settings,
            guild_ids=[int(gid) for gid in eligible_ids if str(gid).isdigit()],
        )
    last_guild_id = session.last_guild_id
    guilds = [g for g in session.all_guilds if isinstance(g, dict)]
    if guilds:
        def _guild_sort_key(guild: dict[str, Any]) -> tuple[int, str]:
            gid = str(guild.get("id") or "")
            name_value = str(guild.get("name") or gid).strip().lower()
            is_last = 0 if last_guild_id and gid == str(last_guild_id) else 1
            return (is_last, name_value)

        guilds = sorted(guilds, key=_guild_sort_key)
    cards: list[dict[str, Any]] = []
    for g in guilds:
        gid = g.get("id")
        name = str(g.get("name") or gid)
        gid_str = str(gid)
        eligible = gid_str in eligible_ids
        plan = None
        plan_label = ""
        plan_class = ""
        if eligible and gid_str.isdigit():
            plan = entitlements_service.get_guild_plan(settings, guild_id=int(gid_str))
            plan_label = str(plan).upper()
            plan_class = str(plan)
        install_label = ""
        install_class = ""
        install_status: bool | None = None
        if eligible and gid_str.isdigit():
            status_doc = install_statuses.get(int(gid_str))
            if isinstance(status_doc, dict):
                status_value = status_doc.get("installed")
                if isinstance(status_value, bool):
                    install_status = status_value
            if install_status is True:
                install_label = "INSTALLED"
                install_class = "ok"
            elif install_status is False:
                install_label = "NOT INSTALLED"
                install_class = "warn"
            else:
                install_label = "UNKNOWN"
                install_class = "warn"
        icon_url = _guild_icon_url(g)
        fallback = (name[:2] or "").upper()
        show_upgrade = bool(eligible and plan and plan != entitlements_service.PLAN_PRO)
        show_invite = bool(eligible and install_status is not True)
        invite_class = "blue" if install_status is False else "secondary"
        cards.append(
            {
                "id": gid_str,
                "name": name,
                "icon_url": icon_url or "",
                "fallback": fallback,
                "eligible": eligible,
                "plan_label": plan_label,
                "plan_class": plan_class,
                "install_label": install_label,
                "install_class": install_class,
                "show_upgrade": show_upgrade,
                "show_invite": show_invite,
                "invite_class": invite_class,
            }
        )
    invite_href = _invite_url(settings)
    selected_guild_id = None
    if session.owner_guilds:
        last_gid = session.last_guild_id
        if isinstance(last_gid, int) and str(last_gid) in eligible_ids:
            selected_guild_id = last_gid
        else:
            gid = str(session.owner_guilds[0].get("id") or "").strip()
            if gid.isdigit():
                selected_guild_id = int(gid)
    installed, _install_error = (
        await _detect_bot_installed(request, guild_id=selected_guild_id)
        if selected_guild_id is not None
        else (None, None)
    )

    content = render(
        "pages/dashboard/server_picker.html",
        cards=cards,
        invite_href=invite_href,
    )
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


def _public_repo_url() -> str:
    repo = (os.environ.get("PUBLIC_REPO_URL") or "").strip()
    if not repo:
        repo = (os.environ.get("GITHUB_REPO_URL") or "").strip()
    if not repo:
        repo = DEFAULT_PUBLIC_REPO_URL
    return repo.rstrip("/")


def _mailto_link(address: str) -> str:
    return "mailto:" + urllib.parse.quote(address)


async def terms_page(_request: web.Request) -> web.Response:
    text = _repo_read_text("TERMS_OF_SERVICE.md")
    if text is None:
        raise web.HTTPNotFound(text="TERMS_OF_SERVICE.md not found.")
    html = _markdown_to_html(text)
    content = f"""
      <div class="card hero-card">
        <p class="mt-0"><a href="/">&larr; Back</a></p>
        <h1 class="mt-6 text-hero-sm">Terms of Service</h1>
      </div>
      <div class="card prose">{html}</div>
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
      <div class="card hero-card">
        <p class="mt-0"><a href="/">&larr; Back</a></p>
        <h1 class="mt-6 text-hero-sm">Privacy Policy</h1>
      </div>
      <div class="card prose">{html}</div>
    """
    from offside_bot.web_templates import render, safe_html

    page = render("pages/markdown_page.html", title="Privacy", content=safe_html(content))
    return web.Response(text=page, content_type="text/html")


async def product_copy_page(_request: web.Request) -> web.Response:
    text = _repo_read_text("docs/product-copy.md")
    if text is None:
        raise web.HTTPNotFound(text="docs/product-copy.md not found.")
    html = _markdown_to_html(text)
    content = f"""
      <div class="card hero-card">
        <p class="mt-0"><a href="/">&larr; Back</a></p>
        <h1 class="mt-6 text-hero-sm">Product</h1>
      </div>
      <div class="card prose">{html}</div>
    """
    from offside_bot.web_templates import render, safe_html

    page = render("pages/markdown_page.html", title="Product", content=safe_html(content))
    return web.Response(text=page, content_type="text/html")


async def docs_index_page(_request: web.Request) -> web.Response:
    from offside_bot.web_templates import render

    docs = [
        {"title": page["title"], "summary": page["summary"], "href": f"/docs/{page['slug']}"}
        for page in DOCS_PAGES
    ]
    docs.extend(DOCS_EXTRAS)
    page_html = render("pages/docs_index.html", title="Docs", docs=docs, active_nav="docs")
    return web.Response(text=page_html, content_type="text/html")


async def docs_page(request: web.Request) -> web.Response:
    slug = str(request.match_info.get("slug") or "").strip()
    doc = DOCS_BY_SLUG.get(slug)
    if not doc:
        raise web.HTTPNotFound(text="Doc not found.")
    text = _repo_read_text(doc["path"])
    if text is None:
        raise web.HTTPNotFound(text=f"{doc['path']} not found.")
    html = _markdown_to_html(text)
    content = f"""
      <div class="card hero-card">
        <p class="mt-0"><a href="/docs">&larr; Back to docs</a></p>
        <h1 class="mt-6 text-hero-sm">{_escape_html(doc["title"])}</h1>
      </div>
      <div class="card prose">{html}</div>
    """
    from offside_bot.web_templates import render, safe_html

    page_html = render(
        "pages/markdown_page.html",
        title=doc["title"],
        content=safe_html(content),
        active_nav="docs",
    )
    return web.Response(text=page_html, content_type="text/html")


def _commands_group_for_category(category: str) -> str:
    key = (category or "").strip().lower()
    if key in {"roster", "recruitment"}:
        return "coach"
    if key == "staff":
        return "staff"
    if key == "operations":
        return "ops"
    if key == "tournament":
        return "tournament"
    return "other"


def _strip_inline_code(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and text.startswith("`") and text.endswith("`"):
        return text[1:-1].strip()
    return text


def _parse_commands_markdown(text: str) -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []
    current_category: dict[str, Any] | None = None
    current_command: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("## "):
            name = line[3:].strip()
            current_category = {"name": name, "group": _commands_group_for_category(name), "commands": []}
            categories.append(current_category)
            current_command = None
            continue

        if line.startswith("### "):
            if current_category is None:
                continue
            signature = line[4:].strip()
            current_command = {"signature": signature, "description": "", "permissions": "", "example": ""}
            current_category["commands"].append(current_command)
            continue

        if line.startswith("- ") and current_command is not None:
            item = line[2:].strip()
            if ":" not in item:
                continue
            key, value = item.split(":", 1)
            normalized_key = key.strip().lower()
            normalized_value = value.strip()
            if normalized_key == "description":
                current_command["description"] = normalized_value
            elif normalized_key == "permissions":
                current_command["permissions"] = normalized_value
            elif normalized_key == "example":
                current_command["example"] = _strip_inline_code(normalized_value)
            continue

    for category in categories:
        for command in category.get("commands", []):
            blob = " ".join(
                part
                for part in [
                    str(command.get("signature") or ""),
                    str(command.get("description") or ""),
                    str(command.get("permissions") or ""),
                    str(command.get("example") or ""),
                ]
                if part
            )
            command["search_text"] = blob.lower()

    return [c for c in categories if c.get("commands")]


async def commands_page(_request: web.Request) -> web.Response:
    text = _repo_read_text("docs/commands.md")
    if text is None:
        raise web.HTTPNotFound(text="docs/commands.md not found.")

    categories = _parse_commands_markdown(text)
    from offside_bot.web_templates import render

    page = render("pages/commands.html", title="Commands", categories=categories, active_nav="docs")
    return web.Response(text=page, content_type="text/html")


async def features_page(_request: web.Request) -> web.Response:
    from offside_bot.web_templates import render

    page = render("pages/features.html", title="Features", active_nav="features")
    return web.Response(text=page, content_type="text/html")


async def support_page(_request: web.Request) -> web.Response:
    support_discord = os.environ.get("SUPPORT_DISCORD_INVITE_URL", "").strip()
    support_email = os.environ.get("SUPPORT_EMAIL", "").strip()
    repo = _public_repo_url()
    issues_href = f"{repo}/issues" if repo else ""
    bug_href = f"{repo}/issues/new?template=bug_report.yml" if repo else ""
    feature_href = f"{repo}/issues/new?template=feature_request.yml" if repo else ""
    docs_href = "/docs"
    readme_href = f"{repo}#readme" if repo else ""

    support_items: list[str] = []
    if support_discord:
        support_items.append(
            f'<li><a href="{_escape_html(support_discord)}">Join support Discord</a></li>'
        )
    else:
        support_items.append("<li><span class='muted'>Support Discord (invite required)</span></li>")

    if support_email:
        mailto = _mailto_link(support_email)
        support_items.append(
            f'<li><a href="{_escape_html(mailto)}">{_escape_html(support_email)}</a></li>'
        )
    else:
        support_items.append("<li><span class='muted'>Email support (set SUPPORT_EMAIL)</span></li>")

    docs_items = [
        f'<li><a href="{docs_href}">Docs hub</a></li>',
        '<li><a href="/docs/server-setup-checklist">Server setup checklist</a></li>',
        '<li><a href="/docs/billing">How billing works</a></li>',
    ]
    issue_items: list[str] = []
    if repo:
        issue_items.append(f'<li><a href="{bug_href}">Report a bug</a></li>')
        issue_items.append(f'<li><a href="{feature_href}">Request a feature</a></li>')
        issue_items.append(f'<li><a href="{issues_href}">Browse issues</a></li>')
        issue_items.append(f'<li><a href="{readme_href}">README</a></li>')
    else:
        issue_items.append("<li><span class='muted'>GitHub links unavailable (set PUBLIC_REPO_URL)</span></li>")

    content = f"""
      <div class="card hero-card">
        <p class="mt-0"><a href="/">&larr; Back</a></p>
        <h1 class="mt-6 text-hero-sm">Support</h1>
        <p class="muted mt-10">Docs, contact options, and issue reporting.</p>
      </div>
      <div class="row">
        <div class="card">
          <p><strong>Get help</strong></p>
          <p class="muted mt-6">Reach the team directly for support requests.</p>
          <ul>
            {"".join(support_items)}
          </ul>
        </div>
        <div class="card">
          <p><strong>Docs</strong></p>
          <p class="muted mt-6">Guides, checklists, and troubleshooting.</p>
          <ul>
            {"".join(docs_items)}
          </ul>
        </div>
        <div class="card">
          <p><strong>Report an issue</strong></p>
          <p class="muted mt-6">Use GitHub if you manage the repo.</p>
          <ul>
            {"".join(issue_items)}
          </ul>
        </div>
      </div>
    """
    from offside_bot.web_templates import render, safe_html

    page = render(
        "pages/markdown_page.html",
        title="Support",
        content=safe_html(content),
        active_nav="support",
    )
    return web.Response(text=page, content_type="text/html")


def _format_admin_dt(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.strftime("%Y-%m-%d %H:%M UTC")
    return ""


def _admin_actor(session: SessionData) -> tuple[int | None, str | None]:
    user = session.user
    actor_id = int(user.get("id")) if isinstance(user, dict) and str(user.get("id")).isdigit() else None
    actor_username = None
    if isinstance(user, dict):
        username = user.get("username")
        discriminator = user.get("discriminator")
        if username:
            actor_username = f"{username}#{discriminator or ''}".strip("#")
    return actor_id, actor_username


async def admin_dashboard(request: web.Request) -> web.Response:
    session = _require_session(request)
    _require_admin(session)
    settings: Settings = request.app[SETTINGS_KEY]
    from offside_bot.web_templates import render

    status = str(request.query.get("status") or "").strip().lower()
    status_message = ""
    status_kind = "info"
    status_title = t("admin.action.title", "Admin action")
    if status == "resync_ok":
        status_message = t("admin.resync.success", "Stripe resync completed.")
        status_kind = "success"
    elif status == "resync_failed":
        status_message = t("admin.resync.failed", "Stripe resync failed. Check logs for details.")
        status_kind = "warn"

    subscriptions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    dead_letters: list[dict[str, Any]] = []
    ops_tasks: list[dict[str, Any]] = []
    if settings.mongodb_uri:
        subs_col = get_subscription_collection(settings)
        for doc in subs_col.find({}).sort("updated_at", -1).limit(50):
            if not isinstance(doc, dict):
                continue
            subscriptions.append(
                {
                    "guild_id": doc.get("guild_id") or doc.get("_id"),
                    "plan": str(doc.get("plan") or "").upper(),
                    "status": str(doc.get("status") or ""),
                    "period_end": _format_admin_dt(doc.get("period_end")),
                    "customer_id": str(doc.get("customer_id") or ""),
                    "subscription_id": str(doc.get("subscription_id") or ""),
                    "updated_at": _format_admin_dt(doc.get("updated_at")),
                }
            )

        events_col = get_global_collection(settings, name=STRIPE_EVENTS_COLLECTION)
        for doc in events_col.find({}).sort("received_at", -1).limit(25):
            if not isinstance(doc, dict):
                continue
            events.append(
                {
                    "event_id": str(doc.get("_id") or ""),
                    "event_type": str(doc.get("type") or doc.get("event_type") or ""),
                    "status": str(doc.get("status") or ""),
                    "handled": str(doc.get("handled") or ""),
                    "guild_id": str(doc.get("guild_id") or ""),
                    "received_at": _format_admin_dt(doc.get("received_at")),
                }
            )

        dead_col = get_global_collection(settings, name=STRIPE_DEAD_LETTERS_COLLECTION)
        for doc in dead_col.find({}).sort("received_at", -1).limit(25):
            if not isinstance(doc, dict):
                continue
            dead_letters.append(
                {
                    "event_id": str(doc.get("_id") or ""),
                    "event_type": str(doc.get("event_type") or ""),
                    "reason": str(doc.get("reason") or ""),
                    "received_at": _format_admin_dt(doc.get("received_at")),
                }
            )

        ops_col = get_global_collection(settings, name=OPS_TASKS_COLLECTION)
        for doc in ops_col.find({}).sort("created_at", -1).limit(25):
            if not isinstance(doc, dict):
                continue
            ops_tasks.append(
                {
                    "task_id": str(doc.get("_id") or ""),
                    "guild_id": str(doc.get("guild_id") or ""),
                    "action": str(doc.get("action") or ""),
                    "status": str(doc.get("status") or ""),
                    "run_after": _format_admin_dt(doc.get("run_after")),
                    "created_at": _format_admin_dt(doc.get("created_at")),
                }
            )

    content = render(
        "pages/admin/dashboard.html",
        subscriptions=subscriptions,
        events=events,
        dead_letters=dead_letters,
        ops_tasks=ops_tasks,
        status_message=status_message,
        status_kind=status_kind,
        status_title=status_title,
        csrf_token=session.csrf_token,
    )

    body = _app_shell(
        settings=settings,
        session=session,
        section="admin",
        selected_guild_id=None,
        installed=None,
        content=content,
        nav_items_override=[{"label": "Admin", "href": "/admin", "active": True}],
        breadcrumbs_override=[{"label": "Admin", "href": "/admin"}],
        guild_selector_override=[],
    )
    return web.Response(text=_html_page(title="Admin", body=body), content_type="text/html")


async def admin_stripe_resync(request: web.Request) -> web.Response:
    session = _require_session(request)
    _require_admin(session)
    settings: Settings = request.app[SETTINGS_KEY]
    if not settings.mongodb_uri:
        raise web.HTTPBadRequest(text="MongoDB is not configured.")

    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    guild_id_raw = str(data.get("guild_id") or "").strip()
    subscription_id = str(data.get("subscription_id") or "").strip()
    guild_id = int(guild_id_raw) if guild_id_raw.isdigit() else None

    sub_doc: dict[str, Any] | None = None
    if subscription_id:
        sub_doc = get_guild_subscription_by_subscription_id(settings, subscription_id=subscription_id)
    if sub_doc is None and guild_id is not None:
        sub_doc = get_guild_subscription(settings, guild_id=guild_id)
    if not subscription_id and isinstance(sub_doc, dict):
        subscription_id = str(sub_doc.get("subscription_id") or "").strip()

    if not subscription_id:
        raise web.HTTPBadRequest(text="Missing subscription ID.")

    try:
        import stripe  # type: ignore[import-not-found]
    except Exception:
        raise web.HTTPBadRequest(text="Stripe SDK is not installed.") from None

    try:
        stripe.api_key = _require_env("STRIPE_SECRET_KEY")
        sub = stripe.Subscription.retrieve(subscription_id)
        metadata = sub.get("metadata") if hasattr(sub, "get") else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        meta_guild_id = _parse_int(metadata.get("guild_id"))
        target_guild_id = guild_id or meta_guild_id or _parse_int(sub_doc.get("guild_id") if sub_doc else None)
        if target_guild_id is None:
            raise RuntimeError("Unable to resolve guild_id for subscription.")

        plan = str(metadata.get("plan") or (sub_doc.get("plan") if sub_doc else "") or entitlements_service.PLAN_PRO)
        status = str(sub.get("status") if hasattr(sub, "get") else getattr(sub, "status", "unknown") or "unknown")
        period_end_raw = sub.get("current_period_end") if hasattr(sub, "get") else getattr(sub, "current_period_end", None)
        period_end = None
        if isinstance(period_end_raw, (int, float)):
            period_end = datetime.fromtimestamp(float(period_end_raw), tz=timezone.utc)
        customer_id = sub.get("customer") if hasattr(sub, "get") else getattr(sub, "customer", None)

        upsert_guild_subscription(
            settings,
            guild_id=target_guild_id,
            plan=str(plan).strip().lower(),
            status=str(status).strip().lower(),
            period_end=period_end,
            customer_id=str(customer_id) if customer_id else None,
            subscription_id=subscription_id,
        )
        entitlements_service.invalidate_guild_plan(target_guild_id)
        actor_id, actor_username = _admin_actor(session)
        record_audit_event(
            guild_id=target_guild_id,
            category="admin",
            action="stripe.resync",
            source="admin_console",
            actor_discord_id=actor_id,
            actor_username=actor_username,
            details={
                "subscription_id": subscription_id,
                "status": str(status),
            },
        )
    except Exception:
        logging.exception("admin_stripe_resync_failed", extra={"subscription_id": subscription_id})
        raise web.HTTPFound("/admin?status=resync_failed") from None

    raise web.HTTPFound("/admin?status=resync_ok")


async def enterprise_page(_request: web.Request) -> web.Response:
    support_discord = os.environ.get("SUPPORT_DISCORD_INVITE_URL", "").strip()
    support_email = os.environ.get("SUPPORT_EMAIL", "").strip()
    sales_email = os.environ.get("SALES_EMAIL", "").strip()
    contact_email = sales_email or support_email
    mailto = _mailto_link(contact_email) if contact_email else ""

    from offside_bot.web_templates import render

    page = render(
        "pages/enterprise.html",
        title="Enterprise",
        contact_email=contact_email,
        mailto_href=mailto,
        support_discord=support_discord,
    )
    return web.Response(text=page, content_type="text/html")


async def pricing_page(request: web.Request) -> web.Response:
    session = request.get("session")
    billing = str(request.query.get("billing") or "monthly").strip().lower()
    if billing not in {"monthly", "yearly"}:
        billing = "monthly"

    pro_monthly_price = os.environ.get("PRICING_PRO_MONTHLY_USD", "9").strip() or "9"
    pro_cta_href = "/app/billing"
    if session is None:
        pro_cta_href = "/login?next=/app/billing"
    enterprise_cta_href = "/enterprise"

    features = [
        {
            "name": "Dashboards + setup wizard",
            "description": "Auto-setup, portal dashboards, listing channels, and guided setup checks.",
            "free": True,
            "pro": True,
            "enterprise": True,
        },
        {
            "name": "Roster + recruiting workflows",
            "description": "Rosters, recruiting, clubs, and staff workflows inside Discord.",
            "free": True,
            "pro": True,
            "enterprise": True,
        },
        {
            "name": "Analytics",
            "description": "Per-server collection analytics and operational visibility.",
            "free": True,
            "pro": True,
            "enterprise": True,
        },
        {
            "name": "Premium coach tiers",
            "description": "Premium caps (22/25) and premium coach tier management.",
            "free": False,
            "pro": entitlements_service.FEATURE_PREMIUM_COACH_TIERS in entitlements_service.PRO_FEATURE_KEYS,
            "enterprise": True,
        },
        {
            "name": "Premium Coaches report",
            "description": "Premium coach listing embed and related controls.",
            "free": False,
            "pro": entitlements_service.FEATURE_PREMIUM_COACHES_REPORT in entitlements_service.PRO_FEATURE_KEYS,
            "enterprise": True,
        },
        {
            "name": "FC25 stats integration",
            "description": "Link accounts and refresh player stats (feature flagged).",
            "free": False,
            "pro": entitlements_service.FEATURE_FC25_STATS in entitlements_service.PRO_FEATURE_KEYS,
            "enterprise": True,
        },
        {
            "name": "Banlist checks",
            "description": "Google Sheets-driven banlist checks during roster actions.",
            "free": False,
            "pro": entitlements_service.FEATURE_BANLIST in entitlements_service.PRO_FEATURE_KEYS,
            "enterprise": True,
        },
        {
            "name": "Tournament automation",
            "description": "Staff tournament automation tooling.",
            "free": False,
            "pro": entitlements_service.FEATURE_TOURNAMENT_AUTOMATION in entitlements_service.PRO_FEATURE_KEYS,
            "enterprise": True,
        },
    ]

    from offside_bot.web_templates import render

    html = render(
        "pages/pricing.html",
        title="Pricing",
        billing=billing,
        toggle_monthly_href="/pricing?billing=monthly",
        toggle_yearly_href="/pricing?billing=yearly",
        pro_monthly_price=pro_monthly_price,
        pro_cta_href=pro_cta_href,
        enterprise_cta_href=enterprise_cta_href,
        features=features,
        active_nav="pricing",
    )
    return web.Response(text=html, content_type="text/html")


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def ready(request: web.Request) -> web.Response:
    settings: Settings = request.app[SETTINGS_KEY]
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
    settings: Settings = request.app[SETTINGS_KEY]
    client_id, _client_secret, redirect_uri = _oauth_config(settings)
    states: Collection = request.app[STATE_COLLECTION_KEY]
    expires_at = _utc_now() + timedelta(seconds=STATE_TTL_SECONDS)

    next_param = str(request.query.get("next") or "").strip()
    cookie_state = str(request.cookies.get(NEXT_COOKIE_NAME) or "").strip()
    if cookie_state and len(cookie_state) > 128:
        cookie_state = ""

    next_path = "/"
    state: str | None = None
    if next_param:
        next_path = _sanitize_next_path(next_param).split("?", 1)[0]
        state = _insert_oauth_state(states=states, next_path=next_path, expires_at=expires_at)
    elif cookie_state:
        raw_doc = states.find_one({"_id": cookie_state})
        doc = raw_doc if isinstance(raw_doc, dict) else None
        expires_at_value = doc.get("expires_at") if doc else None
        if isinstance(expires_at_value, datetime) and expires_at_value.tzinfo is None:
            expires_at_value = expires_at_value.replace(tzinfo=timezone.utc)
        if doc and isinstance(expires_at_value, datetime) and expires_at_value > _utc_now():
            next_path = _sanitize_next_path(str(doc.get("next") or "/"))
            state = cookie_state
        else:
            states.delete_one({"_id": cookie_state})
    if state is None:
        state = _insert_oauth_state(states=states, next_path=next_path, expires_at=expires_at)
    authorize_url = _build_authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        scope="identify guilds",
    )
    parsed = urllib.parse.urlparse(authorize_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc not in {"discord.com", "canary.discord.com", "ptb.discord.com"}
        or parsed.path != "/oauth2/authorize"
    ):
        logging.error("event=oauth_authorize_url_invalid", extra=_log_extra(request))
        raise web.HTTPInternalServerError(text="OAuth is misconfigured.")
    resp = web.HTTPFound(authorize_url)
    resp.del_cookie(NEXT_COOKIE_NAME)
    raise resp


async def install(request: web.Request) -> web.Response:
    settings: Settings = request.app[SETTINGS_KEY]
    client_id, _client_secret, redirect_uri = _oauth_config(settings)

    requested_guild_id = request.query.get("guild_id", "").strip()
    next_path = "/"
    extra: dict[str, str] = {"permissions": str(DEFAULT_BOT_PERMISSIONS)}
    if requested_guild_id.isdigit():
        extra["guild_id"] = requested_guild_id
        extra["disable_guild_select"] = "true"
        next_path = f"/guild/{requested_guild_id}/permissions"

    states: Collection = request.app[STATE_COLLECTION_KEY]
    expires_at = _utc_now() + timedelta(seconds=STATE_TTL_SECONDS)
    state = _insert_oauth_state(states=states, next_path=next_path, expires_at=expires_at)
    authorize_url = _build_authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        scope="identify guilds bot applications.commands",
        extra_params=extra,
    )
    parsed = urllib.parse.urlparse(authorize_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc not in {"discord.com", "canary.discord.com", "ptb.discord.com"}
        or parsed.path != "/oauth2/authorize"
    ):
        logging.error("event=oauth_authorize_url_invalid", extra=_log_extra(request))
        raise web.HTTPInternalServerError(text="OAuth is misconfigured.")
    raise web.HTTPFound(authorize_url)


def _oauth_error_response(
    *,
    title: str,
    message: str,
    next_path: str,
    status: int = 400,
) -> web.Response:
    from offside_bot.web_templates import render, safe_html

    next_path = _sanitize_next_path(next_path)
    login_href = f"/login?{urllib.parse.urlencode({'next': next_path})}"
    content = f"""
      <p><a href="/">&larr; Back</a></p>
      <h1>{_escape_html(title)}</h1>
      <div class="card">
        <p class="muted">{_escape_html(message)}</p>
        <div class="btn-group mt-12">
          <a class="btn blue" href="{_escape_html(login_href)}">Try again</a>
          <a class="btn secondary" href="/support">Support</a>
        </div>
      </div>
    """
    page = render("pages/markdown_page.html", title=title, content=safe_html(content))
    return web.Response(text=page, status=status, content_type="text/html")


async def oauth_callback(request: web.Request) -> web.Response:
    settings: Settings = request.app[SETTINGS_KEY]
    client_id, client_secret, redirect_uri = _oauth_config(settings)
    http: ClientSession = request.app[HTTP_SESSION_KEY]
    request_id = _request_id(request)

    code = str(request.query.get("code") or "").strip()
    state = str(request.query.get("state") or "").strip()
    error = str(request.query.get("error") or "").strip()
    error_description = str(request.query.get("error_description") or "").strip()

    next_path = "/"
    issued_at: float | None = None
    pending_state: dict[str, Any] | None = None
    if state:
        states: Collection = request.app[STATE_COLLECTION_KEY]
        raw_state = states.find_one_and_delete({"_id": state})
        pending_state = raw_state if isinstance(raw_state, dict) else None
        issued_at_value = pending_state.get("issued_at") if pending_state else None
        try:
            issued_at = float(issued_at_value) if issued_at_value is not None else None
        except (TypeError, ValueError):
            issued_at = None
        next_path = str(pending_state.get("next") or "/") if pending_state else "/"
        next_path = _sanitize_next_path(next_path)

    if error:
        if error == "access_denied":
            return _oauth_error_response(
                title=t("oauth.cancelled.title", "Login cancelled"),
                message=t(
                    "oauth.cancelled.message",
                    "Discord authorization was cancelled. You can try again when you're ready.",
                ),
                next_path=next_path,
                status=200,
            )
        detail = f" ({error_description})" if error_description else ""
        return _oauth_error_response(
            title=t("oauth.failed.title", "Login failed"),
            message=f"Discord returned an OAuth error: {error}{detail}",
            next_path=next_path,
            status=400,
        )

    if not state or not code:
        return _oauth_error_response(
            title=t("oauth.failed.title", "Login failed"),
            message=t("oauth.failed.missing_code", "Missing code/state. Please try logging in again."),
            next_path=next_path,
            status=400,
        )

    if issued_at is None or time.time() - issued_at > STATE_TTL_SECONDS:
        return _oauth_error_response(
            title=t("oauth.expired.title", "Login expired"),
            message=t("oauth.expired.message", "Your login attempt expired. Please try logging in again."),
            next_path=next_path,
            status=400,
        )

    try:
        token = await _exchange_code(
            http,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
    except web.HTTPException as exc:
        detail = redact_text(str(exc.text))
        logging.warning(
            "event=oauth_exchange_failed request_id=%s status=%s detail=%s",
            request_id,
            exc.status,
            detail,
            extra=_log_extra(request, status=exc.status),
        )
        return _oauth_error_response(
            title=t("oauth.failed.title", "Login failed"),
            message=t("oauth.failed.token", "Discord token exchange failed. Please try again."),
            next_path=next_path,
            status=502,
        )
    except Exception:
        logging.exception(
            "event=oauth_exchange_failed_unhandled request_id=%s",
            request_id,
            extra=_log_extra(request),
        )
        return _oauth_error_response(
            title=t("oauth.failed.title", "Login failed"),
            message=t("oauth.failed.token", "Discord token exchange failed. Please try again."),
            next_path=next_path,
            status=502,
        )
    access_token = str(token.get("access_token") or "")
    if not access_token:
        return _oauth_error_response(
            title=t("oauth.failed.title", "Login failed"),
            message=t("oauth.failed.no_token", "Discord did not return an access token. Please try again."),
            next_path=next_path,
            status=502,
        )

    try:
        user = await _discord_get_json(http, url=ME_URL, access_token=access_token)
        guilds = await _discord_get_json(http, url=MY_GUILDS_URL, access_token=access_token)
    except web.HTTPException as exc:
        detail = redact_text(str(exc.text))
        logging.warning(
            "event=oauth_discord_api_failed request_id=%s status=%s detail=%s",
            request_id,
            exc.status,
            detail,
            extra=_log_extra(request, status=exc.status),
        )
        return _oauth_error_response(
            title=t("oauth.failed.title", "Login failed"),
            message=t("oauth.failed.api", "Discord API request failed. Please try again."),
            next_path=next_path,
            status=502,
        )
    except Exception:
        logging.exception(
            "event=oauth_discord_api_failed_unhandled request_id=%s",
            request_id,
            extra=_log_extra(request),
        )
        return _oauth_error_response(
            title=t("oauth.failed.title", "Login failed"),
            message=t("oauth.failed.api", "Discord API request failed. Please try again."),
            next_path=next_path,
            status=502,
        )
    all_guilds = [g for g in guilds if isinstance(g, dict)]
    owner_guilds = [g for g in all_guilds if _guild_is_eligible(g)]

    try:
        _upsert_user_record(settings, user)
    except Exception:
        logging.exception(
            "event=upsert_user_record_failed request_id=%s",
            request_id,
            extra=_log_extra(request),
        )

    installed_guild_id = request.query.get("guild_id", "").strip()
    last_guild_id = int(installed_guild_id) if installed_guild_id.isdigit() else None
    if installed_guild_id.isdigit():
        for g in owner_guilds:
            if str(g.get("id")) == installed_guild_id:
                next_path = f"/guild/{installed_guild_id}"
                break

    sessions: Collection = request.app[SESSION_COLLECTION_KEY]
    expires_at = _utc_now() + timedelta(seconds=SESSION_TTL_SECONDS)
    csrf_token = secrets.token_urlsafe(24)
    now_ts = time.time()
    session_id = _insert_unique(
        sessions,
        lambda: {
            "_id": secrets.token_urlsafe(32),
            "created_at": now_ts,
            "last_seen_at": now_ts,
            "guilds_fetched_at": now_ts,
            "expires_at": expires_at,
            "user": user,
            "owner_guilds": owner_guilds,
            "all_guilds": all_guilds,
            "csrf_token": csrf_token,
            "last_guild_id": last_guild_id,
        },
    )

    safe_next_path = "/"
    candidate_next_path = next_path
    if (
        candidate_next_path.startswith("/")
        and not candidate_next_path.startswith("//")
        and not candidate_next_path.startswith("/\\")
        and "\\" not in candidate_next_path
    ):
        safe_next_path = candidate_next_path
    resp = web.HTTPFound(safe_next_path)
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
        sessions: Collection = request.app[SESSION_COLLECTION_KEY]
        sessions.delete_one({"_id": session_id})
    resp = web.HTTPFound("/")
    resp.del_cookie(COOKIE_NAME)
    raise resp


def _require_owned_guild(
    session: SessionData,
    *,
    guild_id: str,
    settings: Settings | None = None,
    path: str | None = None,
) -> int:
    try:
        gid_int = int(guild_id)
    except ValueError as exc:
        raise web.HTTPBadRequest(text="Invalid guild id.") from exc
    for g in session.owner_guilds:
        if str(g.get("id")) == str(guild_id):
            set_guild_tag(gid_int)
            return gid_int
    try:
        user = session.user
        actor_id = int(user.get("id")) if isinstance(user, dict) and str(user.get("id")).isdigit() else None
        actor_username = None
        if isinstance(user, dict):
            username = user.get("username")
            discriminator = user.get("discriminator")
            if username:
                actor_username = f"{username}#{discriminator or ''}".strip("#")
        audit_collection = None
        if settings is not None:
            audit_collection = get_collection(settings, record_type="audit_event", guild_id=gid_int)
        record_audit_event(
            guild_id=gid_int,
            category="auth",
            action="dashboard.access_denied",
            source="dashboard",
            actor_discord_id=actor_id,
            actor_username=actor_username,
            details={"reason": "guild_not_authorized", "path": path},
            collection=audit_collection,
        )
    except Exception:
        logging.exception("event=access_denied_audit_failed guild_id=%s", guild_id)
    raise web.HTTPForbidden(text="You do not have access to this guild.")


def _require_guild_owner(
    session: SessionData,
    *,
    guild_id: int,
    settings: Settings | None = None,
    path: str | None = None,
) -> None:
    if _guild_is_owner(session, guild_id):
        return
    try:
        user = session.user
        actor_id = int(user.get("id")) if isinstance(user, dict) and str(user.get("id")).isdigit() else None
        actor_username = None
        if isinstance(user, dict):
            username = user.get("username")
            discriminator = user.get("discriminator")
            if username:
                actor_username = f"{username}#{discriminator or ''}".strip("#")
        audit_collection = None
        if settings is not None:
            audit_collection = get_collection(settings, record_type="audit_event", guild_id=guild_id)
        record_audit_event(
            guild_id=guild_id,
            category="auth",
            action="dashboard.billing_denied",
            source="dashboard",
            actor_discord_id=actor_id,
            actor_username=actor_username,
            details={"reason": "owner_required", "path": path},
            collection=audit_collection,
        )
    except Exception:
        pass
    raise web.HTTPForbidden(text="Billing is restricted to guild owners.")


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
    settings: Settings = request.app[SETTINGS_KEY]
    from offside_bot.web_templates import render

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

    installed, install_error = await _detect_bot_installed(request, guild_id=guild_id)
    invite_href = _invite_url(settings, guild_id=str(guild_id), disable_guild_select=True)
    if installed is False:
        content = render(
            "pages/dashboard/guild_settings.html",
            installed=installed,
            guild_id=guild_id,
            invite_href=invite_href,
        )
        return web.Response(
            text=_html_page(
                title="Guild Settings",
                body=_app_shell(
                    settings=settings,
                    session=session,
                    section="settings",
                    selected_guild_id=guild_id,
                    installed=installed,
                    content=content,
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

    staff_role_options: list[dict[str, Any]] = []
    if roles:
        for role in roles:
            role_id = role.get("id")
            if role_id is None:
                continue
            try:
                role_id_int = int(role_id)
            except (TypeError, ValueError):
                continue
            name = str(role.get("name") or role_id_int)
            staff_role_options.append(
                {
                    "value": role_id_int,
                    "label": name,
                    "selected": role_id_int in staff_role_ids,
                    "disabled": False,
                }
            )
    roles_available = bool(roles)

    coach_role_id = _parse_int(cfg.get("role_coach_id"))
    premium_role_id = _parse_int(cfg.get("role_coach_premium_id"))
    premium_plus_role_id = _parse_int(cfg.get("role_coach_premium_plus_id"))
    premium_badge_class = "pro" if premium_tiers_enabled else "warn"

    coach_role_fields: list[dict[str, Any]] = []
    if roles:
        valid_role_ids = {_parse_int(r.get("id")) for r in roles}
        valid_role_ids.discard(None)

        def _role_options(selected_id: int | None) -> list[dict[str, Any]]:
            default_selected = selected_id is None
            option_lines = [
                {
                    "value": "",
                    "label": "(Use default)",
                    "selected": default_selected,
                    "disabled": False,
                }
            ]
            if selected_id is not None and selected_id not in valid_role_ids:
                option_lines.append(
                    {
                        "value": selected_id,
                        "label": f"(missing id: {selected_id})",
                        "selected": True,
                        "disabled": False,
                    }
                )
            for role in roles:
                rid = _parse_int(role.get("id"))
                if rid is None or rid == guild_id:
                    continue
                name = str(role.get("name") or rid)
                option_lines.append(
                    {
                        "value": rid,
                        "label": name,
                        "selected": rid == selected_id,
                        "disabled": False,
                    }
                )
            return option_lines

        coach_role_fields = [
            {
                "label": "Coach role",
                "name": "role_coach_id",
                "options": _role_options(coach_role_id),
                "value": str(coach_role_id or ""),
                "disabled": False,
                "show_pro_badge": False,
                "pro_badge_class": premium_badge_class,
            },
            {
                "label": "Coach Premium role",
                "name": "role_coach_premium_id",
                "options": _role_options(premium_role_id),
                "value": str(premium_role_id or ""),
                "disabled": not premium_tiers_enabled,
                "show_pro_badge": True,
                "pro_badge_class": premium_badge_class,
            },
            {
                "label": "Coach Premium+ role",
                "name": "role_coach_premium_plus_id",
                "options": _role_options(premium_plus_role_id),
                "value": str(premium_plus_role_id or ""),
                "disabled": not premium_tiers_enabled,
                "show_pro_badge": True,
                "pro_badge_class": premium_badge_class,
            },
        ]
    else:
        coach_role_fields = [
            {
                "label": "Coach role",
                "name": "role_coach_id",
                "options": [],
                "value": str(coach_role_id or ""),
                "disabled": False,
                "show_pro_badge": False,
                "pro_badge_class": premium_badge_class,
            },
            {
                "label": "Coach Premium role",
                "name": "role_coach_premium_id",
                "options": [],
                "value": str(premium_role_id or ""),
                "disabled": not premium_tiers_enabled,
                "show_pro_badge": True,
                "pro_badge_class": premium_badge_class,
            },
            {
                "label": "Coach Premium+ role",
                "name": "role_coach_premium_plus_id",
                "options": [],
                "value": str(premium_plus_role_id or ""),
                "disabled": not premium_tiers_enabled,
                "show_pro_badge": True,
                "pro_badge_class": premium_badge_class,
            },
        ]

    selected_channels: dict[str, int | None] = {
        field: _parse_int(cfg.get(field)) for field, _label in GUILD_CHANNEL_FIELDS
    }

    channel_fields: list[dict[str, Any]] = []
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

        def _channel_options(selected_id: int | None) -> list[dict[str, Any]]:
            default_selected = selected_id is None
            option_lines = [
                {
                    "value": "",
                    "label": "(Use default)",
                    "selected": default_selected,
                    "disabled": False,
                }
            ]
            if selected_id is not None and selected_id not in valid_channel_ids:
                option_lines.append(
                    {
                        "value": selected_id,
                        "label": f"(missing id: {selected_id})",
                        "selected": True,
                        "disabled": False,
                    }
                )
            for cid, label in sorted(channel_labels.items(), key=lambda kv: kv[1].lower()):
                option_lines.append(
                    {
                        "value": cid,
                        "label": label,
                        "selected": cid == selected_id,
                        "disabled": False,
                    }
                )
            return option_lines

        for field, label in GUILD_CHANNEL_FIELDS:
            selected_id = selected_channels.get(field)
            channel_fields.append(
                {
                    "label": label,
                    "name": field,
                    "options": _channel_options(selected_id),
                    "value": str(selected_id or ""),
                }
            )
    else:
        for field, label in GUILD_CHANNEL_FIELDS:
            selected_id = selected_channels.get(field)
            channel_fields.append(
                {
                    "label": label,
                    "name": field,
                    "options": [],
                    "value": str(selected_id or ""),
                }
            )

    channels_available = bool(channels)

    premium_pin_enabled = _parse_bool(cfg.get(PREMIUM_COACHES_PIN_ENABLED_KEY))
    premium_report_badge_class = "pro" if premium_report_enabled else "warn"

    fc25_value = cfg.get(FC25_STATS_ENABLED_KEY)
    if fc25_value is True:
        fc25_selected = "true"
    elif fc25_value is False:
        fc25_selected = "false"
    else:
        fc25_selected = "default"

    fc25_options = [
        {"value": "default", "label": "Default", "selected": fc25_selected == "default"},
        {"value": "true", "label": "Enabled", "selected": fc25_selected == "true"},
        {"value": "false", "label": "Disabled", "selected": fc25_selected == "false"},
    ]
    fc25_badge_class = "pro" if fc25_stats_enabled else "warn"

    saved = bool(request.query.get("saved", "").strip())
    config_rows = [
        {"key": str(k), "value": str(v)}
        for k, v in sorted(cfg.items(), key=lambda item: str(item[0]))
    ]

    content = render(
        "pages/dashboard/guild_settings.html",
        installed=installed,
        guild_id=guild_id,
        invite_href=invite_href,
        csrf_token=session.csrf_token,
        metadata_error=metadata_error,
        roles_available=roles_available,
        channels_available=channels_available,
        staff_role_options=staff_role_options,
        staff_role_ids_csv=staff_role_ids_value,
        coach_role_fields=coach_role_fields,
        channel_fields=channel_fields,
        premium_tiers_enabled=premium_tiers_enabled,
        premium_badge_class=premium_badge_class,
        premium_report_enabled=premium_report_enabled,
        premium_report_badge_class=premium_report_badge_class,
        premium_pin_enabled=premium_pin_enabled,
        premium_pin_disabled=not premium_report_enabled,
        premium_pin_key=PREMIUM_COACHES_PIN_ENABLED_KEY,
        fc25_options=fc25_options,
        fc25_disabled=not fc25_stats_enabled,
        fc25_badge_class=fc25_badge_class,
        upgrade_href=upgrade_href,
        saved=saved,
        show_pro_callout=not is_pro,
        config_rows=config_rows,
    )

    return web.Response(
        text=_html_page(
            title="Guild Settings",
            body=_app_shell(
                settings=settings,
                session=session,
                section="settings",
                selected_guild_id=guild_id,
                installed=installed,
                content=content,
            ),
        ),
        content_type="text/html",
    )


async def guild_settings_save(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    request_id = _request_id(request)
    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

    installed, _install_error = await _detect_bot_installed(request, guild_id=guild_id)
    if not _guild_is_owner(session, guild_id):
        return _owner_locked_page(
            settings=settings,
            session=session,
            guild_id=guild_id,
            installed=installed,
            section="billing",
            title="Billing",
            message="Billing access is restricted to the server owner. Ask the owner to manage upgrades and invoices.",
        )
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
        logging.exception(
            "event=guild_settings_save_failed request_id=%s guild_id=%s",
            request_id,
            guild_id,
            extra=_log_extra(request, guild_id=guild_id),
        )
        raise web.HTTPInternalServerError(text="Failed to save settings.") from exc

    raise web.HTTPFound(f"/guild/{guild_id}/settings?saved=1")


async def guild_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    from offside_bot.web_templates import render

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

    installed, _install_error = await _detect_bot_installed(request, guild_id=guild_id)
    analytics = get_guild_analytics(settings, guild_id=guild_id)
    plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)

    record_counts = [
        {"record_type": rt, "count": count}
        for rt, count in sorted(analytics.record_type_counts.items())
    ]
    collection_counts = [
        {"collection": name, "count": info.get("count")}
        for name, info in sorted(analytics.collections.items())
    ]

    content = render(
        "pages/dashboard/guild_analytics.html",
        guild_id=guild_id,
        plan_label=str(plan).upper(),
        plan_class=str(plan),
        db_name=analytics.db_name,
        generated_at=analytics.generated_at.isoformat(),
        analytics_json_href=f"/api/guild/{guild_id}/analytics.json",
        settings_href=f"/guild/{guild_id}/settings",
        permissions_href=f"/guild/{guild_id}/permissions",
        audit_href=f"/guild/{guild_id}/audit",
        record_counts=record_counts,
        collection_counts=collection_counts,
    )
    return web.Response(
        text=_html_page(
            title="Guild Analytics",
            body=_app_shell(
                settings=settings,
                session=session,
                section="analytics",
                selected_guild_id=guild_id,
                installed=installed,
                content=content,
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
    settings: Settings = request.app[SETTINGS_KEY]
    from offside_bot.web_templates import render

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

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

    def _status(label: str, kind: str) -> dict[str, str]:
        return {"label": label, "kind": kind}

    install_status = _status("OK", "ok") if installed is True else _status("WARN", "warn")
    install_details = "Installed and reachable via bot token."
    install_fix = f"/guild/{guild_id}/settings"
    if installed is False:
        install_details = install_error or "Bot is not installed in this server yet."
        install_fix = invite_href
    elif installed is None:
        install_status = _status("UNKNOWN", "warn")
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

    roles_status = _status("OK", "ok")
    roles_details = "All required coach roles are configured."
    if config_error:
        roles_status = _status("UNKNOWN", "warn")
        roles_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        roles_status = _status("WARN", "warn")
        roles_details = "Install the bot to validate roles."
    elif metadata_error:
        roles_status = _status("UNKNOWN", "warn")
        roles_details = f"Unable to load Discord roles: {metadata_error}"
    elif missing_role_fields or missing_roles_in_discord:
        roles_status = _status("WARN", "warn")
        parts: list[str] = []
        if missing_role_fields:
            parts.append(f"Missing in settings: {', '.join(missing_role_fields)}")
        if missing_roles_in_discord:
            parts.append(f"Not found in Discord: {', '.join(missing_roles_in_discord)}")
        roles_details = " / ".join(parts) or "Roles are not fully configured."

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

    channels_status = _status("OK", "ok")
    channels_details = "All required channels are configured."
    if config_error:
        channels_status = _status("UNKNOWN", "warn")
        channels_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        channels_status = _status("WARN", "warn")
        channels_details = "Install the bot to validate channels."
    elif metadata_error:
        channels_status = _status("UNKNOWN", "warn")
        channels_details = f"Unable to load Discord channels: {metadata_error}"
    elif missing_channel_fields or missing_channels_in_discord:
        channels_status = _status("WARN", "warn")
        parts = []
        if missing_channel_fields:
            parts.append(f"Missing in settings: {', '.join(missing_channel_fields)}")
        if missing_channels_in_discord:
            parts.append(f"Not found in Discord: {', '.join(missing_channels_in_discord)}")
        channels_details = " / ".join(parts) or "Channels are not fully configured."

    posts_status = _status("OK", "ok")
    posts_details = "Dashboard and listing embeds detected."
    if config_error:
        posts_status = _status("UNKNOWN", "warn")
        posts_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        posts_status = _status("WARN", "warn")
        posts_details = "Install the bot to validate posted embeds."
    else:
        http = request.app.get(HTTP_SESSION_KEY)
        if not isinstance(http, ClientSession):
            posts_status = _status("UNKNOWN", "warn")
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
                posts_status = _status("WARN", "warn")
                posts_details = f"Missing channel settings: {', '.join(missing_config)}"
            elif unknown_posts:
                posts_status = _status("UNKNOWN", "warn")
                posts_details = "Unable to verify some channels (missing Read Message History?)."
            elif missing_posts:
                posts_status = _status("WARN", "warn")
                posts_details = f"Missing embeds in: {', '.join(missing_posts)}"

    checks = [
        {
            "name": "Bot installed",
            "status": install_status,
            "details": install_details,
            "fix_href": install_fix,
        },
        {
            "name": "Coach roles",
            "status": roles_status,
            "details": roles_details,
            "fix_href": f"/guild/{guild_id}/settings",
        },
        {
            "name": "Channels",
            "status": channels_status,
            "details": channels_details,
            "fix_href": f"/guild/{guild_id}/settings",
        },
        {
            "name": "Portals posted",
            "status": posts_status,
            "details": posts_details,
            "fix_href": f"/guild/{guild_id}/ops",
        },
    ]

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

    metrics = [
        {"label": "Roster submissions", "value": submissions_display},
        {"label": "Approvals", "value": approvals_display},
        {"label": "Tournaments created", "value": tournaments_display},
    ]

    content = render(
        "pages/dashboard/guild_overview.html",
        guild_id=guild_id,
        db_name=db_name,
        test_mode="true" if settings.test_mode else "false",
        checks=checks,
        metrics=metrics,
        mongodb_configured=bool(settings.mongodb_uri),
        actions_disabled=installed is False,
        csrf_token=session.csrf_token,
        settings_href=f"/guild/{guild_id}/settings",
    )

    return web.Response(
        text=_html_page(
            title="Overview",
            body=_app_shell(
                settings=settings,
                session=session,
                section="overview",
                selected_guild_id=guild_id,
                installed=installed,
                content=content,
            ),
        ),
        content_type="text/html",
    )


async def guild_setup_wizard_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    from offside_bot.web_templates import render

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

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

    def _status(label: str, kind: str) -> dict[str, str]:
        return {"label": label, "kind": kind}

    # Step 1: Permissions (quick summary; full details on /permissions)
    perms_status = _status("UNKNOWN", "warn")
    perms_details = "Unable to verify bot permissions."
    perms_ok = False
    if installed is False:
        perms_status = _status("WARN", "warn")
        perms_details = install_error or "Bot is not installed in this server yet."
    elif installed is True:
        http = request.app.get(HTTP_SESSION_KEY)
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
                    perms_status = _status("OK", "ok")
                    perms_details = (
                        "Required permissions are present."
                        if not missing_optional
                        else f"Missing optional: {', '.join(missing_optional)}"
                    )
                else:
                    perms_status = _status("WARN", "warn")
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
        channels_status = _status("UNKNOWN", "warn")
        channels_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        channels_status = _status("WARN", "warn")
        channels_details = "Install the bot to validate channels."
    elif metadata_error:
        channels_status = _status("UNKNOWN", "warn")
        channels_details = f"Unable to load Discord channels: {metadata_error}"
    elif channels_missing_settings or channels_missing_discord:
        channels_status = _status("WARN", "warn")
        parts: list[str] = []
        if channels_missing_settings:
            parts.append(f"Missing in settings: {', '.join(channels_missing_settings)}")
        if channels_missing_discord:
            parts.append(f"Not found in Discord: {', '.join(channels_missing_discord)}")
        channels_details = " / ".join(parts) or "Channels are not ready."
    else:
        channels_ok = True
        channels_status = _status("OK", "ok")
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
        roles_status = _status("UNKNOWN", "warn")
        roles_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        roles_status = _status("WARN", "warn")
        roles_details = "Install the bot to validate roles."
    elif metadata_error:
        roles_status = _status("UNKNOWN", "warn")
        roles_details = f"Unable to load Discord roles: {metadata_error}"
    elif roles_missing_settings or roles_missing_discord:
        roles_status = _status("WARN", "warn")
        parts = []
        if roles_missing_settings:
            parts.append(f"Missing in settings: {', '.join(roles_missing_settings)}")
        if roles_missing_discord:
            parts.append(f"Not found in Discord: {', '.join(roles_missing_discord)}")
        roles_details = " / ".join(parts) or "Roles are not ready."
    else:
        roles_ok = True
        roles_status = _status("OK", "ok")
        roles_details = "Roles are configured."

    # Step 4: Portals posted
    portals_ok = False
    portals_status = _status("UNKNOWN", "warn")
    portals_details = "Unable to verify posted portals."
    if config_error:
        portals_details = f"Settings unavailable: {config_error}"
    elif installed is not True:
        portals_status = _status("WARN", "warn")
        portals_details = "Install the bot to validate posted portals."
    else:
        http = request.app.get(HTTP_SESSION_KEY)
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
                portals_status = _status("WARN", "warn")
                portals_details = f"Missing channel settings: {', '.join(missing_config)}"
            elif unknown_posts:
                portals_status = _status("UNKNOWN", "warn")
                portals_details = "Unable to verify some channels (missing Read Message History?)."
            elif missing_posts:
                portals_status = _status("WARN", "warn")
                portals_details = f"Missing embeds in: {', '.join(missing_posts)}"
            else:
                portals_ok = True
                portals_status = _status("OK", "ok")
                portals_details = "Portals/instructions detected."

    ready = bool(installed is True and perms_ok and channels_ok and roles_ok and portals_ok)
    ready_status = _status("READY", "ok") if ready else _status("NOT READY", "warn")
    ready_details = "This server looks ready to use." if ready else "Complete the steps below to finish setup."

    actions_disabled = bool(installed is False or not settings.mongodb_uri)

    tasks: list[dict[str, str]] = []
    tasks_error: str | None = None
    if settings.mongodb_uri:
        try:
            raw_tasks = list_ops_tasks(settings, guild_id=guild_id, limit=10)
        except Exception as exc:
            tasks_error = str(exc)
            raw_tasks = []
        for task in raw_tasks:
            created_at = task.get("created_at")
            created = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at or "")
            tasks.append(
                {
                    "created": created,
                    "action": str(task.get("action") or ""),
                    "status": str(task.get("status") or ""),
                }
            )

    steps = [
        {
            "title": "Step 1: Permissions",
            "status": perms_status,
            "details": perms_details,
            "action_label": "Open",
            "action_href": f"/guild/{guild_id}/permissions",
        },
        {
            "title": "Step 2: Channels",
            "status": channels_status,
            "details": channels_details,
            "action_label": "Review",
            "action_href": f"/guild/{guild_id}/settings",
        },
        {
            "title": "Step 3: Roles",
            "status": roles_status,
            "details": roles_details,
            "action_label": "Review",
            "action_href": f"/guild/{guild_id}/settings",
        },
        {
            "title": "Step 4: Post portals",
            "status": portals_status,
            "details": portals_details,
            "action_label": "Ops",
            "action_href": f"/guild/{guild_id}/ops",
        },
        {
            "title": "Step 5: Verify",
            "status": _status("OK", "ok") if ready else _status("PENDING", "warn"),
            "details": "Setup wizard complete." if ready else "Run setup and repost portals, then refresh.",
            "action_label": "Overview",
            "action_href": f"/guild/{guild_id}/overview",
        },
    ]

    queued = bool(request.query.get("queued", "").strip())

    content = render(
        "pages/dashboard/guild_setup_wizard.html",
        guild_id=guild_id,
        plan_label=str(plan).upper(),
        plan_class=str(plan),
        ready_status=ready_status,
        ready_details=ready_details,
        actions_disabled=actions_disabled,
        csrf_token=session.csrf_token,
        steps=steps,
        tasks=tasks,
        tasks_error=tasks_error,
        queued=queued,
    )
    return web.Response(
        text=_html_page(
            title="Setup Wizard",
            body=_app_shell(
                settings=settings,
                session=session,
                section="setup",
                selected_guild_id=guild_id,
                installed=installed,
                content=content,
            ),
        ),
        content_type="text/html",
    )


async def guild_permissions_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    from offside_bot.web_templates import render

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

    invite_href = _invite_url(settings, guild_id=str(guild_id), disable_guild_select=True)
    installed, install_error = await _detect_bot_installed(request, guild_id=guild_id)

    roles: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    metadata_error: str | None = None
    if installed is not False:
        try:
            roles, channels = await _get_guild_discord_metadata(request, guild_id=guild_id)
        except web.HTTPException as exc:
            metadata_error = exc.text or str(exc)
        except Exception as exc:
            metadata_error = str(exc)

    blocked_message: str | None = None
    if installed is False:
        blocked_message = install_error or "Bot is not installed in this server yet."
    else:
        http = request.app.get(HTTP_SESSION_KEY)
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
            blocked_message = metadata_error or install_error or "Unable to load bot membership details."

    guild_permissions: list[dict[str, str]] = []
    role_hierarchy: list[dict[str, str]] = []
    channel_access: list[dict[str, str]] = []
    top_role_name = ""
    top_role_pos = 0
    is_admin = False

    if blocked_message is None:
        roles_by_id: dict[int, dict[str, Any]] = {}
        for role_doc in roles:
            rid = _parse_int(role_doc.get("id"))
            if rid is not None:
                roles_by_id[rid] = role_doc

        member_role_ids: set[int] = {guild_id}
        member_roles_raw = bot_member.get("roles") if isinstance(bot_member, dict) else None
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
        for name, bit, why in required_guild_perms:
            ok = is_admin or bool(base_perms & bit)
            status = "OK" if ok else "Missing"
            guild_permissions.append(
                {
                    "permission": name,
                    "status": status,
                    "why": why,
                }
            )

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
            (
                "Coach Premium",
                _parse_int(cfg.get("role_coach_premium_id")) or _best_role_id_by_name("Coach Premium"),
            ),
            (
                "Coach Premium+",
                _parse_int(cfg.get("role_coach_premium_plus_id")) or _best_role_id_by_name("Coach Premium+"),
            ),
        ]

        for label, rid in coach_role_ids:
            if rid is None:
                role_hierarchy.append(
                    {
                        "role": label,
                        "status": "Not configured",
                        "details": "Run setup to create roles.",
                    }
                )
                continue
            target_role = roles_by_id.get(rid)
            if target_role is None:
                role_hierarchy.append(
                    {
                        "role": label,
                        "status": "Missing role",
                        "details": f"Role ID {rid} not found.",
                    }
                )
                continue
            role_pos = _parse_int(target_role.get("position")) or 0
            ok = top_role_pos > role_pos
            status = "OK" if ok else "Bot role too low"
            if not ok:
                details = "Move the bot's role above the Coach roles in Server Settings -> Roles."
            else:
                details = (
                    f"Bot top role: {top_role_name or 'unknown'} (pos {top_role_pos}); "
                    f"Target: {str(target_role.get('name') or rid)} (pos {role_pos})"
                )
            role_hierarchy.append(
                {
                    "role": label,
                    "status": status,
                    "details": details,
                }
            )

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
        for field, label in GUILD_CHANNEL_FIELDS:
            channel_id = _parse_int(cfg.get(field))
            if channel_id is None:
                continue
            channel = channels_by_id.get(channel_id)
            if channel is None:
                channel_access.append(
                    {
                        "channel": label,
                        "status": "Missing channel",
                        "details": f"Channel ID {channel_id} not found.",
                    }
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
            channel_access.append(
                {
                    "channel": label,
                    "status": status,
                    "details": f"#{channel_name} (ID {channel_id})",
                }
            )

    content = render(
        "pages/dashboard/guild_permissions.html",
        guild_id=guild_id,
        invite_href=invite_href,
        blocked_message=blocked_message,
        is_admin=is_admin,
        top_role_name=top_role_name,
        top_role_pos=str(top_role_pos),
        settings_href=f"/guild/{guild_id}/settings",
        guild_permissions=guild_permissions,
        role_hierarchy=role_hierarchy,
        channel_access=channel_access,
    )
    return web.Response(
        text=_html_page(
            title="Permissions",
            body=_app_shell(
                settings=settings,
                session=session,
                section="permissions",
                selected_guild_id=guild_id,
                installed=installed,
                content=content,
            ),
        ),
        content_type="text/html",
    )


async def guild_audit_page(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    request_id = _request_id(request)
    from offside_bot.web_templates import render

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

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
        logging.exception(
            "event=guild_audit_load_failed request_id=%s guild_id=%s",
            request_id,
            guild_id,
            extra=_log_extra(request, guild_id=guild_id),
        )
        raise web.HTTPInternalServerError(text="Failed to load audit events.") from exc

    rows: list[dict[str, str]] = []
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
        if not actor:
            actor = "?"

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
            {
                "created": created_text,
                "category": category,
                "action": action,
                "actor": actor,
                "source": source,
                "details": details_short,
                "details_full": details_text,
            }
        )

    content = render(
        "pages/dashboard/guild_audit.html",
        guild_id=guild_id,
        limit=limit,
        rows=rows,
        download_href=f"/guild/{guild_id}/audit.csv?limit={limit}",
    )
    return web.Response(
        text=_html_page(
            title="Audit Log",
            body=_app_shell(
                settings=settings,
                session=session,
                section="audit",
                selected_guild_id=guild_id,
                installed=installed,
                content=content,
            ),
        ),
        content_type="text/html",
    )


async def guild_audit_csv(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    request_id = _request_id(request)

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)
    plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    if plan != entitlements_service.PLAN_PRO:
        return _pro_locked_page(
            settings=settings,
            session=session,
            guild_id=guild_id,
            installed=None,
            section="audit",
            title="Audit Log Export",
            message="Audit Log export is available on the Pro plan.",
            benefits=[
                ("Audit export", "Downloadable CSV for compliance and review."),
                ("Billing & entitlements", "Keep entitlements synced across web and bot."),
                ("Priority support", "Access help for billing and operational issues."),
            ],
            upgrade_href=f"/app/upgrade?guild_id={guild_id}&from=audit_csv&section=audit",
        )

    plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    if plan != entitlements_service.PLAN_PRO:
        raise web.HTTPForbidden(text="Audit Log export is available on the Pro plan.")

    limit = _parse_int(request.query.get("limit")) or 500
    limit = max(1, min(500, limit))

    try:
        col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
        events = list_audit_events(guild_id=guild_id, limit=limit, collection=col)
    except Exception as exc:
        logging.exception(
            "event=guild_audit_load_failed request_id=%s guild_id=%s",
            request_id,
            guild_id,
            extra=_log_extra(request, guild_id=guild_id),
        )
        raise web.HTTPInternalServerError(text="Failed to load audit events.") from exc

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
    settings: Settings = request.app[SETTINGS_KEY]
    from offside_bot.web_templates import render

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)
    plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    if plan != entitlements_service.PLAN_PRO:
        return _pro_locked_page(
            settings=settings,
            session=session,
            guild_id=guild_id,
            installed=None,
            section="ops",
            title="Operations",
            message="Ops tasks (setup runs, portal reposts, data delete scheduling) are available on the Pro plan.",
            benefits=[
                ("Setup automation", "Re-run setup tasks reliably."),
                ("Portal reposts", "Regenerate staff/portal messages with one click."),
                ("Data ops", "Schedule data deletion with auditability."),
            ],
            upgrade_href=f"/app/upgrade?guild_id={guild_id}&from=ops&section=ops",
        )

    installed, install_error = await _detect_bot_installed(request, guild_id=guild_id)
    mongodb_configured = bool(settings.mongodb_uri)
    notices: list[dict[str, str]] = []
    if installed is False and install_error:
        notices.append({"title": "Install check", "text": install_error, "kind": "warn"})

    heartbeat_text = "missing"
    if mongodb_configured:
        heartbeat = get_worker_heartbeat(settings, worker="bot") or {}
        updated_at = heartbeat.get("updated_at")
        if isinstance(updated_at, datetime):
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - updated_at).total_seconds()
            heartbeat_text = f"{updated_at.isoformat()} (age={int(age)}s)"

    tasks: list[dict[str, str]] = []
    tasks_error: str | None = None
    if mongodb_configured:
        try:
            raw_tasks = list_ops_tasks(settings, guild_id=guild_id, limit=25)
        except Exception as exc:
            tasks_error = str(exc)
            raw_tasks = []
        for task in raw_tasks:
            created_at = task.get("created_at")
            created = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at or "")
            started_at = task.get("started_at")
            started = started_at.isoformat() if isinstance(started_at, datetime) else str(started_at or "")
            finished_at = task.get("finished_at")
            finished = finished_at.isoformat() if isinstance(finished_at, datetime) else str(finished_at or "")
            tasks.append(
                {
                    "created": created,
                    "action": str(task.get("action") or ""),
                    "status": str(task.get("status") or ""),
                    "requested_by": str(task.get("requested_by_username") or task.get("requested_by_discord_id") or ""),
                    "started": started,
                    "finished": finished,
                    "error": str(task.get("error") or ""),
                }
            )
    if tasks_error:
        notices.append({"title": "Tasks unavailable", "text": tasks_error, "kind": "warn"})

    grace_hours = max(0, int(GUILD_DATA_DELETE_GRACE_HOURS))
    deletion_state: dict[str, str] = {"mode": "disabled", "reason": ""}
    deletion_note: str | None = None
    if not mongodb_configured:
        deletion_state = {
            "mode": "disabled",
            "reason": "MongoDB is not configured; ops tasks cannot be queued.",
        }
    elif not settings.mongodb_per_guild_db:
        deletion_state = {
            "mode": "disabled",
            "reason": "Data deletion requires per-guild databases (set MONGODB_PER_GUILD_DB=true).",
        }
    else:
        deletion_task: dict[str, Any] | None = None
        deletion_task_error: str | None = None
        try:
            deletion_task = get_active_ops_task(
                settings, guild_id=guild_id, action=OPS_TASK_ACTION_DELETE_GUILD_DATA
            )
        except Exception as exc:
            deletion_task_error = str(exc)
            deletion_task = None

        if deletion_task_error:
            deletion_note = deletion_task_error

        if deletion_task is not None:
            status = str(deletion_task.get("status") or "").strip().lower()
            run_after = deletion_task.get("run_after")
            run_after_text = run_after.isoformat() if isinstance(run_after, datetime) else str(run_after or "")
            if status == "queued":
                deletion_state = {
                    "mode": "scheduled",
                    "run_after_text": run_after_text,
                }
            else:
                deletion_state = {
                    "mode": "active",
                    "status": status,
                }
        else:
            run_after = datetime.now(timezone.utc) + timedelta(hours=grace_hours)
            confirm_phrase = f"DELETE {guild_id}"
            deletion_state = {
                "mode": "ready",
                "run_after_text": run_after.isoformat(),
                "confirm_phrase": confirm_phrase,
                "confirm_id": f"confirm_delete_{guild_id}",
                "grace_hours": str(grace_hours),
            }

    content = render(
        "pages/dashboard/guild_ops.html",
        guild_id=guild_id,
        notices=notices,
        mongodb_configured=mongodb_configured,
        heartbeat_text=heartbeat_text,
        actions_disabled=installed is False,
        csrf_token=session.csrf_token,
        tasks=tasks,
        deletion_state=deletion_state,
        deletion_note=deletion_note,
    )
    return web.Response(
        text=_html_page(
            title="Ops",
            body=_app_shell(
                settings=settings,
                session=session,
                section="ops",
                selected_guild_id=guild_id,
                installed=installed,
                content=content,
            ),
        ),
        content_type="text/html",
    )


async def _enqueue_ops_from_dashboard(request: web.Request, *, action: str) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    if not settings.mongodb_uri:
        raise web.HTTPInternalServerError(text="MongoDB is not configured.")

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

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

    referer = request.headers.get("Referer", "").strip()
    if referer:
        parsed = urllib.parse.urlparse(referer)
        redirect_path = parsed.path
        if parsed.query:
            redirect_path = f"{redirect_path}?{parsed.query}"
        redirect_path = _sanitize_next_path(redirect_path)
        if redirect_path != "/":
            raise web.HTTPFound(redirect_path)

    raise web.HTTPFound(f"/guild/{guild_id}/overview")


async def guild_ops_run_setup(request: web.Request) -> web.Response:
    return await _enqueue_ops_from_dashboard(request, action=OPS_TASK_ACTION_RUN_SETUP)


async def guild_ops_run_full_setup(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    if not settings.mongodb_uri:
        raise web.HTTPInternalServerError(text="MongoDB is not configured.")

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

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


async def guild_ops_schedule_delete_data(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    if not settings.mongodb_uri:
        raise web.HTTPInternalServerError(text="MongoDB is not configured.")

    if not settings.mongodb_per_guild_db:
        raise web.HTTPBadRequest(text="Data deletion requires MONGODB_PER_GUILD_DB=true.")

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

    _require_pro_plan_for_ops(settings, guild_id)

    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    expected = f"DELETE {guild_id}"
    confirm = str(data.get("confirm") or "").strip()
    if confirm != expected:
        raise web.HTTPBadRequest(text=f"Confirmation mismatch. Type: {expected}")

    actor_id = _parse_int(session.user.get("id"))
    actor_username = f"{session.user.get('username','')}#{session.user.get('discriminator','')}".strip("#")

    grace_hours = max(0, int(GUILD_DATA_DELETE_GRACE_HOURS))
    run_after = datetime.now(timezone.utc) + timedelta(hours=grace_hours)

    task = enqueue_ops_task(
        settings,
        guild_id=guild_id,
        action=OPS_TASK_ACTION_DELETE_GUILD_DATA,
        requested_by_discord_id=actor_id,
        requested_by_username=actor_username or None,
        source="dashboard",
        run_after=run_after,
    )

    try:
        audit_col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
        record_audit_event(
            guild_id=guild_id,
            category="ops",
            action="guild_data_deletion.scheduled",
            source="dashboard",
            actor_discord_id=actor_id,
            actor_display_name=str(session.user.get("username") or "") or None,
            actor_username=actor_username or None,
            details={
                "task_id": str(task.get("_id") or ""),
                "run_after": run_after.isoformat(),
                "grace_hours": grace_hours,
            },
            collection=audit_col,
        )
    except Exception:
        pass

    raise web.HTTPFound(f"/guild/{guild_id}/ops")


async def guild_ops_cancel_delete_data(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    if not settings.mongodb_uri:
        raise web.HTTPInternalServerError(text="MongoDB is not configured.")

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)

    _require_pro_plan_for_ops(settings, guild_id)

    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    canceled = cancel_ops_task(settings, guild_id=guild_id, action=OPS_TASK_ACTION_DELETE_GUILD_DATA)

    actor_id = _parse_int(session.user.get("id"))
    actor_username = f"{session.user.get('username','')}#{session.user.get('discriminator','')}".strip("#")

    try:
        audit_col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
        record_audit_event(
            guild_id=guild_id,
            category="ops",
            action="guild_data_deletion.canceled",
            source="dashboard",
            actor_discord_id=actor_id,
            actor_display_name=str(session.user.get("username") or "") or None,
            actor_username=actor_username or None,
            details={"canceled": canceled},
            collection=audit_col,
        )
    except Exception:
        pass

    raise web.HTTPFound(f"/guild/{guild_id}/ops")


async def guild_analytics_json(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]

    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)
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
    settings: Settings = request.app[SETTINGS_KEY]
    guild_id_str = request.match_info["guild_id"]
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=guild_id_str)
    roles, channels = await _get_guild_discord_metadata(request, guild_id=guild_id)
    return web.json_response({"guild_id": guild_id, "roles": roles, "channels": channels})


async def billing_webhook(request: web.Request) -> web.Response:
    settings: Settings = request.app[SETTINGS_KEY]
    request_id = _request_id(request)
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
        logging.warning(
            "event=stripe_webhook_validation_failed request_id=%s",
            request_id,
            extra=_log_extra(request),
        )
        raise web.HTTPBadRequest(text="Invalid webhook request.") from exc
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
    settings: Settings = request.app[SETTINGS_KEY]
    from offside_bot.web_templates import render

    selected_guild_id = request.query.get("guild_id", "").strip()
    if selected_guild_id:
        guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=selected_guild_id)
    elif session.owner_guilds:
        guild_id = _require_owned_guild(
            session,
            settings=settings,
            path=request.path_qs,
            guild_id=str(session.owner_guilds[0].get("id") or ""),
        )
    else:
        guild_id = 0

    if not guild_id:
        content = render(
            "pages/dashboard/billing.html",
            has_guild=False,
        )
        return web.Response(
            text=_html_page(
                title="Billing",
                body=_app_shell(
                    settings=settings,
                    session=session,
                    section="billing",
                    selected_guild_id=None,
                    installed=None,
                    content=content,
                ),
            ),
            content_type="text/html",
        )

    installed, _install_error = await _detect_bot_installed(request, guild_id=guild_id)
    current_plan = entitlements_service.get_guild_plan(settings, guild_id=guild_id)
    subscription = get_guild_subscription(settings, guild_id=guild_id) if settings.mongodb_uri else None
    customer_id = str(subscription.get("customer_id") or "") if subscription else ""
    guild_options = [
        {
            "value": str(g.get("id") or ""),
            "label": str(g.get("name") or g.get("id") or ""),
            "selected": str(g.get("id")) == str(guild_id),
        }
        for g in session.owner_guilds
        if isinstance(g, dict)
    ]

    status = request.query.get("status", "").strip()
    status_message = ""
    if status == "cancelled":
        status_message = "Checkout cancelled."
    elif status == "success":
        if current_plan == entitlements_service.PLAN_PRO:
            status_message = "Checkout complete. Pro is enabled."
        else:
            status_message = "Checkout complete. Activation may take a few seconds."

    upgrade_disabled = current_plan == entitlements_service.PLAN_PRO
    upgrade_text = "Already Pro" if upgrade_disabled else "Upgrade to Pro"

    content = render(
        "pages/dashboard/billing.html",
        has_guild=True,
        guild_id=guild_id,
        status_message=status_message,
        current_plan_label=str(current_plan).upper(),
        current_plan_class=str(current_plan),
        manage_portal=bool(customer_id),
        guild_options=guild_options,
        upgrade_disabled=upgrade_disabled,
        upgrade_text=upgrade_text,
        csrf_token=session.csrf_token,
    )
    return web.Response(
        text=_html_page(
            title="Billing",
            body=_app_shell(
                settings=settings,
                session=session,
                section="billing",
                selected_guild_id=guild_id,
                installed=installed,
                content=content,
            ),
        ),
        content_type="text/html",
    )


async def billing_portal(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    if not settings.mongodb_uri:
        raise web.HTTPInternalServerError(text="MongoDB is not configured.")

    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=str(data.get("guild_id") or ""))

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
    redirect_url = str(url)
    parsed = urllib.parse.urlsplit(redirect_url)
    redirect_host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or redirect_host not in {"billing.stripe.com"}:
        logging.error("event=stripe_portal_redirect_invalid", extra=_log_extra(request))
        raise web.HTTPInternalServerError(text="Stripe did not return a valid billing portal URL.")
    raise web.HTTPFound(redirect_url)


async def billing_checkout(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    data = await request.post()
    if str(data.get("csrf", "")) != session.csrf_token:
        raise web.HTTPBadRequest(text="Invalid CSRF token.")

    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=str(data.get("guild_id") or ""))
    _require_guild_owner(session, guild_id=guild_id, settings=settings, path=request.path_qs)
    plan = str(data.get("plan") or "pro").strip().lower()
    if plan != entitlements_service.PLAN_PRO:
        raise web.HTTPBadRequest(text="Unsupported plan.")

    existing = get_guild_subscription(settings, guild_id=guild_id)
    existing_status = str(existing.get("status") or "").strip().lower() if isinstance(existing, dict) else ""
    active_like_statuses = {"active", "trialing", "past_due", "incomplete"}
    if existing_status in active_like_statuses:
        raise web.HTTPBadRequest(text="This guild already has an active or pending subscription; manage via billing.")

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
    redirect_url = str(url)
    parsed = urllib.parse.urlsplit(redirect_url)
    redirect_host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or redirect_host not in {"checkout.stripe.com"}:
        logging.error("event=stripe_checkout_redirect_invalid", extra=_log_extra(request))
        raise web.HTTPInternalServerError(text="Stripe did not return a valid checkout URL.")
    raise web.HTTPFound(redirect_url)


async def billing_success(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    from offside_bot.web_templates import render

    gid = request.query.get("guild_id", "").strip()
    checkout_session_id = request.query.get("session_id", "").strip()
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=gid) if gid else 0
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
    content = render(
        "pages/dashboard/billing_success.html",
        guild_id=guild_id,
        message=message,
        plan_label=str(plan).upper(),
        plan_class=str(plan),
        billing_href=f"/app/billing?guild_id={guild_id}",
        analytics_href=f"/guild/{guild_id}",
        settings_href=f"/guild/{guild_id}/settings",
    )
    return web.Response(text=_html_page(title="Checkout Success", body=content), content_type="text/html")


async def billing_cancel(request: web.Request) -> web.Response:
    session = _require_session(request)
    settings: Settings = request.app[SETTINGS_KEY]
    gid = request.query.get("guild_id", "").strip()
    guild_id = _require_owned_guild(session, settings=settings, path=request.path_qs, guild_id=gid) if gid else 0
    if not guild_id:
        raise web.HTTPBadRequest(text="Missing guild_id.")
    _require_guild_owner(session, guild_id=guild_id, settings=settings, path=request.path_qs)
    raise web.HTTPFound(f"/app/billing?guild_id={guild_id}&status=cancelled")


async def _on_startup(app: web.Application) -> None:
    # aiohttp ClientSession must be created with a running event loop.
    app[HTTP_SESSION_KEY] = ClientSession()


async def _on_cleanup(app: web.Application) -> None:
    http = app.get("http")
    if isinstance(http, ClientSession):
        await http.close()


def create_app(*, settings: Settings | None = None) -> web.Application:
    app = web.Application(
        client_max_size=max(1, int(MAX_REQUEST_BYTES)),
        middlewares=[
            request_id_middleware,
            request_metrics_middleware,
            security_headers_middleware,
            rate_limit_middleware,
            timeout_middleware,
            session_middleware,
        ]
    )
    app_settings = settings or load_settings()
    app[SETTINGS_KEY] = app_settings
    validate_stripe_environment()
    init_error_reporting(settings=app_settings, service_name="dashboard")
    session_collection, state_collection, user_collection = _ensure_dashboard_collections(app_settings)
    app[SESSION_COLLECTION_KEY] = session_collection
    app[STATE_COLLECTION_KEY] = state_collection
    app[USER_COLLECTION_KEY] = user_collection
    if app_settings.mongodb_uri:
        ensure_stripe_webhook_indexes(app_settings)
        ensure_ops_task_indexes(app_settings)
        ensure_guild_install_indexes(app_settings)
    app[GUILD_METADATA_CACHE_KEY] = {}
    app[HTTP_SESSION_KEY] = None
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
    app.router.add_get("/healthz", health)
    app.router.add_get("/ready", ready)
    app.router.add_get("/", index)
    app.router.add_get("/app", app_index)
    app.router.add_get("/features", features_page)
    app.router.add_get("/pricing", pricing_page)
    app.router.add_get("/enterprise", enterprise_page)
    app.router.add_get("/terms", terms_page)
    app.router.add_get("/privacy", privacy_page)
    app.router.add_get("/product", product_copy_page)
    app.router.add_get("/support", support_page)
    app.router.add_get("/admin", admin_dashboard)
    app.router.add_post("/admin/stripe/resync", admin_stripe_resync)
    app.router.add_get("/docs", docs_index_page)
    app.router.add_get("/docs/{slug}", docs_page)
    app.router.add_get("/commands", commands_page)
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
    app.router.add_post(
        "/api/guild/{guild_id}/ops/schedule_delete_data",
        guild_ops_schedule_delete_data,
    )
    app.router.add_post(
        "/api/guild/{guild_id}/ops/cancel_delete_data",
        guild_ops_cancel_delete_data,
    )
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
