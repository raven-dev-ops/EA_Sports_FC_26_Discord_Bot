from __future__ import annotations

from datetime import datetime
from typing import Any

import discord

from utils.embeds import DEFAULT_COLOR, make_embed


def build_club_ad_embed(ad: dict[str, Any]) -> discord.Embed:
    club_name = ad.get("club_name") or "Unnamed Club"
    embed = make_embed(
        title=f"Club Ad: {club_name}",
        description=f"Owner ID: `{ad.get('owner_id', 'unknown')}`",
        color=DEFAULT_COLOR,
    )

    if ad.get("region"):
        embed.add_field(name="📍 Region", value=str(ad["region"]), inline=True)
    if ad.get("timezone"):
        embed.add_field(name="🧭 Timezone", value=str(ad["timezone"]), inline=True)
    if ad.get("formation"):
        embed.add_field(name="🧩 Formation", value=str(ad["formation"]), inline=True)

    positions = ad.get("positions_needed") or []
    if isinstance(positions, list) and positions:
        lines = [f"- {p}" for p in positions if str(p).strip()]
        embed.add_field(
            name="👥 Positions needed",
            value="\n".join(lines)[:1024],
            inline=False,
        )

    keywords = ad.get("keywords") or []
    if isinstance(keywords, list) and keywords:
        embed.add_field(
            name="🏷️ Keywords",
            value=", ".join(str(k) for k in keywords)[:1024],
            inline=False,
        )

    description = ad.get("description")
    if description:
        _add_long_field(
            embed,
            name="📝 What we're looking for",
            value=str(description),
            max_fields=2,
        )

    tryout_at = ad.get("tryout_at")
    if isinstance(tryout_at, datetime):
        embed.add_field(
            name="⏰ Tryout time (viewer-local)",
            value=f"{discord.utils.format_dt(tryout_at, style='F')} ({discord.utils.format_dt(tryout_at, style='R')})",
            inline=False,
        )

    contact = ad.get("contact")
    if contact:
        _add_long_field(embed, name="📨 Contact", value=str(contact), max_fields=1)

    updated_at = ad.get("updated_at") or ad.get("created_at")
    if isinstance(updated_at, datetime):
        embed.set_footer(
            text=(
                f"Updated: {discord.utils.format_dt(updated_at, style='R')} | "
                "Long text may be truncated"
            )
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
