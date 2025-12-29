from __future__ import annotations

import logging
import uuid

import discord


def log_interaction_error(
    error: Exception,
    interaction: discord.Interaction,
    *,
    source: str,
    error_id: str | None = None,
) -> None:
    command_name = getattr(interaction.command, "name", None)
    prefix = f"[error_id={error_id}] " if error_id else ""
    guild_id = getattr(interaction.guild, "id", None) if interaction.guild else None
    channel_id = getattr(interaction.channel, "id", None) if interaction.channel else None
    user_id = getattr(interaction.user, "id", None)
    logging.error(
        "%sInteraction error source=%s guild=%s channel=%s user=%s command=%s",
        prefix,
        source,
        guild_id,
        channel_id,
        user_id,
        command_name,
        exc_info=error,
    )


async def send_interaction_error(
    interaction: discord.Interaction,
    message: str = "Something went wrong. Please try again.",
    error_id: str | None = None,
) -> None:
    if error_id:
        message = f"{message} (ref: {error_id})"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def new_error_id() -> str:
    return uuid.uuid4().hex[:8]
