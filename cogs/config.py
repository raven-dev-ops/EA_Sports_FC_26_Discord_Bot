from __future__ import annotations

from dataclasses import replace

import discord
from discord import app_commands
from discord.ext import commands

from services.guild_config_service import get_guild_config, set_guild_config
from utils.permissions import is_staff_user

SAFE_CONFIG_FIELDS = {
    "discord_application_id",
    "discord_client_id",
    "discord_public_key",
    "interactions_endpoint_url",
    "test_mode",
    "role_broskie_id",
    "role_coach_id",
    "role_coach_premium_id",
    "role_coach_premium_plus_id",
    "channel_staff_portal_id",
    "channel_club_portal_id",
    "channel_manager_portal_id",
    "channel_coach_portal_id",
    "channel_recruit_portal_id",
    "channel_staff_monitor_id",
    "channel_roster_listing_id",
    "channel_recruit_listing_id",
    "channel_club_listing_id",
    "channel_premium_coaches_id",
    "banlist_sheet_id",
    "banlist_range",
    "banlist_cache_ttl_seconds",
    "fc25_stats_cache_ttl_seconds",
    "fc25_stats_http_timeout_seconds",
    "fc25_stats_max_concurrency",
    "fc25_stats_rate_limit_per_guild",
    "fc25_default_platform",
}


class ConfigCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.settings = getattr(bot, "settings", None)

    @app_commands.command(name="config_view", description="View current bot configuration (non-secret).")
    async def config_view(self, interaction: discord.Interaction) -> None:
        if not is_staff_user(interaction.user, self.settings):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        settings = getattr(self.bot, "settings", None)
        if settings is None:
            await interaction.response.send_message("Settings unavailable.", ephemeral=True)
            return
        lines = []
        for field in sorted(SAFE_CONFIG_FIELDS):
            val = getattr(settings, field, None)
            lines.append(f"{field}: {val}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(
        name="config_guild_view", description="View per-guild overrides (staff only)."
    )
    async def config_guild_view(self, interaction: discord.Interaction) -> None:
        if not is_staff_user(interaction.user, self.settings):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command must be used in a guild.", ephemeral=True
            )
            return
        cfg = get_guild_config(guild.id)
        if not cfg:
            await interaction.response.send_message("No overrides set.", ephemeral=True)
            return
        lines = [f"{k}: {v}" for k, v in sorted(cfg.items())]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(
        name="config_guild_set", description="Set a per-guild override (staff only)."
    )
    @app_commands.describe(field="Field name", value="New value")
    async def config_guild_set(
        self, interaction: discord.Interaction, field: str, value: str
    ) -> None:
        if not is_staff_user(interaction.user, self.settings):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command must be used in a guild.", ephemeral=True
            )
            return
        field = field.strip()
        if not field:
            await interaction.response.send_message("Field is required.", ephemeral=True)
            return
        cfg = get_guild_config(guild.id)
        cfg[field] = value.strip()
        set_guild_config(guild.id, cfg)
        await interaction.response.send_message(
            f"Set `{field}` override for this guild.", ephemeral=True
        )

    @app_commands.command(name="config_set", description="Set a runtime config value (staff only).")
    @app_commands.describe(field="Config field", value="New value")
    async def config_set(self, interaction: discord.Interaction, field: str, value: str) -> None:
        if not is_staff_user(interaction.user, self.settings):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        field = field.strip()
        if field not in SAFE_CONFIG_FIELDS:
            await interaction.response.send_message("Field not allowed or does not exist.", ephemeral=True)
            return
        if field == "test_mode":
            await interaction.response.send_message(
                "Test mode is controlled via `TEST_MODE` in the environment; set it and restart the bot. "
                "Use `/setup_channels` while test mode is enabled to create the staff monitor channel.",
                ephemeral=True,
            )
            return
        # Update runtime settings on the bot object only (no persistence).
        settings = getattr(self.bot, "settings", None)
        if settings is None:
            await interaction.response.send_message("Settings unavailable.", ephemeral=True)
            return
        value = value.strip()
        parsed: bool | int | str
        try:
            current = getattr(settings, field)
            if isinstance(current, bool):
                parsed = value.lower() in {"1", "true", "yes", "on"}
            elif isinstance(current, int):
                parsed = int(value)
            elif current is None and (field.endswith("_id") or field.endswith("_seconds")):
                parsed = int(value)
            else:
                parsed = value
        except Exception:
            parsed = value
        # Override on bot; caller must restart to persist.
        try:
            new_settings = replace(settings, **{field: parsed})
        except TypeError:
            await interaction.response.send_message(
                "Failed to apply config override (invalid field/value).",
                ephemeral=True,
            )
            return
        setattr(self.bot, "settings", new_settings)
        self.settings = new_settings
        if field == "channel_staff_monitor_id":
            setattr(self.bot, "staff_monitor_channel_id", int(parsed) if parsed else None)
        await interaction.response.send_message(
            f"Set `{field}` to `{parsed}` (runtime only; restart to persist).",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ConfigCog(bot))
