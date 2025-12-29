"""
Export all members of a Discord guild into MongoDB.

Fields stored per member:
- guild_id, user_id
- username (name#discriminator), display_name, global_name, bot flag
- roles: list of {id, name} excluding @everyone
- updated_at (UTC)

Usage:
    python scripts/export_members.py --guild-id <GUILD_ID> [--collection FIFADiscordMemberList]

Env vars required:
    DISCORD_TOKEN
    MONGODB_URI
    MONGODB_DB_NAME
Optional:
    MONGODB_COLLECTION (default: from code arg/collection name)
    DISCORD_GUILD_ID (fallback if --guild-id not provided)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import discord
from pymongo import MongoClient
from pymongo.collection import Collection


DEFAULT_COLLECTION = "FIFADiscordMemberList"


def _mongo_collection(collection_name: str) -> Collection:
    mongo_uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DB_NAME")
    if not mongo_uri or not db_name:
        raise SystemExit("MONGODB_URI and MONGODB_DB_NAME are required.")
    client = MongoClient(mongo_uri)
    return client[db_name][collection_name]


class ExportClient(discord.Client):
    def __init__(
        self,
        *,
        guild_id: int,
        collection: Collection,
        **kwargs: Any,
    ) -> None:
        intents = kwargs.pop("intents", discord.Intents.default())
        super().__init__(intents=intents, **kwargs)
        self.guild_id = guild_id
        self.collection = collection
        self.inserted = 0
        self.updated = 0

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")
        try:
            guild = self.get_guild(self.guild_id) or await self.fetch_guild(self.guild_id)
        except discord.DiscordException as exc:
            logging.error("Failed to fetch guild %s: %s", self.guild_id, exc)
            await self.close()
            return

        logging.info("Fetching members for guild %s (%s)", guild.name, guild.id)
        count = 0
        async for member in guild.fetch_members(limit=None):
            roles = [
                {"id": role.id, "name": role.name}
                for role in member.roles
                if not role.is_default()
            ]
            doc = {
                "guild_id": guild.id,
                "user_id": member.id,
                "username": str(member),
                "display_name": member.display_name,
                "global_name": member.global_name,
                "bot": bool(member.bot),
                "roles": roles,
                "updated_at": datetime.now(timezone.utc),
            }
            result = self.collection.update_one(
                {"guild_id": guild.id, "user_id": member.id},
                {"$set": doc},
                upsert=True,
            )
            if result.matched_count:
                self.updated += 1
            else:
                self.inserted += 1
            count += 1
            if count % 500 == 0:
                logging.info("Processed %s members (inserted %s, updated %s)", count, self.inserted, self.updated)

        logging.info(
            "Done. Processed %s members (inserted %s, updated %s).",
            count,
            self.inserted,
            self.updated,
        )
        await self.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Discord guild members to MongoDB.")
    parser.add_argument(
        "--guild-id",
        type=int,
        default=None,
        help="Discord guild ID (falls back to DISCORD_GUILD_ID).",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=DEFAULT_COLLECTION,
        help=f"MongoDB collection name (default: {DEFAULT_COLLECTION}).",
    )
    args = parser.parse_args()

    guild_id = args.guild_id or os.getenv("DISCORD_GUILD_ID")
    if not guild_id:
        raise SystemExit("Provide --guild-id or set DISCORD_GUILD_ID.")
    guild_id = int(guild_id)

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is required.")

    collection = _mongo_collection(args.collection)

    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True  # Requires privileged member intent enabled for the bot.

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    client = ExportClient(guild_id=guild_id, collection=collection, intents=intents)
    asyncio.run(client.start(token))


if __name__ == "__main__":
    main()
