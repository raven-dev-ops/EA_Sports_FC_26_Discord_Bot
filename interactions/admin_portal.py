from __future__ import annotations

import discord

from utils.channel_routing import resolve_channel_id
from utils.errors import send_interaction_error
from interactions.views import SafeView


ADMIN_EMBED_DESCRIPTION = (
    "Admin controls for the tournament bot. Use the buttons below to view quick actions "
    "and command references. All responses are ephemeral to you."
)


def build_admin_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Admin Control Panel",
        description=ADMIN_EMBED_DESCRIPTION,
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Bot Controls",
        value="Toggle test mode, health checks.",
        inline=False,
    )
    embed.add_field(
        name="Tournaments",
        value="Lifecycle, rules, fixtures.",
        inline=False,
    )
    embed.add_field(
        name="Coaches & Rosters",
        value="Unlock, review, roster dashboards.",
        inline=False,
    )
    embed.add_field(
        name="Players",
        value="Player eligibility and ban checks.",
        inline=False,
    )
    embed.add_field(
        name="DB & Analytics",
        value="Data checks, health, and exports.",
        inline=False,
    )
    return embed


class AdminPortalView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

        buttons = [
            ("Bot Controls", discord.ButtonStyle.primary, self.on_bot_controls),
            ("Tournaments", discord.ButtonStyle.primary, self.on_tournaments),
            ("Coaches", discord.ButtonStyle.primary, self.on_coaches),
            ("Rosters", discord.ButtonStyle.primary, self.on_rosters),
            ("Players", discord.ButtonStyle.primary, self.on_players),
            ("DB Analytics", discord.ButtonStyle.primary, self.on_db),
        ]
        for label, style, handler in buttons:
            button = discord.ui.Button(label=label, style=style)
            button.callback = handler
            self.add_item(button)

    def _staff_only(self, interaction: discord.Interaction) -> bool:
        settings = getattr(interaction.client, "settings", None)
        role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
        if settings and settings.staff_role_ids:
            return bool(role_ids.intersection(settings.staff_role_ids))
        perms = getattr(interaction.user, "guild_permissions", None)
        return bool(perms and perms.manage_guild)

    async def _ensure_staff(self, interaction: discord.Interaction) -> bool:
        if not self._staff_only(interaction):
            await interaction.response.send_message(
                "You do not have permission to use this panel.",
                ephemeral=True,
            )
            return False
        return True

    async def on_bot_controls(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            "**Bot Controls**\n"
            "- `/dev_on` / `/dev_off` toggle test-mode routing.\n"
            "- `/ping` health check.\n"
            "- Logs route to test channel when test mode is on.\n",
            ephemeral=True,
        )

    async def on_tournaments(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            "**Tournaments**\n"
            "- Use `/roster tournament:\"Name\"` for multi-cycle support.\n"
            "- Staff review happens in the submissions channel with buttons.\n"
            "- Future: add lifecycle and fixtures commands here.\n",
            ephemeral=True,
        )

    async def on_coaches(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            "**Coaches**\n"
            "- `/unlock_roster @Coach [tournament]` to unlock.\n"
            "- `/help` shows coach-facing instructions.\n"
            "- Roster caps based on coach roles.\n",
            ephemeral=True,
        )

    async def on_rosters(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            "**Rosters**\n"
            "- Coaches use `/roster` for create/add/remove/view/submit.\n"
            "- Staff approve/reject via buttons on the submission message.\n"
            "- Audit trail records approvals, rejections, unlocks.\n",
            ephemeral=True,
        )

    async def on_players(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            "**Players**\n"
            "- Add via dashboard → Add Player modal (Discord ID, Gamertag/PSN, EA ID, Console).\n"
            "- Ban list checks are optional and configured via Google Sheets settings.\n",
            ephemeral=True,
        )

    async def on_db(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            "**DB & Analytics**\n"
            "- MongoDB used for rosters/cycles/submissions/audit.\n"
            "- Future: add health/metrics/export commands.\n",
            ephemeral=True,
        )


async def send_admin_portal_message(
    interaction: discord.Interaction,
) -> None:
    settings = getattr(interaction.client, "settings", None)
    if settings is None:
        await send_interaction_error(interaction)
        return

    test_mode = bool(getattr(interaction.client, "test_mode", False))
    target_channel_id = resolve_channel_id(
        settings, settings.channel_admin_portal_id, test_mode=test_mode
    )

    channel = interaction.client.get_channel(target_channel_id)
    if channel is None:
        try:
            channel = await interaction.client.fetch_channel(target_channel_id)
        except discord.DiscordException:
            await interaction.response.send_message(
                "Admin portal channel not found.",
                ephemeral=True,
            )
            return

    embed = build_admin_embed()
    view = AdminPortalView()
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(
        f"Posted admin control panel to <#{target_channel_id}>.",
        ephemeral=True,
    )
