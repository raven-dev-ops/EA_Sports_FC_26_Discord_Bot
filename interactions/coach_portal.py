from __future__ import annotations

import logging

import discord
from discord.ext import commands

from interactions.dashboard import build_roster_dashboard
from interactions.views import SafeView
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import fetch_channel, send_message


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


def build_coach_intro_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Coach Portal Overview",
        description=(
            "@Coach\n"
            "@Coach Premium @Coach Premium+\n\n"
            "Coaches, welcome to the Offside Bot Portal\n\n"
            "This portal is the official system used for signing players and submitting your team roster. "
            "To assist you, the Coach Help button is available and provides a full list of commands you may need throughout the process.\n\n"
            "When you are ready to begin, select Open Roster Dashboard. Inside the dashboard, you will be able to add players, remove players, view your current roster, "
            "and edit your team name. All players must be added using their correct player DISCORD ID copied from their profile. "
            "The roster name must exactly match the team name that was assigned to you by staff; no extra words, symbols, or changes are allowed.\n\n"
            "**Roster Requirements & Limits**\n"
            "A minimum of 8 players is required in order to submit a roster. Coaches are permitted to sign up to 16 players. "
            "Coaches with a Premium membership may sign up to 22 players, while Premium+ coaches may sign up to 25 players. "
            "It is the coach’s responsibility to ensure their roster does not exceed these limits.\n\n"
            "🚨 **Submission & Approval Process**\n"
            "Once your roster is complete, you may submit it. Each team is allowed one initial submission. After submission, a staff member will review your roster. "
            "If approved, you will receive confirmation along with the name of the staff member who approved and assigned your team. "
            "If your roster is rejected, you will receive a direct message explaining the reason for the rejection and what needs to be corrected.\n\n"
            "✅ **Resubmission & Finalization**\n"
            "If your roster is rejected, review the feedback carefully, then go to your team’s ticket and ping the staff member who declined your roster. "
            "That staff member will unlock your roster, allowing you to make the required changes and submit again. After resubmission, wait for approval. "
            "Once your roster is approved, it is finalized and cannot be changed under the roster lock date, which will be announced below this message.\n\n"
            "📣 **Premium Coach Listings**\n"
            "Premium coaches can set Practice Times from the roster dashboard to keep the #premium-coaches report up to date."
        ),
        color=discord.Color.orange(),
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
        btn_dashboard: discord.ui.Button = discord.ui.Button(
            label="Open Roster Dashboard", style=discord.ButtonStyle.primary
        )
        btn_help: discord.ui.Button = discord.ui.Button(
            label="Coach Help", style=discord.ButtonStyle.secondary
        )
        setattr(btn_dashboard, "callback", self.on_dashboard)
        setattr(btn_help, "callback", self.on_help)
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
        settings,
        guild_id=getattr(interaction.guild, "id", None),
        field="channel_coach_portal_id",
        test_mode=test_mode,
    )
    if not target_channel_id:
        await interaction.response.send_message(
            "Coach portal channel is not configured yet. Ensure the bot has `Manage Channels` and MongoDB is configured, then restart the bot.",
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
        async for message in channel.history(limit=20):
            client_user = interaction.client.user
            if client_user and message.author.id == client_user.id:
                if message.embeds and message.embeds[0].title in {
                    "Coach Roster Portal",
                    "Coach Portal Overview",
                }:
                    try:
                        await message.delete()
                    except discord.DiscordException:
                        pass
    except discord.DiscordException:
        pass

    intro_embed = build_coach_intro_embed()
    embed = build_coach_portal_embed()
    view = CoachPortalView()
    try:
        await send_message(channel, embed=intro_embed)
        await send_message(channel, embed=embed, view=view)
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
    bot: commands.Bot | commands.AutoShardedBot,
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
            async for message in channel.history(limit=20):
                if message.author.id == bot_user.id:
                    if message.embeds and message.embeds[0].title in {
                        "Coach Roster Portal",
                        "Coach Portal Overview",
                    }:
                        try:
                            await message.delete()
                        except discord.DiscordException:
                            pass
        except discord.DiscordException:
            pass

        intro_embed = build_coach_intro_embed()
        embed = build_coach_portal_embed()
        view = CoachPortalView()
        try:
            await send_message(channel, embed=intro_embed)
            await send_message(channel, embed=embed, view=view)
            logging.info("Posted coach portal embed (guild=%s channel=%s).", guild.id, target_channel_id)
        except discord.DiscordException as exc:
            logging.warning(
                "Failed to post coach portal to channel %s (guild=%s): %s",
                target_channel_id,
                guild.id,
                exc,
            )
