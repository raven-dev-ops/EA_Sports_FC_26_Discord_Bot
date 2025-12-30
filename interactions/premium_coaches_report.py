from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from config import Settings
from database import get_collection
from repositories.tournament_repo import ensure_active_cycle
from services.guild_config_service import get_guild_config, set_guild_config
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import edit_message, fetch_channel, send_message

PREMIUM_CAPS = {22, 25}
PREMIUM_MESSAGE_ID_KEY = "premium_coaches_message_id"


def _build_embed(*, cycle_name: str, listings: list[str]) -> discord.Embed:
    embed = discord.Embed(
        title="Premium Coaches",
        description=(
            "Premium coach rosters for the current tournament cycle.\n"
            "Listings update automatically when premium rosters change."
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name="Cycle", value=cycle_name, inline=False)

    if not listings:
        embed.add_field(
            name="Listings",
            value="No premium rosters found yet.",
            inline=False,
        )
        return embed

    chunks = _chunk_lines(listings, max_len=1024)
    for idx, chunk in enumerate(chunks):
        embed.add_field(
            name="Listings" if idx == 0 else "Listings (cont.)",
            value=chunk,
            inline=False,
        )
        if idx >= 23:
            break
    embed.set_footer(text="Coach Premium = 22 cap • Coach Premium+ = 25 cap")
    return embed


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


def _build_listings(collection, *, cycle_id: Any) -> list[str]:
    rosters = list(
        collection.find(
            {
                "record_type": "team_roster",
                "cycle_id": cycle_id,
                "cap": {"$in": sorted(PREMIUM_CAPS)},
            }
        )
    )
    if not rosters:
        return []

    roster_ids = [r.get("_id") for r in rosters if r.get("_id") is not None]
    counts: dict[Any, int] = {}
    if roster_ids:
        try:
            pipeline = [
                {"$match": {"record_type": "roster_player", "roster_id": {"$in": roster_ids}}},
                {"$group": {"_id": "$roster_id", "count": {"$sum": 1}}},
            ]
            for doc in collection.aggregate(pipeline):
                counts[doc.get("_id")] = int(doc.get("count") or 0)
        except Exception:
            counts = {}

    rows: list[tuple[int, str]] = []
    for roster in rosters:
        cap_raw = roster.get("cap")
        cap = int(cap_raw) if isinstance(cap_raw, int) else 0
        coach_id_raw = roster.get("coach_discord_id")
        coach_id = int(coach_id_raw) if isinstance(coach_id_raw, int) else None
        if coach_id is None:
            continue
        count = counts.get(roster.get("_id"), 0)
        openings = max(0, cap - count) if cap > 0 else 0
        rows.append((openings, _format_listing(roster, count=count, openings=openings)))

    rows.sort(key=lambda item: (item[0], item[1].casefold()), reverse=True)
    return [line for _, line in rows]


def _format_listing(roster: dict[str, Any], *, count: int, openings: int) -> str:
    coach_id = roster.get("coach_discord_id")
    team_name = str(roster.get("team_name") or "Unnamed Team").strip() or "Unnamed Team"
    cap_raw = roster.get("cap")
    cap = int(cap_raw) if isinstance(cap_raw, int) else 0
    practice = str(roster.get("practice_times") or "").strip() or "Not set"
    tier = "Premium+" if cap >= 25 else "Premium"
    return (
        f"<@{coach_id}> — **{team_name}** — {tier} — "
        f"Openings: {openings} ({count}/{cap}) — Practice: {practice}"
    )


async def upsert_premium_coaches_report(
    client: discord.Client,
    *,
    settings: Settings,
    guild_id: int,
    test_mode: bool,
) -> None:
    channel_id = resolve_channel_id(
        settings,
        guild_id=guild_id,
        field="channel_premium_coaches_id",
        test_mode=test_mode,
    )
    if not channel_id:
        return

    try:
        collection = get_collection(settings)
    except Exception:
        return

    try:
        cycle = ensure_active_cycle(collection=collection)
    except Exception:
        return

    listings = _build_listings(collection, cycle_id=cycle["_id"])
    embed = _build_embed(cycle_name=str(cycle.get("name") or "Current Tournament"), listings=listings)

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

    msg = None
    if message_id and hasattr(channel, "fetch_message"):
        try:
            msg = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
        except discord.DiscordException:
            msg = None

    if msg is not None:
        edited = await edit_message(msg, embed=embed, view=None)
        if edited is not None:
            return

    sent = await send_message(channel, embed=embed, allowed_mentions=discord.AllowedMentions.none())
    if sent is None:
        return
    cfg[PREMIUM_MESSAGE_ID_KEY] = sent.id
    try:
        set_guild_config(guild_id, cfg)
    except Exception:
        logging.debug("Failed to persist premium coaches message id (guild=%s).", guild_id)


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
            logging.exception("Failed to upsert premium coaches report (guild=%s).", guild.id)
