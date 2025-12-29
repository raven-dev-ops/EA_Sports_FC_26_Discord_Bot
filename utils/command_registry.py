from __future__ import annotations

import logging
from typing import Iterable

import discord


def validate_commands(commands: Iterable[discord.app_commands.Command]) -> None:
    """
    Validate the command collection for duplicate names and missing descriptions.
    Raises RuntimeError on duplicates or empty descriptions.
    """
    seen: set[str] = set()
    for cmd in commands:
        name = cmd.qualified_name
        if not name:
            raise RuntimeError("Encountered command without a qualified_name.")
        if name in seen:
            raise RuntimeError(f"Duplicate command name detected: {name}")
        seen.add(name)
        desc = getattr(cmd, "description", "") or ""
        if not desc.strip() or desc.strip().lower() == "no description provided":
            raise RuntimeError(f"Command '{name}' is missing a meaningful description.")


def validate_command_tree(bot: discord.Client) -> None:
    """
    Convenience wrapper to validate the bot's command tree after sync.
    """
    commands = list(bot.tree.walk_commands())
    validate_commands(commands)
    logging.info("Validated %s commands (no duplicates, descriptions present).", len(commands))
