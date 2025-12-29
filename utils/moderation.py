from __future__ import annotations

import discord

from utils.validation import ensure_safe_text


async def enforce_safe_inputs(interaction: discord.Interaction) -> bool:
    """
    Global check to prevent mass-mention content in string options.
    """
    ns = getattr(interaction, "namespace", None)
    if not ns:
        return True
    try:
        for value in ns.__dict__.values():
            if isinstance(value, str):
                ensure_safe_text(value)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return False
    return True
