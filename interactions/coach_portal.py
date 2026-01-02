from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from interactions.dashboard import build_roster_dashboard
from interactions.views import SafeView
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import fetch_channel, send_message
from utils.embeds import DEFAULT_COLOR, make_embed
from utils.permissions import is_staff_user


def _portal_footer() -> str:
    return f"Last refreshed: {discord.utils.format_dt(datetime.now(timezone.utc), style='R')}"


def build_coach_help_embed() -> discord.Embed:
    embed = make_embed(
        title="Coach Guide",
        description="Quick steps for creating, editing, and submitting your roster.",
        color=DEFAULT_COLOR,
    )
    embed.add_field(
        name="Create & manage",
        value=(
            "- Open the roster dashboard.\n"
            "- Add/remove players and review your roster.\n"
            "- Submit; your roster locks until staff acts."
        ),
        inline=False,
    )
    embed.add_field(
        name="Player fields",
        value=(
            "- Discord ID/mention\n"
            "- Gamertag/PSN\n"
            "- EA ID\n"
            "- Console (PS/XBOX/PC/SWITCH)"
        ),
        inline=False,
    )
    embed.add_field(
        name="After submit",
        value="If rejected, staff must unlock your roster before you can edit/resubmit.",
        inline=False,
    )
    return embed


def build_coach_portal_embed() -> discord.Embed:
    embed = make_embed(
        title="Coach Portal",
        description=(
            "**Build and submit your roster for the current cycle.**\n"
            "- Minimum 8 players to submit.\n"
            "- Caps: Team Coach=16, Club Manager=22.\n"
            "- After submit, your roster locks until staff approves/rejects.\n"
            "- Pro coaches: set Practice Times to appear in the Pro coaches report.\n\n"
            "Use the action menu below. Responses are ephemeral."
        ),
        color=DEFAULT_COLOR,
        footer=_portal_footer(),
    )
    return embed


class CoachPortalView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        options = [
            discord.SelectOption(
                label="Open Roster Dashboard",
                value="dashboard",
                description="Create, edit, and submit your roster",
            ),
            discord.SelectOption(
                label="Coach Help",
                value="help",
                description="Tips + requirements",
            ),
            discord.SelectOption(
                label="Repost Portal",
                value="repost",
                description="Staff-only portal cleanup",
            ),
        ]
        self.action_select = discord.ui.Select(
            placeholder="Select a coach action...",
            options=options,
        )
        self.action_select.callback = self.on_action_select
        self.add_item(self.action_select)

    async def on_action_select(self, interaction: discord.Interaction) -> None:
        selection = self.action_select.values[0] if self.action_select.values else ""
        if selection == "dashboard":
            await self.on_dashboard(interaction)
        elif selection == "help":
            await self.on_help(interaction)
        elif selection == "repost":
            await self.on_repost_portal(interaction)
        else:
            await interaction.response.send_message(
                "Select a valid action.",
                ephemeral=True,
            )

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

    async def on_repost_portal(self, interaction: discord.Interaction) -> None:
        settings = getattr(interaction.client, "settings", None)
        if not is_staff_user(interaction.user, settings, guild_id=getattr(interaction, "guild_id", None)):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This action must be used in a guild.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=make_embed(
                title="Reposting portal...",
                description="Cleaning up and reposting the coach portal now.",
                color=DEFAULT_COLOR,
            ),
            ephemeral=True,
        )
        await post_coach_portal(interaction.client, guilds=[guild])


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
        settings,
        guild_id=getattr(interaction.guild, "id", None),
        field="channel_coach_portal_id",
        test_mode=test_mode,
    )
    if not target_channel_id:
        await interaction.response.send_message(
            "Coach portal channel is not configured yet. Ensure the bot has `Manage Channels` and "
            "MongoDB is configured, then restart the bot.",
            ephemeral=True,
        )
        return

    channel = await fetch_channel(interaction.client, target_channel_id)
    if channel is None:
        await interaction.response.send_message(
            "Coach portal channel not found.",
            ephemeral=True,
        )
        return

    try:
        async for message in channel.history(limit=20):  # type: ignore[attr-defined]
            client_user = interaction.client.user
            if client_user and message.author.id == client_user.id:
                if message.embeds and message.embeds[0].title in {
                    "Coach Roster Portal",
                    "Coach Portal Overview",
                    "Coach Portal",
                }:
                    try:
                        await message.delete()
                    except discord.DiscordException:
                        pass
    except discord.DiscordException:
        pass

    embed = build_coach_portal_embed()
    view = CoachPortalView()
    try:
        await send_message(
            channel,
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.DiscordException as exc:
        logging.warning("Failed to post coach portal to channel %s: %s", target_channel_id, exc)
        await interaction.response.send_message(
            f"Could not post coach portal to <#{target_channel_id}>.",
            ephemeral=True,
        )
        return
    await interaction.response.send_message(
        f"Posted coach portal to <#{target_channel_id}>.",
        ephemeral=True,
    )


async def post_coach_portal(
    bot: discord.Client,
    *,
    guilds: list[discord.Guild] | None = None,
) -> None:
    settings = getattr(bot, "settings", None)
    if settings is None:
        return

    test_mode = bool(getattr(bot, "test_mode", False))
    target_guilds = bot.guilds if guilds is None else guilds
    for guild in target_guilds:
        target_channel_id = resolve_channel_id(
            settings,
            guild_id=guild.id,
            field="channel_coach_portal_id",
            test_mode=test_mode,
        )
        if not target_channel_id:
            continue

        channel = await fetch_channel(bot, target_channel_id)
        if channel is None:
            continue

        bot_user = bot.user
        if bot_user is None:
            continue
        try:
            async for message in channel.history(limit=20):  # type: ignore[attr-defined]
                if message.author.id == bot_user.id:
                    if message.embeds and message.embeds[0].title in {
                        "Coach Roster Portal",
                        "Coach Portal Overview",
                        "Coach Portal",
                    }:
                        try:
                            await message.delete()
                        except discord.DiscordException:
                            pass
        except discord.DiscordException:
            pass

        embed = build_coach_portal_embed()
        view = CoachPortalView()
        try:
            await send_message(
                channel,
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            logging.info(
                "Posted coach portal embed (guild=%s channel=%s).",
                guild.id,
                target_channel_id,
            )
        except discord.DiscordException as exc:
            logging.warning(
                "Failed to post coach portal to channel %s (guild=%s): %s",
                target_channel_id,
                guild.id,
                exc,
            )
