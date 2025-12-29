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
        embed.add_field(name="Region", value=str(ad["region"]), inline=True)
    if ad.get("timezone"):
        embed.add_field(name="Timezone", value=str(ad["timezone"]), inline=True)
    if ad.get("formation"):
        embed.add_field(name="Formation", value=str(ad["formation"]), inline=True)

    positions = ad.get("positions_needed") or []
    if isinstance(positions, list) and positions:
        lines = [f"- {p}" for p in positions if str(p).strip()]
        embed.add_field(
            name="Positions needed",
            value="\n".join(lines)[:1024],
            inline=False,
        )

    keywords = ad.get("keywords") or []
    if isinstance(keywords, list) and keywords:
        embed.add_field(
            name="Keywords",
            value=", ".join(str(k) for k in keywords)[:1024],
            inline=False,
        )

    description = ad.get("description")
    if description:
        embed.add_field(name="What we're looking for", value=str(description)[:1024], inline=False)

    tryout_at = ad.get("tryout_at")
    if isinstance(tryout_at, datetime):
        embed.add_field(
            name="Tryout time (viewer-local)",
            value=f"{discord.utils.format_dt(tryout_at, style='F')} ({discord.utils.format_dt(tryout_at, style='R')})",
            inline=False,
        )

    contact = ad.get("contact")
    if contact:
        embed.add_field(name="Contact", value=str(contact)[:1024], inline=False)

    return embed

