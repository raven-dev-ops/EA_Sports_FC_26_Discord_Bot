from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import edit_message, fetch_channel, send_message
from utils.embeds import DEFAULT_COLOR, make_embed


def _footer() -> str:
    return f"Updated: {discord.utils.format_dt(datetime.now(timezone.utc), style='R')}"


def _format_channel_ref(channel_id: int | None, *, fallback_name: str) -> str:
    if channel_id:
        return f"<#{channel_id}>"
    return f"`#{fallback_name}`"


def _build_listing_about_embed(
    *,
    title: str,
    description: str,
    portal_ref: str,
) -> discord.Embed:
    embed = make_embed(
        title=title,
        description=description,
        color=DEFAULT_COLOR,
        footer=_footer(),
    )
    embed.add_field(
        name="Where to take action",
        value=portal_ref,
        inline=False,
    )
    embed.add_field(
        name="Chat policy",
        value="This channel is read-only to keep listings clean.",
        inline=False,
    )
    return embed


async def _upsert_pinned_embed(
    bot: discord.Client,
    channel: discord.TextChannel,
    *,
    embed: discord.Embed,
    legacy_titles: list[str] | None = None,
) -> None:
    bot_user = bot.user
    if bot_user is None:
        return
    desired_title = embed.title
    if not desired_title:
        return
    match_titles = {desired_title}
    if legacy_titles:
        match_titles.update(legacy_titles)

    async def _update_existing(message: discord.Message) -> None:
        await edit_message(
            message,
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        if not message.pinned:
            try:
                await message.pin(reason="Offside: listing channel instructions")
            except discord.DiscordException:
                logging.info("Could not pin listing instructions in channel %s.", channel.id)

    try:
        pinned = await channel.pins()
    except discord.DiscordException:
        pinned = []

    for pinned_message in pinned:
        if pinned_message.author.id != bot_user.id:
            continue
        if not pinned_message.embeds or pinned_message.embeds[0].title not in match_titles:
            continue
        await _update_existing(pinned_message)
        return

    try:
        async for history_message in channel.history(limit=50):
            if history_message.author.id != bot_user.id:
                continue
            if not history_message.embeds or history_message.embeds[0].title not in match_titles:
                continue
            await _update_existing(history_message)
            return
    except discord.DiscordException:
        pass

    created = await send_message(
        channel,
        embed=embed,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    if created is None:
        return
    try:
        await created.pin(reason="Offside: listing channel instructions")
    except discord.DiscordException:
        logging.info("Could not pin listing instructions in channel %s.", channel.id)


async def post_listing_channel_instructions(
    bot: discord.Client,
    *,
    guilds: list[discord.Guild] | None = None,
) -> None:
    settings = getattr(bot, "settings", None)
    if settings is None:
        return
    if bool(getattr(bot, "test_mode", False)):
        return

    target_guilds = bot.guilds if guilds is None else guilds
    for guild in target_guilds:
        coach_portal_id = resolve_channel_id(
            settings,
            guild_id=guild.id,
            field="channel_coach_portal_id",
            test_mode=False,
        )
        recruit_portal_id = resolve_channel_id(
            settings,
            guild_id=guild.id,
            field="channel_recruit_portal_id",
            test_mode=False,
        )
        manager_portal_id = resolve_channel_id(
            settings,
            guild_id=guild.id,
            field="channel_manager_portal_id",
            test_mode=False,
        )

        listing_specs = [
            (
                "channel_roster_listing_id",
                "roster-listing",
                _build_listing_about_embed(
                    title="About: roster-listing",
                    description="Approved rosters are posted here automatically.",
                    portal_ref=_format_channel_ref(coach_portal_id, fallback_name="coach-portal"),
                ),
            ),
            (
                "channel_recruit_listing_id",
                "recruitment-boards",
                _build_listing_about_embed(
                    title="About: recruitment-boards",
                    description="Recruit profiles are posted here automatically when a player registers/updates.",
                    portal_ref=_format_channel_ref(recruit_portal_id, fallback_name="recruit-portal"),
                ),
            ),
            (
                "channel_club_listing_id",
                "club-listing",
                _build_listing_about_embed(
                    title="About: club-listing",
                    description="Club ads are posted here automatically when a club registers/updates.",
                    portal_ref="Contact staff to submit a club ad.",
                ),
            ),
            (
                "channel_premium_coaches_id",
                "pro-coaches",
                _build_listing_about_embed(
                    title="About: pro-coaches",
                    description="Pro coach listings are managed by the bot (openings/practice times).",
                    portal_ref=_format_channel_ref(manager_portal_id, fallback_name="managers-portal"),
                ),
            ),
        ]

        for field, fallback_name, embed in listing_specs:
            channel_id = resolve_channel_id(
                settings,
                guild_id=guild.id,
                field=field,
                test_mode=False,
            )
            if not channel_id:
                continue
            channel = await fetch_channel(bot, channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                await _upsert_pinned_embed(
                    bot,
                    channel,
                    embed=embed,
                    legacy_titles=(
                        ["About: premium-coaches"]
                        if fallback_name == "pro-coaches"
                        else ["About: recruit-listing"]
                        if fallback_name == "recruitment-boards"
                        else None
                    ),
                )
            except Exception:
                logging.exception("Failed to upsert listing instructions (guild=%s channel=%s).", guild.id, channel_id)
