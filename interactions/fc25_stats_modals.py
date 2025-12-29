from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

from config import Settings
from interactions.modals import SafeModal
from interactions.recruit_posts import upsert_recruit_profile_posts
from services.fc25_stats_client import (
    FC25NotFound,
    FC25ParseError,
    FC25RateLimited,
    FC25TransientError,
)
from services.fc25_stats_feature import fc25_stats_enabled
from services.fc25_stats_gateway import FC25StatsGateway
from services.fc25_stats_service import (
    delete_link,
    delete_snapshots,
    get_link,
    save_snapshot,
    upsert_link,
)
from services.recruitment_service import get_recruit_profile, update_recruit_profile_posts
from utils.channel_routing import resolve_channel_id
from utils.cooldowns import Cooldown
from utils.discord_wrappers import fetch_channel, send_message
from utils.fc25 import parse_club_id_from_url, platform_key_from_user_input
from utils.validation import ensure_safe_text


def _get_gateway(client: discord.Client, settings: Settings) -> FC25StatsGateway:
    existing = getattr(client, "_fc25_stats_gateway", None)
    if isinstance(existing, FC25StatsGateway) and getattr(existing, "settings", None) == settings:
        return existing
    gateway = FC25StatsGateway(settings=settings)
    setattr(client, "_fc25_stats_gateway", gateway)
    return gateway


FC25_REFRESH_COOLDOWN = Cooldown(seconds=120.0)


class LinkFC25StatsModal(SafeModal, title="Link FC25 Clubs Stats"):
    platform: discord.ui.TextInput = discord.ui.TextInput(
        label="Platform (PC/PS5, optional)",
        required=False,
        max_length=16,
        placeholder="Leave blank for default",
    )
    club_id_or_url: discord.ui.TextInput = discord.ui.TextInput(
        label="Club ID or club URL",
        max_length=200,
        placeholder="Paste a club URL or numeric club ID",
    )
    member_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Member name (in-game)",
        max_length=32,
        placeholder="Exact in-game member name",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This flow must be used in a guild.",
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

        club_id = parse_club_id_from_url(self.club_id_or_url.value or "")
        if club_id is None:
            await interaction.response.send_message(
                "Could not parse a club ID from that input.",
                ephemeral=True,
            )
            return

        try:
            member_name = ensure_safe_text(self.member_name.value, max_length=32)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        platform_key = platform_key_from_user_input(
            self.platform.value,
            default=settings.fc25_default_platform,
        )
        if platform_key is None:
            await interaction.response.send_message(
                "Platform must be PC or PS5 (or leave blank).",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        gateway = _get_gateway(interaction.client, settings)
        try:
            result = await gateway.get_members_career_stats(
                guild_id=guild.id,
                user_id=interaction.user.id,
                platform_key=platform_key,
                club_id=club_id,
            )
        except FC25RateLimited as exc:
            retry = exc.retry_after_seconds
            if retry is None:
                msg = "Rate limited by the FC25 Clubs API. Please try again in a few minutes."
            else:
                msg = f"Rate limited by the FC25 Clubs API. Try again in ~{int(retry)}s."
            await interaction.followup.send(msg, ephemeral=True)
            await _staff_log(
                interaction,
                settings,
                (
                    f"FC25 link attempt: user=<@{interaction.user.id}> platform={platform_key} "
                    f"club_id={club_id} status=rate_limited retry_after={retry}"
                ),
            )
            return
        except FC25NotFound:
            await interaction.followup.send(
                "Club not found. Double-check the club ID and platform, then try again.",
                ephemeral=True,
            )
            await _staff_log(
                interaction,
                settings,
                (
                    f"FC25 link attempt: user=<@{interaction.user.id}> platform={platform_key} "
                    f"club_id={club_id} status=club_not_found"
                ),
            )
            return
        except (FC25TransientError, FC25ParseError):
            await interaction.followup.send(
                "FC25 stats are temporarily unavailable. Please try again later.",
                ephemeral=True,
            )
            await _staff_log(
                interaction,
                settings,
                (
                    f"FC25 link attempt: user=<@{interaction.user.id}> platform={platform_key} "
                    f"club_id={club_id} status=unavailable"
                ),
            )
            return
        except Exception:
            await interaction.followup.send(
                "Failed to fetch club stats due to an unexpected error.",
                ephemeral=True,
            )
            await _staff_log(
                interaction,
                settings,
                (
                    f"FC25 link attempt: user=<@{interaction.user.id}> platform={platform_key} "
                    f"club_id={club_id} status=error"
                ),
            )
            return

        member_key, member_stats = _find_member(result.data, member_name)
        if member_key is None:
            await interaction.followup.send(
                "Could not verify that member name in the club stats response.",
                ephemeral=True,
            )
            await _staff_log(
                interaction,
                settings,
                (
                    f"FC25 link attempt: user=<@{interaction.user.id}> platform={platform_key} "
                    f"club_id={club_id} status=member_not_found"
                ),
            )
            return

        club_name = _extract_club_name(result.data)
        now = datetime.now(timezone.utc)
        upsert_link(
            guild.id,
            interaction.user.id,
            platform_key=platform_key,
            club_id=club_id,
            club_name=club_name,
            member_name=member_key,
            verified=True,
            verified_at=now,
            last_fetched_at=now,
            last_fetch_status="ok",
        )
        save_snapshot(
            guild.id,
            interaction.user.id,
            platform_key=platform_key,
            club_id=club_id,
            snapshot={
                "club_name": club_name,
                "member_name": member_key,
                "member_stats": member_stats,
            },
            fetched_at=now,
        )

        profile = None
        try:
            profile = get_recruit_profile(guild.id, interaction.user.id)
        except Exception:
            profile = None
        if profile:
            test_mode = bool(getattr(interaction.client, "test_mode", False))
            try:
                refs = await upsert_recruit_profile_posts(
                    interaction.client,
                    settings=settings,
                    guild_id=guild.id,
                    profile=profile,
                    test_mode=test_mode,
                )
                update_recruit_profile_posts(
                    guild.id,
                    interaction.user.id,
                    listing_channel_id=refs.get("listing_channel_id"),
                    listing_message_id=refs.get("listing_message_id"),
                    staff_channel_id=refs.get("staff_channel_id"),
                    staff_message_id=refs.get("staff_message_id"),
                )
            except Exception:
                pass

        await _staff_log(
            interaction,
            settings,
            (
                f"FC25 stats linked: user=<@{interaction.user.id}> platform={platform_key} club_id={club_id} "
                f"member_name={member_key} status=verified"
            ),
        )
        await interaction.followup.send(
            "FC25 stats linked and verified.",
            ephemeral=True,
        )


async def refresh_fc25_stats(interaction: discord.Interaction) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "This flow must be used in a guild.",
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

    cooldown = FC25_REFRESH_COOLDOWN.check(f"fc25_refresh:{guild.id}:{interaction.user.id}")
    if not cooldown.allowed:
        retry = cooldown.retry_after_seconds
        retry_text = f" Try again in ~{int(retry)}s." if retry is not None else ""
        await interaction.response.send_message(
            f"You're refreshing too quickly.{retry_text}",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    test_mode = bool(getattr(interaction.client, "test_mode", False))
    status = await refresh_fc25_stats_for_user(
        interaction.client,
        settings,
        guild_id=guild.id,
        user_id=interaction.user.id,
        test_mode=test_mode,
        reason="manual",
    )
    if status == "not_linked":
        await interaction.followup.send(
            "No linked FC25 stats found. Use Link FC25 Stats first.",
            ephemeral=True,
        )
        return
    if status == "cached":
        await interaction.followup.send(
            "Stats are already fresh (served from cache).",
            ephemeral=True,
        )
        return
    if status == "refreshed":
        await interaction.followup.send(
            "Verified stats refreshed.",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        "Failed to refresh stats. Please try again later.",
        ephemeral=True,
    )


async def refresh_fc25_stats_for_user(
    client: discord.Client,
    settings: Settings,
    *,
    guild_id: int,
    user_id: int,
    test_mode: bool,
    reason: str,
) -> str:
    link = None
    try:
        link = get_link(guild_id, user_id)
    except Exception:
        link = None
    if not link:
        return "not_linked"

    platform_key = link.get("platform_key")
    club_id = link.get("club_id")
    member_name = link.get("member_name")
    if not isinstance(platform_key, str) or not isinstance(club_id, int) or not isinstance(member_name, str):
        return "invalid_link"

    gateway = _get_gateway(client, settings)
    try:
        result = await gateway.get_members_career_stats(
            guild_id=guild_id,
            user_id=user_id,
            platform_key=platform_key,
            club_id=club_id,
        )
    except FC25RateLimited as exc:
        await _staff_log_client(
            client,
            settings,
            guild_id=guild_id,
            test_mode=test_mode,
            message=(
                f"FC25 refresh: user=<@{user_id}> platform={platform_key} club_id={club_id} "
                f"status=rate_limited retry_after={exc.retry_after_seconds} reason={reason}"
            ),
        )
        return "rate_limited"
    except FC25NotFound:
        await _staff_log_client(
            client,
            settings,
            guild_id=guild_id,
            test_mode=test_mode,
            message=(
                f"FC25 refresh: user=<@{user_id}> platform={platform_key} club_id={club_id} "
                f"status=club_not_found reason={reason}"
            ),
        )
        return "not_found"
    except (FC25TransientError, FC25ParseError):
        await _staff_log_client(
            client,
            settings,
            guild_id=guild_id,
            test_mode=test_mode,
            message=(
                f"FC25 refresh: user=<@{user_id}> platform={platform_key} club_id={club_id} "
                f"status=unavailable reason={reason}"
            ),
        )
        return "unavailable"
    except Exception:
        await _staff_log_client(
            client,
            settings,
            guild_id=guild_id,
            test_mode=test_mode,
            message=(
                f"FC25 refresh: user=<@{user_id}> platform={platform_key} club_id={club_id} "
                f"status=error reason={reason}"
            ),
        )
        return "error"

    member_key, member_stats = _find_member(result.data, member_name)
    if member_key is None:
        now = datetime.now(timezone.utc)
        try:
            upsert_link(
                guild_id,
                user_id,
                platform_key=platform_key,
                club_id=club_id,
                club_name=link.get("club_name"),
                member_name=str(member_name),
                verified=False,
                verified_at=None,
                last_fetched_at=now,
                last_fetch_status="member_not_found",
            )
        except Exception:
            pass
        await _staff_log_client(
            client,
            settings,
            guild_id=guild_id,
            test_mode=test_mode,
            message=(
                f"FC25 refresh: user=<@{user_id}> platform={platform_key} club_id={club_id} "
                f"status=member_not_found reason={reason}"
            ),
        )
        return "member_not_found"

    if result.from_cache:
        return "cached"

    club_name = _extract_club_name(result.data) or link.get("club_name")
    now = datetime.now(timezone.utc)
    verified_at = link.get("verified_at") if link.get("verified") else None
    if not isinstance(verified_at, datetime):
        verified_at = now

    try:
        upsert_link(
            guild_id,
            user_id,
            platform_key=platform_key,
            club_id=club_id,
            club_name=club_name,
            member_name=member_key,
            verified=True,
            verified_at=verified_at,
            last_fetched_at=now,
            last_fetch_status="ok",
        )
        save_snapshot(
            guild_id,
            user_id,
            platform_key=platform_key,
            club_id=club_id,
            snapshot={
                "club_name": club_name,
                "member_name": member_key,
                "member_stats": member_stats,
            },
            fetched_at=now,
        )
    except Exception:
        await _staff_log_client(
            client,
            settings,
            guild_id=guild_id,
            test_mode=test_mode,
            message=(
                f"FC25 refresh: user=<@{user_id}> platform={platform_key} club_id={club_id} "
                f"status=db_error reason={reason}"
            ),
        )
        return "db_error"

    profile = None
    try:
        profile = get_recruit_profile(guild_id, user_id)
    except Exception:
        profile = None
    if profile:
        try:
            refs = await upsert_recruit_profile_posts(
                client,
                settings=settings,
                guild_id=guild_id,
                profile=profile,
                test_mode=test_mode,
            )
            update_recruit_profile_posts(
                guild_id,
                user_id,
                listing_channel_id=refs.get("listing_channel_id"),
                listing_message_id=refs.get("listing_message_id"),
                staff_channel_id=refs.get("staff_channel_id"),
                staff_message_id=refs.get("staff_message_id"),
            )
        except Exception:
            pass

    await _staff_log_client(
        client,
        settings,
        guild_id=guild_id,
        test_mode=test_mode,
        message=(
            f"FC25 refresh: user=<@{user_id}> platform={platform_key} club_id={club_id} "
            f"status=refreshed reason={reason}"
        ),
    )
    return "refreshed"


async def unlink_fc25_stats(interaction: discord.Interaction) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "This flow must be used in a guild.",
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

    await interaction.response.defer(ephemeral=True)
    existing_link = None
    try:
        existing_link = get_link(guild.id, interaction.user.id)
    except Exception:
        existing_link = None
    deleted_link = False
    try:
        deleted_link = delete_link(guild.id, interaction.user.id)
        delete_snapshots(guild.id, interaction.user.id)
    except Exception:
        deleted_link = False

    profile = None
    try:
        profile = get_recruit_profile(guild.id, interaction.user.id)
    except Exception:
        profile = None
    if profile:
        test_mode = bool(getattr(interaction.client, "test_mode", False))
        try:
            refs = await upsert_recruit_profile_posts(
                interaction.client,
                settings=settings,
                guild_id=guild.id,
                profile=profile,
                test_mode=test_mode,
            )
            update_recruit_profile_posts(
                guild.id,
                interaction.user.id,
                listing_channel_id=refs.get("listing_channel_id"),
                listing_message_id=refs.get("listing_message_id"),
                staff_channel_id=refs.get("staff_channel_id"),
                staff_message_id=refs.get("staff_message_id"),
            )
        except Exception:
            pass

    await _staff_log(
        interaction,
        settings,
        (
            f"FC25 stats unlinked: user=<@{interaction.user.id}> platform={existing_link.get('platform_key') if existing_link else None} "
            f"club_id={existing_link.get('club_id') if existing_link else None} status=unlinked deleted_link={deleted_link}"
        ),
    )
    await interaction.followup.send(
        "FC25 stats unlinked.",
        ephemeral=True,
    )


def _normalize_name(value: str) -> str:
    return value.strip().casefold()


def _find_member(data: dict[str, Any], member_name: str) -> tuple[str | None, dict[str, Any] | None]:
    target = _normalize_name(member_name)
    members = data.get("members")
    if isinstance(members, dict):
        for key, value in members.items():
            if _normalize_name(str(key)) == target:
                return str(key), value if isinstance(value, dict) else None
            if isinstance(value, dict):
                name = value.get("name") or value.get("memberName") or value.get("playername")
                if name and _normalize_name(str(name)) == target:
                    return str(name), value
    if isinstance(members, list):
        for value in members:
            if not isinstance(value, dict):
                continue
            name = value.get("name") or value.get("memberName") or value.get("playername")
            if name and _normalize_name(str(name)) == target:
                return str(name), value
    return None, None


def _extract_club_name(data: dict[str, Any]) -> str | None:
    for key in ("clubName", "name"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    info = data.get("clubInfo")
    if isinstance(info, dict):
        name = info.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


async def _staff_log(interaction: discord.Interaction, settings: Settings, message: str) -> None:
    test_mode = bool(getattr(interaction.client, "test_mode", False))
    await _staff_log_client(
        interaction.client,
        settings,
        guild_id=getattr(interaction.guild, "id", None),
        test_mode=test_mode,
        message=message,
    )


async def _staff_log_client(
    client: discord.Client,
    settings: Settings,
    *,
    guild_id: int | None,
    test_mode: bool,
    message: str,
) -> None:
    staff_channel_id = resolve_channel_id(
        settings,
        guild_id=guild_id,
        field="channel_staff_portal_id",
        test_mode=test_mode,
    )
    if not staff_channel_id:
        return
    channel = await fetch_channel(client, staff_channel_id)
    if channel is None:
        return
    await send_message(
        channel,
        message,
        allowed_mentions=discord.AllowedMentions.none(),
    )
