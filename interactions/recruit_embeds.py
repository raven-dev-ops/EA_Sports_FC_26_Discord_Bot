from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import discord

from utils.availability import Availability, format_days, next_availability_start
from utils.embeds import DEFAULT_COLOR, apply_embed_footer, make_embed


def build_recruit_profile_embed(
    profile: dict[str, Any],
    *,
    fc25_link: dict[str, Any] | None = None,
    fc25_snapshot: dict[str, Any] | None = None,
) -> discord.Embed:
    display_name = profile.get("display_name") or profile.get("user_tag") or str(profile.get("user_id", "Unknown"))
    embed = make_embed(
        title=f"Free Agent Profile: {display_name}",
        description=f"User ID: `{profile.get('user_id', 'unknown')}`",
        color=DEFAULT_COLOR,
    )

    if profile.get("age"):
        embed.add_field(name="🎂 Age", value=str(profile["age"]), inline=True)
    if profile.get("platform"):
        embed.add_field(name="🎮 Platform", value=str(profile["platform"]), inline=True)
    if "mic" in profile:
        embed.add_field(name="🎙️ Mic", value="Yes" if profile.get("mic") else "No", inline=True)

    main_position = profile.get("main_position") or "-"
    main_archetype = _format_label(profile.get("main_archetype")) or "-"
    secondary_position = profile.get("secondary_position") or "-"
    secondary_archetype = _format_label(profile.get("secondary_archetype")) or "-"
    positions_value = (
        f"Main: **{main_position}** ({main_archetype})\n"
        f"Secondary: **{secondary_position}** ({secondary_archetype})"
    )
    embed.add_field(name="📌 Positions", value=positions_value, inline=False)

    if profile.get("server_name"):
        embed.add_field(name="📍 Server", value=str(profile["server_name"]), inline=True)
    if profile.get("timezone"):
        embed.add_field(name="🧭 Timezone", value=str(profile["timezone"]), inline=True)

    notes = profile.get("notes")
    if notes:
        _add_long_field(embed, name="📝 Notes", value=str(notes), max_fields=2)

    availability_days = profile.get("availability_days")
    availability_start_hour = profile.get("availability_start_hour")
    availability_end_hour = profile.get("availability_end_hour")
    availability_tz = profile.get("timezone")

    if (
        availability_days
        and availability_start_hour is not None
        and availability_end_hour is not None
        and availability_tz
    ):
        tz_name = str(availability_tz or "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        try:
            availability = Availability(
                days=list(availability_days or []),
                start_hour=int(availability_start_hour),
                end_hour=int(availability_end_hour),
            )
            next_start = next_availability_start(availability, tz=tz)
        except Exception:
            next_start = None
            availability = None

        if availability is not None:
            embed.add_field(
                name="🗓️ Availability",
                value=f"{format_days(availability.days)} - {availability.start_hour:02d}:00-{availability.end_hour:02d}:00",
                inline=False,
            )
        if next_start is not None:
            embed.add_field(
                name="⏰ Next start (viewer-local)",
                value=f"{discord.utils.format_dt(next_start, style='F')} ({discord.utils.format_dt(next_start, style='R')})",
                inline=False,
            )

    if fc25_link:
        verified = bool(fc25_link.get("verified"))
        club_name = fc25_link.get("club_name") or str(fc25_link.get("club_id") or "Unknown club")
        member_name = fc25_link.get("member_name") or "Unknown member"
        status = "Verified" if verified else "Pending verification"
        lines = [f"Status: {status}", f"Club: {club_name}", f"Member: {member_name}"]

        member_stats = None
        if fc25_snapshot and isinstance(fc25_snapshot.get("snapshot"), dict):
            snap = fc25_snapshot.get("snapshot") or {}
            if isinstance(snap.get("member_stats"), dict):
                member_stats = snap.get("member_stats")
        if verified and member_stats:
            totals = _format_fc25_totals(member_stats)
            if totals:
                lines.append(totals)

        fetched_at = None
        if fc25_snapshot and isinstance(fc25_snapshot.get("fetched_at"), datetime):
            fetched_at = fc25_snapshot.get("fetched_at")
        elif isinstance(fc25_link.get("last_fetched_at"), datetime):
            fetched_at = fc25_link.get("last_fetched_at")
        if fetched_at is not None:
            lines.append(f"Last updated: {discord.utils.format_dt(fetched_at, style='R')}")

        embed.add_field(
            name="📊 Verified Stats (FC25 Clubs, unofficial)",
            value="\n".join(lines)[:1024],
            inline=False,
        )

    updated_at = profile.get("updated_at") or profile.get("created_at")
    if isinstance(updated_at, datetime):
        apply_embed_footer(
            embed,
            (
                f"Updated: {discord.utils.format_dt(updated_at, style='R')} | "
                "Long text may be truncated"
            ),
        )

    return embed


def _add_long_field(
    embed: discord.Embed,
    *,
    name: str,
    value: str,
    inline: bool = False,
    max_fields: int = 2,
) -> None:
    remaining = value.strip()
    if not remaining:
        return
    fields_added = 0
    while remaining and fields_added < max_fields:
        chunk, remaining = _split_chunk(remaining, max_len=1024)
        heading = name if fields_added == 0 else f"{name} (cont.)"
        if remaining and fields_added == max_fields - 1 and len(chunk) >= 4:
            chunk = chunk[:1020].rstrip() + "..."
            remaining = ""
        embed.add_field(name=heading, value=chunk, inline=inline)
        fields_added += 1


def _split_chunk(text: str, *, max_len: int) -> tuple[str, str]:
    if len(text) <= max_len:
        return text, ""
    cutoff = max(text.rfind("\n", 0, max_len), text.rfind(" ", 0, max_len))
    if cutoff < int(max_len * 0.6):
        cutoff = max_len
    chunk = text[:cutoff].rstrip()
    rest = text[cutoff:].lstrip()
    return chunk, rest


def _format_label(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.title()


def _format_fc25_totals(member_stats: dict[str, Any]) -> str | None:
    matches = _first_int(member_stats, ("gamesPlayed", "matchesPlayed", "games"))
    goals = _first_int(member_stats, ("goals",))
    assists = _first_int(member_stats, ("assists",))
    clean_sheets = _first_int(member_stats, ("cleanSheets", "clean_sheets", "cleanSheet"))
    rating = _first_float(member_stats, ("ratingAve", "averageRating", "avgRating", "rating"))

    parts: list[str] = []
    if matches is not None:
        parts.append(f"Matches: {matches}")
    if goals is not None:
        parts.append(f"Goals: {goals}")
    if assists is not None:
        parts.append(f"Assists: {assists}")
    if clean_sheets is not None:
        parts.append(f"Clean sheets: {clean_sheets}")
    if rating is not None:
        parts.append(f"Rating: {rating:.2f}".rstrip("0").rstrip("."))

    if not parts:
        return None
    return " | ".join(parts)[:1024]


def _first_int(member_stats: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key not in member_stats:
            continue
        value = member_stats.get(key)
        parsed = _coerce_int(value)
        if parsed is not None:
            return parsed
    return None


def _first_float(member_stats: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key not in member_stats:
            continue
        value = member_stats.get(key)
        parsed = _coerce_float(value)
        if parsed is not None:
            return parsed
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return int(float(cleaned))
        except ValueError:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
