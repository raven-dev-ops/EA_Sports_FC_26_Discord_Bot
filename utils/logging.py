from __future__ import annotations

import logging
from typing import Any

import discord


def _interaction_context(interaction: discord.Interaction) -> dict[str, Any]:
    guild_id = getattr(interaction.guild, "id", None) if interaction.guild else None
    channel_id = getattr(interaction.channel, "id", None) if interaction.channel else None
    user_id = getattr(interaction.user, "id", None) if interaction.user else None
    command = getattr(interaction.command, "qualified_name", None)
    interaction_id = getattr(interaction, "id", None)
    return {
        "guild_id": guild_id,
        "channel_id": channel_id,
        "user_id": user_id,
        "command": command,
        "interaction_id": interaction_id,
    }


def log_command_event(interaction: discord.Interaction, *, status: str) -> None:
    """
    Emit a structured log line for a command interaction.
    """
    ctx = _interaction_context(interaction)
    logging.info(
        "command event status=%s guild=%s channel=%s user=%s command=%s",
        status,
        ctx["guild_id"],
        ctx["channel_id"],
        ctx["user_id"],
        ctx["command"],
        extra=ctx,
    )
