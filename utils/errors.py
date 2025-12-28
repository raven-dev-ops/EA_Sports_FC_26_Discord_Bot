from __future__ import annotations

import logging

import discord


def log_interaction_error(
    error: Exception,
    interaction: discord.Interaction,
    *,
    source: str,
) -> None:
    command_name = getattr(interaction.command, "name", None)
    logging.error(
        "Interaction error source=%s user_id=%s command=%s",
        source,
        getattr(interaction.user, "id", None),
        command_name,
        exc_info=error,
    )


async def send_interaction_error(
    interaction: discord.Interaction,
    message: str = "Something went wrong. Please try again.",
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)
