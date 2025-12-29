from __future__ import annotations

import discord

from interactions.dashboard import build_roster_dashboard
from interactions.views import SafeView
from utils.channel_routing import resolve_channel_id
from discord.ext import commands


def build_coach_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Coach Guide",
        description="How to create, edit, and submit your roster.",
        color=discord.Color.green(),
    )
    embed.add_field(
        name="Create & Manage",
        value=(
            "1) Open the dashboard and create your roster.\n"
            "2) Add/remove players and view your roster.\n"
            "3) Submit; roster locks until staff acts."
        ),
        inline=False,
    )
    embed.add_field(
        name="Player Fields",
        value="Discord mention/ID, Gamertag/PSN, EA ID, Console (PS/XBOX/PC/SWITCH).",
        inline=False,
    )
    embed.add_field(
        name="After Submit",
        value="Locked until staff approves/rejects; ask staff to unlock for edits.",
        inline=False,
    )
    return embed


def build_coach_portal_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Coach Roster Portal",
        description=(
            "Use the buttons below to open your roster dashboard or view the coach guide. "
            "All responses are ephemeral (only you can see them)."
        ),
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Dashboard",
        value="Open your roster dashboard to create, add/remove players, view, and submit.",
        inline=False,
    )
    embed.add_field(
        name="Help",
        value="Read the coach guide for step-by-step instructions.",
        inline=False,
    )
    return embed


class CoachPortalView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        btn_dashboard = discord.ui.Button(
            label="Open Roster Dashboard", style=discord.ButtonStyle.primary
        )
        btn_help = discord.ui.Button(label="Coach Help", style=discord.ButtonStyle.secondary)
        btn_dashboard.callback = self.on_dashboard
        btn_help.callback = self.on_help
        self.add_item(btn_dashboard)
        self.add_item(btn_help)

    async def on_dashboard(self, interaction: discord.Interaction) -> None:
        try:
            embed, view = build_roster_dashboard(interaction)
        except Exception:
            await interaction.response.send_message(
                "Could not load your roster dashboard. Try again.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_help(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_coach_help_embed(), ephemeral=True)


async def send_coach_portal_message(
    interaction: discord.Interaction,
) -> None:
    settings = getattr(interaction.client, "settings", None)
    if settings is None:
        await interaction.response.send_message(
            "Bot configuration is not loaded.",
            ephemeral=True,
        )
        return

    test_mode = bool(getattr(interaction.client, "test_mode", False))
    target_channel_id = resolve_channel_id(
        settings, settings.channel_coach_portal_id, test_mode=test_mode
    )

    channel = interaction.client.get_channel(target_channel_id)
    if channel is None:
        try:
            channel = await interaction.client.fetch_channel(target_channel_id)
        except discord.DiscordException:
            await interaction.response.send_message(
                "Coach portal channel not found.",
                ephemeral=True,
            )
            return

    try:
        async for message in channel.history(limit=20):
            if message.author.id == interaction.client.user.id:
                if message.embeds and message.embeds[0].title == "Coach Roster Portal":
                    try:
                        await message.delete()
                    except discord.DiscordException:
                        pass
    except discord.DiscordException:
        pass

    embed = build_coach_portal_embed()
    view = CoachPortalView()
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(
        f"Posted coach portal to <#{target_channel_id}>.",
        ephemeral=True,
    )


async def post_coach_portal(bot: commands.Bot) -> None:
    settings = getattr(bot, "settings", None)
    if settings is None:
        return

    test_mode = bool(getattr(bot, "test_mode", False))
    target_channel_id = resolve_channel_id(
        settings, settings.channel_roster_portal_id, test_mode=test_mode
    )

    channel = bot.get_channel(target_channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(target_channel_id)
        except discord.DiscordException:
            return

    try:
        async for message in channel.history(limit=20):
            if message.author.id == bot.user.id:
                if message.embeds and message.embeds[0].title == "Coach Roster Portal":
                    try:
                        await message.delete()
                    except discord.DiscordException:
                        pass
    except discord.DiscordException:
        pass

    embed = build_coach_portal_embed()
    view = CoachPortalView()
    try:
        await channel.send(embed=embed, view=view)
    except discord.DiscordException:
        return
