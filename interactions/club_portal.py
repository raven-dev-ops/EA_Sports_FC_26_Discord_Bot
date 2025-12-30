from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from interactions.club_embeds import build_club_ad_embed
from interactions.modals import ClubAdModalStep1
from interactions.views import SafeView
from services.clubs_service import delete_club_ad, get_club_ad
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import delete_message, fetch_channel, send_message
from utils.embeds import DEFAULT_COLOR, SUCCESS_COLOR, make_embed
from utils.permissions import is_staff_user


def _portal_footer() -> str:
    return f"Last refreshed: {discord.utils.format_dt(datetime.now(timezone.utc), style='R')}"


def build_club_intro_embed() -> discord.Embed:
    return make_embed(
        title="Club Portal Overview",
        description=(
            "**Purpose**\n"
            "Create a club ad so recruits can find you.\n\n"
            "**Who should use this**\n"
            "- Club staff/coaches posting ads.\n\n"
            "**Key rules**\n"
            "- Keep positions needed and keywords consistent so recruits can search.\n"
            "- Descriptions must be at least 30 characters."
        ),
        color=DEFAULT_COLOR,
        footer=_portal_footer(),
    )


def build_club_portal_embed() -> discord.Embed:
    embed = make_embed(
        title="Club Portal",
        description="Use the buttons below. All responses are ephemeral (only you can see them).",
        color=DEFAULT_COLOR,
        footer=_portal_footer(),
    )
    embed.add_field(
        name="Register / Edit",
        value="Opens a short 2-step form (modal).",
        inline=False,
    )
    embed.add_field(
        name="Preview",
        value="Shows what your public club listing embed will look like.",
        inline=False,
    )
    embed.add_field(
        name="Unregister",
        value="Deletes your stored club ad and removes your listing posts when possible.",
        inline=False,
    )
    embed.add_field(
        name="Help",
        value="Guidance and tips for making your club ad clear and searchable.",
        inline=False,
    )
    embed.add_field(
        name="Repost Portal (staff)",
        value="Clean up and repost this portal message set.",
        inline=False,
    )
    return embed


def build_club_help_embed() -> discord.Embed:
    return make_embed(
        title="Club Ads Help",
        description=(
            "Tips:\n"
            "- Keep positions needed and keywords consistent so coaches can filter/search.\n"
            "- Descriptions must be at least 30 characters.\n"
            "- If you provide a tryout time, use the format YYYY-MM-DD HH:MM.\n"
            "- Avoid mass mentions in descriptions.\n"
            "- If staff approvals are enabled, new ads may require approval before appearing publicly.\n"
            "- Ad edits are rate-limited to prevent spam."
        ),
        color=DEFAULT_COLOR,
    )


class ClubPortalView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Register / Edit",
        style=discord.ButtonStyle.primary,
        custom_id="club:register_edit",
    )
    async def register_edit(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This portal must be used in a guild.",
                ephemeral=True,
            )
            return
        logging.info(
            "Club portal action=register_edit guild=%s user=%s",
            guild.id,
            interaction.user.id,
        )
        existing = None
        try:
            existing = get_club_ad(guild.id, interaction.user.id)
        except Exception:
            existing = None
        await interaction.response.send_modal(ClubAdModalStep1(existing_ad=existing))

    @discord.ui.button(
        label="Preview",
        style=discord.ButtonStyle.secondary,
        custom_id="club:preview",
    )
    async def preview(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This portal must be used in a guild.",
                ephemeral=True,
            )
            return
        logging.info(
            "Club portal action=preview guild=%s user=%s",
            guild.id,
            interaction.user.id,
        )
        ad = None
        try:
            ad = get_club_ad(guild.id, interaction.user.id)
        except Exception:
            ad = None
        if not ad:
            await interaction.response.send_message(
                "No club ad found yet. Use Register / Edit first.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=build_club_ad_embed(ad),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Unregister",
        style=discord.ButtonStyle.danger,
        custom_id="club:unregister",
    )
    async def unregister(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This portal must be used in a guild.",
                ephemeral=True,
            )
            return
        logging.info(
            "Club portal action=unregister guild=%s user=%s",
            guild.id,
            interaction.user.id,
        )

        ad = None
        try:
            ad = get_club_ad(guild.id, interaction.user.id)
        except Exception:
            ad = None
        if not ad:
            await interaction.response.send_message(
                "No club ad found to delete.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await _delete_club_posts(interaction.client, ad)
        try:
            delete_club_ad(guild.id, interaction.user.id)
        except Exception:
            pass

        await interaction.followup.send(
            embed=make_embed(
                title="Club ad removed",
                description="Your club ad has been deleted.",
                color=SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Help",
        style=discord.ButtonStyle.secondary,
        custom_id="club:help",
    )
    async def help(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_message(
            embed=build_club_help_embed(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Repost Portal (staff)",
        style=discord.ButtonStyle.secondary,
        custom_id="club:repost_portal",
    )
    async def repost_portal(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
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
                description="Cleaning up and reposting the club portal now.",
                color=DEFAULT_COLOR,
            ),
            ephemeral=True,
        )
        await post_club_portal(interaction.client, guilds=[guild])


async def _delete_club_posts(client: discord.Client, ad: dict) -> None:
    for channel_key, message_key in (
        ("listing_channel_id", "listing_message_id"),
        ("staff_channel_id", "staff_message_id"),
    ):
        channel_id = ad.get(channel_key)
        message_id = ad.get(message_key)
        if not isinstance(channel_id, int) or not isinstance(message_id, int):
            continue
        channel = await fetch_channel(client, channel_id)
        if channel is None or not hasattr(channel, "fetch_message"):
            continue
        try:
            msg = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
        except discord.DiscordException:
            continue
        await delete_message(msg)


async def post_club_portal(
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
            field="channel_club_portal_id",
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
                        "Club Portal",
                        "Club Portal Overview",
                    }:
                        try:
                            await message.delete()
                        except discord.DiscordException:
                            pass
        except discord.DiscordException:
            pass

        intro_embed = build_club_intro_embed()
        embed = build_club_portal_embed()
        view = ClubPortalView()
        try:
            await send_message(
                channel,
                embed=intro_embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await send_message(
                channel,
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            logging.info(
                "Posted club portal embed (guild=%s channel=%s).",
                guild.id,
                target_channel_id,
            )
        except discord.DiscordException as exc:
            logging.warning(
                "Failed to post club portal to channel %s (guild=%s): %s",
                target_channel_id,
                guild.id,
                exc,
            )
