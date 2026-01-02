from __future__ import annotations

import discord

# Centralized embed styling so colors/icons stay consistent across commands.
DEFAULT_COLOR = 0x2B6CB0  # deep blue for informational messages
SUCCESS_COLOR = 0x2F855A  # green for confirmations
WARNING_COLOR = 0xD69E2E  # amber for warnings
ERROR_COLOR = 0xC53030    # red for errors


def _apply_footer(embed: discord.Embed, footer: str | None) -> None:
    if not footer:
        return
    if "<t:" in footer:
        base = embed.description or ""
        if base:
            embed.description = f"{base}\n\n{footer}"
        else:
            embed.description = footer
        return
    embed.set_footer(text=footer)


def make_embed(
    *,
    title: str,
    description: str | None = None,
    color: int = DEFAULT_COLOR,
    footer: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description or "", color=color)
    _apply_footer(embed, footer)
    return embed


def apply_embed_footer(embed: discord.Embed, footer: str | None) -> None:
    _apply_footer(embed, footer)
