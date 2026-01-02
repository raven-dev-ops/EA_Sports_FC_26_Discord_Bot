from datetime import datetime, timezone

import discord

from interactions.roster_embeds import build_roster_listing_embed


def test_roster_listing_embed_uses_relative_timestamp_footer() -> None:
    roster = {
        "team_name": "A-Team",
        "coach_discord_id": 123,
        "cap": 16,
        "updated_at": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    }
    embed = build_roster_listing_embed(roster, [], approved=True)
    expected = f"Updated: {discord.utils.format_dt(roster['updated_at'], style='R')}"
    assert embed.footer.text == expected
