from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import discord
from discord.ext import commands

from config import Settings
from database import get_collection
from repositories.tournament_repo import ensure_active_cycle
from services import entitlements_service
from services.guild_config_service import get_guild_config, set_guild_config
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import edit_message, fetch_channel, send_message

PREMIUM_CAPS = {22, 25}

PREMIUM_MESSAGE_ID_KEY = "premium_coaches_message_id"
PREMIUM_PIN_ENABLED_KEY = "premium_coaches_pin_enabled"
PREMIUM_PINNED_MESSAGE_ID_KEY = "premium_coaches_pinned_message_id"
PRO_COACHES_TITLE = "Pro Coaches"
LEGACY_PREMIUM_COACHES_TITLE = "Premium Coaches"


def _build_embed(
    *,
    cycle_name: str,
    premium_listings: list[str],
    premium_plus_listings: list[str],
    updated_at: datetime,
) -> discord.Embed:
    embed = discord.Embed(
        title=PRO_COACHES_TITLE,
        description=(
            "Pro coach rosters for the current tournament cycle.\n"
            "Listings update automatically when pro rosters change."
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name="Cycle", value=cycle_name, inline=False)

    if not premium_listings and not premium_plus_listings:
        embed.add_field(
            name="Listings",
            value="No pro rosters found yet.",
            inline=False,
        )
        embed.set_footer(text=f"Last updated: {discord.utils.format_dt(updated_at, style='R')}")
        return embed

    if premium_plus_listings:
        _add_listing_fields(embed, heading="Legacy Pro+ (25 cap)", listings=premium_plus_listings)
    _add_listing_fields(embed, heading="Club Manager (22 cap)", listings=premium_listings)
    footer = f"Last updated: {discord.utils.format_dt(updated_at, style='R')} | Club Manager=22"
    if premium_plus_listings:
        footer = f"{footer} | Legacy Pro+=25"
    embed.set_footer(text=footer)
    return embed


def _add_listing_fields(embed: discord.Embed, *, heading: str, listings: list[str]) -> None:
    if not listings:
        embed.add_field(name=heading, value="None", inline=False)
        return

    chunks = _chunk_lines(listings, max_len=1024)
    for idx, chunk in enumerate(chunks):
        if len(embed.fields) >= 25:
            return
        embed.add_field(
            name=heading if idx == 0 else f"{heading} (cont.)",
            value=chunk,
            inline=False,
        )


def _chunk_lines(lines: list[str], *, max_len: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for line in lines:
        line_len = len(line) + (1 if current else 0)
        if current and length + line_len > max_len:
            chunks.append("\n".join(current))
            current = []
            length = 0
        if len(line) > max_len:
            chunks.append(line[: max_len - 3] + "...")
            continue
        current.append(line)
        length += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
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


def _build_listings(
    roster_collection,
    *,
    cycle_id: Any,
    roster_players_collection=None,
) -> tuple[list[str], list[str]]:
    players_collection = roster_players_collection or roster_collection
    rosters = list(
        roster_collection.find(
            {
                "record_type": "team_roster",
                "cycle_id": cycle_id,
                "cap": {"$in": sorted(PREMIUM_CAPS)},
            }
        )
    )
    if not rosters:
        return [], []

    roster_ids = [r.get("_id") for r in rosters if r.get("_id") is not None]
    counts: dict[Any, int] = {}
    if roster_ids:
        try:
            pipeline = [
                {"$match": {"record_type": "roster_player", "roster_id": {"$in": roster_ids}}},
                {"$group": {"_id": "$roster_id", "count": {"$sum": 1}}},
            ]
            for doc in players_collection.aggregate(pipeline):
                counts[doc.get("_id")] = int(doc.get("count") or 0)
        except Exception:
            counts = {}

    premium: list[tuple[int, str]] = []
    premium_plus: list[tuple[int, str]] = []
    for roster in rosters:
        cap_raw = roster.get("cap")
        cap = int(cap_raw) if isinstance(cap_raw, int) else 0
        coach_id_raw = roster.get("coach_discord_id")
        coach_id = int(coach_id_raw) if isinstance(coach_id_raw, int) else None
        if coach_id is None:
            continue
        count = counts.get(roster.get("_id"), 0)
        openings = max(0, cap - count) if cap > 0 else 0
        line = _format_listing(roster, count=count, openings=openings)
        if cap >= 25:
            premium_plus.append((openings, line))
        else:
            premium.append((openings, line))

    premium.sort(key=lambda item: (item[0], item[1].casefold()), reverse=True)
    premium_plus.sort(key=lambda item: (item[0], item[1].casefold()), reverse=True)
    return [line for _, line in premium], [line for _, line in premium_plus]


def _format_listing(roster: dict[str, Any], *, count: int, openings: int) -> str:
    coach_id = roster.get("coach_discord_id")
    coach = f"<@{coach_id}>" if isinstance(coach_id, int) else "Unknown coach"
    team_name = str(roster.get("team_name") or "Unnamed Team").strip() or "Unnamed Team"
    cap_raw = roster.get("cap")
    cap = int(cap_raw) if isinstance(cap_raw, int) else 0
    practice = str(roster.get("practice_times") or "").strip() or "Not set"
    tier = "Legacy Pro+" if cap >= 25 else "Club Manager"
    return (
        f"{coach} - **{team_name}** - {tier} - "
        f"Openings: {openings} ({count}/{cap}) - Practice: {practice}"
    )


async def force_rebuild_premium_coaches_report(
    client: discord.Client,
    *,
    settings: Settings,
    guild_id: int,
    test_mode: bool,
    cleanup_limit: int = 50,
) -> int:
    try:
        entitlements_service.require_feature(
            settings,
            guild_id=guild_id,
            feature_key=entitlements_service.FEATURE_PREMIUM_COACHES_REPORT,
        )
    except PermissionError:
        return 0
    channel_id = resolve_channel_id(
        settings,
        guild_id=guild_id,
        field="channel_premium_coaches_id",
        test_mode=test_mode,
    )
    if not channel_id:
        return 0

    channel = await fetch_channel(client, channel_id)
    if channel is None:
        return 0

    deleted = 0
    bot_user = getattr(client, "user", None)
    if bot_user and hasattr(channel, "history"):
        try:
            async for message in channel.history(limit=int(cleanup_limit)):  # type: ignore[attr-defined]
                if message.author.id != bot_user.id:
                    continue
                if not message.embeds:
                    continue
                if message.embeds[0].title not in {PRO_COACHES_TITLE, LEGACY_PREMIUM_COACHES_TITLE}:
                    continue
                try:
                    await message.delete()
                    deleted += 1
                except discord.DiscordException:
                    continue
        except discord.DiscordException:
            pass

    if not test_mode:
        try:
            cfg = get_guild_config(guild_id)
        except Exception:
            cfg = {}
        cfg.pop(PREMIUM_MESSAGE_ID_KEY, None)
        cfg.pop(PREMIUM_PINNED_MESSAGE_ID_KEY, None)
        try:
            set_guild_config(guild_id, cfg, source="premium_coaches_report")
        except Exception:
                    logging.debug("Failed to clear pro coaches message ids (guild=%s).", guild_id)

    await upsert_premium_coaches_report(
        client,
        settings=settings,
        guild_id=guild_id,
        test_mode=test_mode,
    )
    return deleted


async def upsert_premium_coaches_report(
    client: discord.Client,
    *,
    settings: Settings,
    guild_id: int,
    test_mode: bool,
) -> None:
    try:
        entitlements_service.require_feature(
            settings,
            guild_id=guild_id,
            feature_key=entitlements_service.FEATURE_PREMIUM_COACHES_REPORT,
        )
    except PermissionError:
        return
    channel_id = resolve_channel_id(
        settings,
        guild_id=guild_id,
        field="channel_premium_coaches_id",
        test_mode=test_mode,
    )
    if not channel_id:
        return

    try:
        cycle_collection = get_collection(settings, record_type="tournament_cycle", guild_id=guild_id)
        team_rosters = get_collection(settings, record_type="team_roster", guild_id=guild_id)
        roster_players = get_collection(settings, record_type="roster_player", guild_id=guild_id)
    except Exception:
        return

    try:
        cycle = ensure_active_cycle(collection=cycle_collection)
    except Exception:
        return

    premium_listings, premium_plus_listings = _build_listings(
        team_rosters,
        roster_players_collection=roster_players,
        cycle_id=cycle["_id"],
    )
    embed = _build_embed(
        cycle_name=str(cycle.get("name") or "Current Tournament"),
        premium_listings=premium_listings,
        premium_plus_listings=premium_plus_listings,
        updated_at=datetime.now(timezone.utc),
    )

    channel = await fetch_channel(client, channel_id)
    if channel is None:
        return

    if test_mode:
        await send_message(channel, embed=embed, allowed_mentions=discord.AllowedMentions.none())
        return

    cfg: dict[str, Any]
    try:
        cfg = get_guild_config(guild_id)
    except Exception:
        cfg = {}

    message_id = _parse_int(cfg.get(PREMIUM_MESSAGE_ID_KEY))
    pin_enabled = _parse_bool(cfg.get(PREMIUM_PIN_ENABLED_KEY))
    pinned_message_id = _parse_int(cfg.get(PREMIUM_PINNED_MESSAGE_ID_KEY))

    msg = None
    if message_id and hasattr(channel, "fetch_message"):
        try:
            msg = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
        except discord.DiscordException:
            msg = None

    if msg is not None:
        edited = await edit_message(msg, embed=embed, view=None)
        if edited is not None:
            updated = await _apply_pin_settings(
                channel,
                msg,
                guild_id=guild_id,
                pin_enabled=pin_enabled,
                pinned_message_id=pinned_message_id,
                cfg=cfg,
            )
            if updated:
                try:
                    set_guild_config(guild_id, cfg, source="premium_coaches_report")
                except Exception:
                    logging.debug(
                        "Failed to persist pro coaches pin settings (guild=%s).", guild_id
                    )
            return

    sent = await send_message(channel, embed=embed, allowed_mentions=discord.AllowedMentions.none())
    if sent is None:
        return
    cfg[PREMIUM_MESSAGE_ID_KEY] = sent.id
    await _apply_pin_settings(
        channel,
        sent,
        guild_id=guild_id,
        pin_enabled=pin_enabled,
        pinned_message_id=pinned_message_id,
        cfg=cfg,
    )
    try:
        set_guild_config(guild_id, cfg, source="premium_coaches_report")
    except Exception:
        logging.debug("Failed to persist pro coaches config (guild=%s).", guild_id)


async def _apply_pin_settings(
    channel: discord.abc.Messageable,
    message: discord.Message,
    *,
    guild_id: int,
    pin_enabled: bool,
    pinned_message_id: int | None,
    cfg: dict[str, Any],
) -> bool:
    if not hasattr(message, "pin") or not hasattr(message, "unpin"):
        return False
    if not hasattr(channel, "fetch_message"):
        return False

    changed = False
    if pin_enabled:
        if pinned_message_id and pinned_message_id != message.id:
            try:
                old = await channel.fetch_message(pinned_message_id)  # type: ignore[attr-defined]
            except discord.DiscordException:
                old = None
            if old is not None and getattr(old, "pinned", False):
                try:
                    await old.unpin(reason="Offside: pro coaches repin")  # type: ignore[attr-defined]
                except discord.DiscordException:
                    pass
        try:
            if not getattr(message, "pinned", False):
                await message.pin(reason="Offside: pro coaches")  # type: ignore[attr-defined]
            if cfg.get(PREMIUM_PINNED_MESSAGE_ID_KEY) != message.id:
                cfg[PREMIUM_PINNED_MESSAGE_ID_KEY] = message.id
                changed = True
        except discord.Forbidden:
            logging.info("Missing permission to pin pro coaches message (guild=%s).", guild_id)
        except discord.DiscordException:
            pass
        return changed

    if pinned_message_id:
        try:
            old = await channel.fetch_message(pinned_message_id)  # type: ignore[attr-defined]
        except discord.DiscordException:
            old = None
        if old is not None and getattr(old, "pinned", False):
            try:
                await old.unpin(reason="Offside: pro coaches unpin")  # type: ignore[attr-defined]
            except discord.DiscordException:
                pass
        if PREMIUM_PINNED_MESSAGE_ID_KEY in cfg:
            cfg.pop(PREMIUM_PINNED_MESSAGE_ID_KEY, None)
            changed = True
    return changed


async def post_premium_coaches_report(
    bot: commands.Bot | commands.AutoShardedBot,
    *,
    guilds: list[discord.Guild] | None = None,
) -> None:
    settings = getattr(bot, "settings", None)
    if settings is None:
        return

    test_mode = bool(getattr(bot, "test_mode", False))
    target_guilds = bot.guilds if guilds is None else guilds
    for guild in target_guilds:
        try:
            await upsert_premium_coaches_report(
                bot,
                settings=settings,
                guild_id=guild.id,
                test_mode=test_mode,
            )
        except Exception:
            logging.exception("Failed to upsert pro coaches report (guild=%s).", guild.id)
