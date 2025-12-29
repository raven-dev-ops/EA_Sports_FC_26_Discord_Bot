from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.channel_setup_service import ensure_offside_channels
from services.guild_config_service import get_guild_config, set_guild_config
from utils.permissions import is_staff_user


class SetupChannelsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.settings = getattr(bot, "settings", None)

    @app_commands.command(
        name="setup_channels",
        description="Create/update Offside categories + channels for this guild (staff only).",
    )
    async def setup_channels(self, interaction: discord.Interaction) -> None:
        settings = getattr(interaction.client, "settings", None)
        if not is_staff_user(interaction.user, settings):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command must be used in a guild.",
                ephemeral=True,
            )
            return

        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "I need the `Manage Channels` permission to create categories/channels.",
                ephemeral=True,
            )
            return

        if settings is None or not (settings.mongodb_uri and settings.mongodb_db_name and settings.mongodb_collection):
            await interaction.response.send_message(
                "MongoDB is not configured, so I can't persist per-guild channel IDs. "
                "Set `MONGODB_URI`, `MONGODB_DB_NAME`, and `MONGODB_COLLECTION`, then restart.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        test_mode = bool(getattr(interaction.client, "test_mode", False))
        existing = get_guild_config(guild.id)
        updated, actions = await ensure_offside_channels(
            guild,
            settings=settings,
            existing_config=existing,
            test_mode=test_mode,
        )
        set_guild_config(guild.id, updated)

        staff_monitor_id = updated.get("channel_staff_monitor_id")
        if test_mode:
            setattr(
                interaction.client,
                "staff_monitor_channel_id",
                int(staff_monitor_id) if staff_monitor_id else None,
            )
        else:
            setattr(interaction.client, "staff_monitor_channel_id", None)

        lines: list[str] = ["Offside channels setup complete."]
        if actions:
            lines.append("")
            lines.append("Actions:")
            lines.extend(f"- {a}" for a in actions)
        lines.append("")
        lines.append("Stored channel IDs:")
        for key in (
            "channel_staff_portal_id",
            "channel_club_portal_id",
            "channel_coach_portal_id",
            "channel_recruit_portal_id",
            "channel_staff_monitor_id",
            "channel_roster_listing_id",
            "channel_recruit_listing_id",
            "channel_club_listing_id",
        ):
            value = updated.get(key)
            if isinstance(value, int):
                lines.append(f"- {key}: <#{value}>")
            else:
                lines.append(f"- {key}: {value}")

        await interaction.followup.send("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupChannelsCog(bot))
