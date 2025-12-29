from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


SAFE_CONFIG_FIELDS = {
    "discord_application_id",
    "discord_client_id",
    "discord_public_key",
    "interactions_endpoint_url",
    "discord_test_channel_id",
    "test_mode",
    "role_broskie_id",
    "role_super_league_coach_id",
    "role_coach_premium_id",
    "role_coach_premium_plus_id",
    "channel_roster_portal_id",
    "channel_coach_portal_id",
    "channel_staff_portal_id",
    "banlist_sheet_id",
    "banlist_range",
    "banlist_cache_ttl_seconds",
}


class ConfigCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        settings = getattr(self.bot, "settings", None)
        if settings is None:
            return False
        role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
        if settings.staff_role_ids:
            return bool(role_ids.intersection(settings.staff_role_ids))
        return bool(getattr(interaction.user, "guild_permissions", None).manage_guild)

    @app_commands.command(name="config_view", description="View current bot configuration (non-secret).")
    async def config_view(self, interaction: discord.Interaction) -> None:
        if not self._is_staff(interaction):
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

    @app_commands.command(name="config_set", description="Set a runtime config value (staff only).")
    @app_commands.describe(field="Config field", value="New value")
    async def config_set(self, interaction: discord.Interaction, field: str, value: str) -> None:
        if not self._is_staff(interaction):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        field = field.strip()
        if field not in SAFE_CONFIG_FIELDS:
            await interaction.response.send_message("Field not allowed or does not exist.", ephemeral=True)
            return
        # Update runtime settings on the bot object only (no persistence).
        settings = getattr(self.bot, "settings", None)
        if settings is None:
            await interaction.response.send_message("Settings unavailable.", ephemeral=True)
            return
        try:
            current = getattr(settings, field)
            if isinstance(current, bool):
                parsed = value.lower() in {"1", "true", "yes", "on"}
            elif isinstance(current, int):
                parsed = int(value)
            else:
                parsed = value
        except Exception:
            parsed = value
        # Override on bot; caller must restart to persist.
        setattr(settings, field, parsed)
        await interaction.response.send_message(
            f"Set `{field}` to `{parsed}` (runtime only; restart to persist).",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ConfigCog(bot))
