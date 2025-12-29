from __future__ import annotations

import discord

# Centralized embed styling so colors/icons stay consistent across commands.
DEFAULT_COLOR = 0x2B6CB0  # deep blue for informational messages
SUCCESS_COLOR = 0x2F855A  # green for confirmations
WARNING_COLOR = 0xD69E2E  # amber for warnings
ERROR_COLOR = 0xC53030    # red for errors


def make_embed(
    *,
    title: str,
    description: str | None = None,
    color: int = DEFAULT_COLOR,
    footer: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description or "", color=color)
    if footer:
        embed.set_footer(text=footer)
    return embed
