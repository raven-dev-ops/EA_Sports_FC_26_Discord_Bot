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
from services import entitlements_service
from services.fc25_stats_feature import fc25_stats_enabled
from services.fc25_stats_service import get_latest_snapshot, get_link
from services.recruitment_service import delete_recruit_profile, get_recruit_profile
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import delete_message, fetch_channel, send_message
from utils.embeds import DEFAULT_COLOR, SUCCESS_COLOR, make_embed
from utils.permissions import is_staff_user
from utils.role_routing import resolve_role_id


def _portal_footer() -> str:
    return f"Last refreshed: {discord.utils.format_dt(datetime.now(timezone.utc), style='R')}"


def build_recruit_portal_embed() -> discord.Embed:
    embed = make_embed(
        title="Recruitment Portal",
        description=(
            "**Create and manage your free agent profile.**\n"
            "- Set Availability to publish to listings.\n"
            "- Keep positions/archetypes consistent for search.\n"
            "- Toggle Retirement when you are inactive.\n\n"
            "Use the action menu below. Responses are ephemeral."
        ),
        color=DEFAULT_COLOR,
        footer=_portal_footer(),
    )
    embed.add_field(
        name="Pro features",
        value="- FC25 stats linking + rich embeds are Pro-only for this server.",
        inline=False,
    )
    return embed


def build_recruit_help_embed() -> discord.Embed:
    return make_embed(
        title="Recruitment Help",
        description=(
            "**Tips**\n"
            "- Set Availability to publish your listing.\n"
            "- Keep positions/archetypes consistent so coaches can filter/search.\n"
            "- Avoid invites or mass mentions in notes.\n"
            "- Update your profile whenever availability changes.\n"
            "- Profile edits are rate-limited to prevent spam."
        ),
        color=DEFAULT_COLOR,
    )


class RecruitPortalView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        options = [
            discord.SelectOption(
                label="Register / Edit",
                value="register_edit",
                description="Create or update your profile",
            ),
            discord.SelectOption(
                label="Preview",
                value="preview",
                description="See your listing embed",
            ),
            discord.SelectOption(
                label="Availability",
                value="availability",
                description="Set days and hours",
            ),
            discord.SelectOption(
                label="Retirement",
                value="retirement",
                description="Toggle inactive status",
            ),
            discord.SelectOption(
                label="Link FC25 Stats",
                value="link_fc25",
                description="Connect your FC25 stats",
            ),
            discord.SelectOption(
                label="Refresh FC25 Stats",
                value="refresh_fc25",
                description="Refresh your FC25 snapshot",
            ),
            discord.SelectOption(
                label="Unlink FC25 Stats",
                value="unlink_fc25",
                description="Remove FC25 stats link",
            ),
            discord.SelectOption(
                label="Unregister",
                value="unregister",
                description="Delete your profile",
            ),
            discord.SelectOption(
                label="Help",
                value="help",
                description="Guidance and tips",
            ),
            discord.SelectOption(
                label="Repost Portal",
                value="repost",
                description="Staff-only portal cleanup",
            ),
        ]
        self.action_select = discord.ui.Select(
            placeholder="Select a recruitment action...",
            options=options,
        )
        self.action_select.callback = self.on_action_select
        self.add_item(self.action_select)

    async def on_action_select(self, interaction: discord.Interaction) -> None:
        selection = self.action_select.values[0] if self.action_select.values else ""
        if selection == "register_edit":
            await self._register_edit(interaction)
        elif selection == "preview":
            await self._preview(interaction)
        elif selection == "availability":
            await self._availability(interaction)
        elif selection == "retirement":
            await self._toggle_retired(interaction)
        elif selection == "link_fc25":
            await self._link_fc25_stats(interaction)
        elif selection == "refresh_fc25":
            await self._refresh_fc25_stats(interaction)
        elif selection == "unlink_fc25":
            await self._unlink_fc25_stats(interaction)
        elif selection == "unregister":
            await self._unregister(interaction)
        elif selection == "help":
            await self._help(interaction)
        elif selection == "repost":
            await self._repost_portal(interaction)
        else:
            await interaction.response.send_message(
                "Select a valid action.",
                ephemeral=True,
            )

    async def _register_edit(self, interaction: discord.Interaction) -> None:
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

    async def _preview(self, interaction: discord.Interaction) -> None:
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
        settings = getattr(interaction.client, "settings", None)
        if settings is not None:
            try:
                entitlements_service.require_feature(
                    settings,
                    guild_id=guild.id,
                    feature_key=entitlements_service.FEATURE_FC25_STATS,
                )
            except PermissionError:
                await interaction.response.send_message(
                    "Free agent profiles with FC stats and rich embeds are available on the Pro plan for this server.",
                    ephemeral=True,
                )
                return
        if not profile:
            await interaction.response.send_message(
                "No profile found yet. Use Register / Edit first.",
                ephemeral=True,
            )
            return
        fc25_link = None
        fc25_snapshot = None
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

    async def _availability(self, interaction: discord.Interaction) -> None:
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
        try:
            entitlements_service.require_feature(
                settings,
                guild_id=guild.id,
                feature_key=entitlements_service.FEATURE_FC25_STATS,
            )
        except PermissionError:
            await interaction.response.send_message(
                "Recruit availability scheduling is available on the Pro plan for this server.",
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

    async def _toggle_retired(self, interaction: discord.Interaction) -> None:
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

        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None:
            try:
                member = await guild.fetch_member(interaction.user.id)
            except discord.DiscordException:
                await interaction.response.send_message(
                    "Could not resolve your guild membership.",
                    ephemeral=True,
                )
                return

        retired_role_id = resolve_role_id(settings, guild_id=guild.id, field="role_retired_id")
        if not retired_role_id:
            await interaction.response.send_message(
                "Retirement role is not configured for this server.",
                ephemeral=True,
            )
            return

        role = guild.get_role(retired_role_id)
        if role is None:
            await interaction.response.send_message(
                "Retirement role could not be found on this server.",
                ephemeral=True,
            )
            return

        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "Bot is missing `Manage Roles` and cannot toggle retirement.",
                ephemeral=True,
            )
            return
        if not _can_manage_role(bot_member, role):
            await interaction.response.send_message(
                "Bot cannot manage the Retired role. Move the bot role above it and try again.",
                ephemeral=True,
            )
            return

        if role in member.roles:
            try:
                await member.remove_roles(role, reason="Offside: player retirement toggle (active)")
            except discord.DiscordException:
                await interaction.response.send_message(
                    "Could not remove the Retired role. Please contact staff.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                embed=make_embed(
                    title="Welcome back",
                    description="You are now **Active**. The Retired role has been removed.",
                    color=SUCCESS_COLOR,
                ),
                ephemeral=True,
            )
            return

        try:
            await member.add_roles(role, reason="Offside: player retirement toggle (inactive)")
        except discord.DiscordException:
            await interaction.response.send_message(
                "Could not add the Retired role. Please contact staff.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=make_embed(
                title="Marked as retired",
                description=(
                    "You are now **Retired** (inactive) and Offside interactions are disabled.\n"
                    "Use the Retirement button again to become active."
                ),
                color=SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def _link_fc25_stats(self, interaction: discord.Interaction) -> None:
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

    async def _unlink_fc25_stats(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is not None:
            logging.info(
                "Recruit portal action=unlink_fc25_stats guild=%s user=%s",
                guild.id,
                interaction.user.id,
            )
        await unlink_fc25_stats(interaction)

    async def _refresh_fc25_stats(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is not None:
            logging.info(
                "Recruit portal action=refresh_fc25_stats guild=%s user=%s",
                guild.id,
                interaction.user.id,
            )
        await refresh_fc25_stats(interaction)

    async def _unregister(self, interaction: discord.Interaction) -> None:
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

    async def _help(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=build_recruit_help_embed(),
            ephemeral=True,
        )

    async def _repost_portal(self, interaction: discord.Interaction) -> None:
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

        embed = build_recruit_portal_embed()
        view = RecruitPortalView()
        try:
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


def _can_manage_role(bot_member: discord.Member, role: discord.Role) -> bool:
    if bot_member.guild_permissions.administrator:
        return True
    try:
        return role < bot_member.top_role
    except TypeError:
        return role.position < bot_member.top_role.position
