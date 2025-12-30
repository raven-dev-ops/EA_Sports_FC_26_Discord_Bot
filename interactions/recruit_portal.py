from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from interactions.fc25_stats_modals import (
    LinkFC25StatsModal,
    refresh_fc25_stats,
    unlink_fc25_stats,
)
from interactions.modals import RecruitProfileModalStep1
from interactions.recruit_availability import RecruitAvailabilityView
from interactions.recruit_embeds import build_recruit_profile_embed
from interactions.views import SafeView
from services.fc25_stats_feature import fc25_stats_enabled
from services.fc25_stats_service import get_latest_snapshot, get_link
from services.recruitment_service import delete_recruit_profile, get_recruit_profile
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import delete_message, fetch_channel, send_message
from utils.embeds import DEFAULT_COLOR, SUCCESS_COLOR, make_embed
from utils.permissions import is_staff_user


def _portal_footer() -> str:
    return f"Last refreshed: {discord.utils.format_dt(datetime.now(timezone.utc), style='R')}"


def build_recruit_intro_embed() -> discord.Embed:
    return make_embed(
        title="Recruitment Portal Overview",
        description=(
            "**Purpose**\n"
            "Create a recruit profile so clubs/coaches can find you.\n\n"
            "**Who should use this**\n"
            "- Players/recruits.\n\n"
            "**Key rules**\n"
            "- Set Availability to publish to the listing channel.\n"
            "- Keep positions/archetypes consistent so coaches can filter/search."
        ),
        color=DEFAULT_COLOR,
        footer=_portal_footer(),
    )


def build_recruit_portal_embed() -> discord.Embed:
    embed = make_embed(
        title="Recruitment Portal",
        description=(
            "Use the buttons below. All responses are ephemeral (only you can see them)."
        ),
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
        value="Shows what your listing embed will look like.",
        inline=False,
    )
    embed.add_field(
        name="Availability",
        value="Pick days and hours using a selector (no free text).",
        inline=False,
    )
    embed.add_field(
        name="Unregister",
        value="Deletes your stored profile and removes your listing posts when possible.",
        inline=False,
    )
    embed.add_field(
        name="Help",
        value="Guidance and tips for keeping your profile high-signal.",
        inline=False,
    )
    embed.add_field(
        name="Repost Portal (staff)",
        value="Clean up and repost this portal message set.",
        inline=False,
    )
    return embed


def build_recruit_help_embed() -> discord.Embed:
    return make_embed(
        title="Recruitment Help",
        description=(
            "Tips:\n"
            "- Set Availability to publish your listing.\n"
            "- Keep positions/archetypes consistent so coaches can filter/search.\n"
            "- Avoid putting invites or mass mentions in notes.\n"
            "- Update your profile whenever availability changes.\n"
            "- Profile edits are rate-limited to prevent spam."
        ),
        color=DEFAULT_COLOR,
    )


class RecruitPortalView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Register / Edit",
        style=discord.ButtonStyle.primary,
        custom_id="recruit:register_edit",
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
            "Recruit portal action=register_edit guild=%s user=%s",
            guild.id,
            interaction.user.id,
        )
        existing = None
        try:
            existing = get_recruit_profile(guild.id, interaction.user.id)
        except Exception:
            existing = None
        await interaction.response.send_modal(
            RecruitProfileModalStep1(existing_profile=existing)
        )

    @discord.ui.button(
        label="Preview",
        style=discord.ButtonStyle.secondary,
        custom_id="recruit:preview",
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
            "Recruit portal action=preview guild=%s user=%s",
            guild.id,
            interaction.user.id,
        )
        profile = None
        try:
            profile = get_recruit_profile(guild.id, interaction.user.id)
        except Exception:
            profile = None
        if not profile:
            await interaction.response.send_message(
                "No profile found yet. Use Register / Edit first.",
                ephemeral=True,
            )
            return
        fc25_link = None
        fc25_snapshot = None
        settings = getattr(interaction.client, "settings", None)
        if settings is not None and fc25_stats_enabled(settings, guild_id=guild.id):
            try:
                fc25_link = get_link(guild.id, interaction.user.id)
                if fc25_link:
                    fc25_snapshot = get_latest_snapshot(guild.id, interaction.user.id)
            except Exception:
                fc25_link = None
                fc25_snapshot = None
        await interaction.response.send_message(
            embed=build_recruit_profile_embed(
                profile,
                fc25_link=fc25_link,
                fc25_snapshot=fc25_snapshot,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Availability",
        style=discord.ButtonStyle.secondary,
        custom_id="recruit:availability",
    )
    async def availability(
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
            "Recruit portal action=availability guild=%s user=%s",
            guild.id,
            interaction.user.id,
        )
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.",
                ephemeral=True,
            )
            return
        profile = None
        try:
            profile = get_recruit_profile(guild.id, interaction.user.id)
        except Exception:
            profile = None
        if not profile:
            await interaction.response.send_message(
                "No profile found yet. Use Register / Edit first.",
                ephemeral=True,
            )
            return
        view = RecruitAvailabilityView(
            settings=settings,
            guild_id=guild.id,
            user_id=interaction.user.id,
            profile=profile,
        )
        await interaction.response.send_message(
            embed=view.build_embed(),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Link FC25 Stats",
        style=discord.ButtonStyle.secondary,
        custom_id="recruit:link_fc25_stats",
    )
    async def link_fc25_stats(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This portal must be used in a guild.",
                ephemeral=True,
            )
            return
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.",
                ephemeral=True,
            )
            return
        if not fc25_stats_enabled(settings, guild_id=guild.id):
            await interaction.response.send_message(
                "FC25 stats integration is disabled for this guild.",
                ephemeral=True,
            )
            return
        logging.info(
            "Recruit portal action=link_fc25_stats guild=%s user=%s",
            guild.id,
            interaction.user.id,
        )
        await interaction.response.send_modal(LinkFC25StatsModal())

    @discord.ui.button(
        label="Unlink FC25 Stats",
        style=discord.ButtonStyle.secondary,
        custom_id="recruit:unlink_fc25_stats",
    )
    async def unlink_fc25_stats_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        guild = interaction.guild
        if guild is not None:
            logging.info(
                "Recruit portal action=unlink_fc25_stats guild=%s user=%s",
                guild.id,
                interaction.user.id,
            )
        await unlink_fc25_stats(interaction)

    @discord.ui.button(
        label="Refresh FC25 Stats",
        style=discord.ButtonStyle.secondary,
        custom_id="recruit:refresh_fc25_stats",
    )
    async def refresh_fc25_stats_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        guild = interaction.guild
        if guild is not None:
            logging.info(
                "Recruit portal action=refresh_fc25_stats guild=%s user=%s",
                guild.id,
                interaction.user.id,
            )
        await refresh_fc25_stats(interaction)

    @discord.ui.button(
        label="Unregister",
        style=discord.ButtonStyle.danger,
        custom_id="recruit:unregister",
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
            "Recruit portal action=unregister guild=%s user=%s",
            guild.id,
            interaction.user.id,
        )

        profile = None
        try:
            profile = get_recruit_profile(guild.id, interaction.user.id)
        except Exception:
            profile = None
        if not profile:
            await interaction.response.send_message(
                "No profile found to delete.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        await _delete_profile_posts(interaction.client, profile)
        try:
            delete_recruit_profile(guild.id, interaction.user.id)
        except Exception:
            pass

        await interaction.followup.send(
            embed=make_embed(
                title="Profile removed",
                description="Your recruit profile has been deleted.",
                color=SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Help",
        style=discord.ButtonStyle.secondary,
        custom_id="recruit:help",
    )
    async def help(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_message(
            embed=build_recruit_help_embed(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Repost Portal (staff)",
        style=discord.ButtonStyle.secondary,
        custom_id="recruit:repost_portal",
    )
    async def repost_portal(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        settings = getattr(interaction.client, "settings", None)
        if not is_staff_user(interaction.user, settings):
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
                description="Cleaning up and reposting the recruitment portal now.",
                color=DEFAULT_COLOR,
            ),
            ephemeral=True,
        )
        await post_recruit_portal(interaction.client, guilds=[guild])


async def _delete_profile_posts(client: discord.Client, profile: dict) -> None:
    for channel_key, message_key in (
        ("listing_channel_id", "listing_message_id"),
        ("staff_channel_id", "staff_message_id"),
    ):
        channel_id = profile.get(channel_key)
        message_id = profile.get(message_key)
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


async def post_recruit_portal(
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
            field="channel_recruit_portal_id",
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
                        "Recruitment Portal",
                        "Recruitment Portal Overview",
                    }:
                        try:
                            await message.delete()
                        except discord.DiscordException:
                            pass
        except discord.DiscordException:
            pass

        intro_embed = build_recruit_intro_embed()
        embed = build_recruit_portal_embed()
        view = RecruitPortalView()
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
                "Posted recruit portal embed (guild=%s channel=%s).",
                guild.id,
                target_channel_id,
            )
        except discord.DiscordException as exc:
            logging.warning(
                "Failed to post recruit portal to channel %s (guild=%s): %s",
                target_channel_id,
                guild.id,
                exc,
            )
