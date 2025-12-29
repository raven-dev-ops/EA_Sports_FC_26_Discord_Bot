"""
Register slash commands for the bot.

Usage:
  python -m scripts.register_commands --guild 123        # sync to a dev guild
  python -m scripts.register_commands --global           # sync globally
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Optional

import discord

from config import load_settings
from offside_bot.__main__ import build_bot, load_cogs


async def _sync(bot: discord.Client, guild_id: Optional[int]) -> None:
    await load_cogs(bot)  # reuse existing cogs/commands
    if guild_id:
        target = discord.Object(id=guild_id)
        await bot.tree.sync(guild=target)
        logging.info("Synced commands to guild %s", guild_id)
    else:
        await bot.tree.sync()
        logging.info("Synced global commands.")


async def main_async(guild_id: Optional[int]) -> None:
    settings = load_settings()
    bot = build_bot(settings)
    async with bot:
        await bot.login(settings.discord_token)
        await _sync(bot, guild_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Register slash commands.")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--guild", type=int, help="Guild ID for scoped registration.")
    scope.add_argument("--global", dest="is_global", action="store_true", help="Sync globally.")
    args = parser.parse_args()

    guild_id = args.guild if not args.is_global else None
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main_async(guild_id))


if __name__ == "__main__":
    main()
