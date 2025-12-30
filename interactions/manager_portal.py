from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from database import get_collection
from interactions.premium_coaches_report import (
    PREMIUM_PIN_ENABLED_KEY,
    force_rebuild_premium_coaches_report,
    upsert_premium_coaches_report,
)
from interactions.views import SafeView
from repositories.tournament_repo import ensure_active_cycle, ensure_cycle_by_name
from services.audit_service import (
    AUDIT_ACTION_CAP_SYNC_SKIPPED,
    AUDIT_ACTION_CAP_SYNCED,
    AUDIT_ACTION_TIER_CHANGED,
    AUDIT_ACTION_UNLOCKED,
    record_staff_action,
)
from services.guild_config_service import get_guild_config, set_guild_config
from services.roster_service import (
    ROSTER_STATUS_UNLOCKED,
    count_roster_players,
    delete_roster,
    get_latest_roster_for_coach,
    get_roster_for_coach,
    set_roster_status,
    update_roster_cap,
)
from services.submission_service import delete_submission_by_roster
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import fetch_channel, send_message
from utils.embeds import DEFAULT_COLOR, ERROR_COLOR, SUCCESS_COLOR, make_embed
from utils.permissions import is_staff_user
from utils.role_routing import resolve_role_id


def _portal_footer() -> str:
    return f"Last refreshed: {discord.utils.format_dt(datetime.now(timezone.utc), style='R')}"


def build_manager_intro_embed() -> discord.Embed:
    return make_embed(
        title="Club Managers Portal Overview",
        description=(
            "**Purpose**\n"
            "Manage coach tiers, roster unlocks, and premium coach listings.\n\n"
            "**Who should use this**\n"
            "- Staff / club managers only.\n\n"
            "**Key rules**\n"
            "- The bot needs `Manage Roles` for tier changes.\n"
            "- Cap downgrades will not reduce below current roster size."
        ),
        color=DEFAULT_COLOR,
        footer=_portal_footer(),
    )


def build_manager_embed() -> discord.Embed:
    embed = make_embed(
        title="Club Managers Control Panel",
        description="Use the buttons below. All responses are ephemeral (only you can see them).",
        color=DEFAULT_COLOR,
        footer=_portal_footer(),
    )
    embed.add_field(
        name="Set Coach Tier",
        value="Assign Coach / Premium / Premium+ to a coach and (optionally) sync their roster cap.",
        inline=False,
    )
    embed.add_field(
        name="Unlock Roster",
        value="Unlock a coach roster for edits after rejection (clears stale submissions).",
        inline=False,
    )
    embed.add_field(
        name="Refresh Premium Coaches",
        value="Update the Premium Coaches report embed.",
        inline=False,
    )
    embed.add_field(
        name="Toggle Premium Pin",
        value="Pin/unpin the Premium Coaches embed (if the bot has permission).",
        inline=False,
    )
    embed.add_field(
        name="Force Rebuild Premium",
        value="Delete stale bot messages in the Premium Coaches channel and rebuild the report.",
        inline=False,
    )
    embed.add_field(
        name="Sync Caps (Active Cycle)",
        value="Sync all active rosters' caps to match coach tier roles (safe downgrade rules apply).",
        inline=False,
    )
    embed.add_field(
        name="Delete Roster",
        value="Delete a roster (administrator-only; last resort).",
        inline=False,
    )
    embed.add_field(
        name="Repost Portal (staff)",
        value="Clean up and repost this portal message set.",
        inline=False,
    )
    return embed


def _parse_discord_id(value: str) -> int | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        return int(cleaned)
    for part in ("<@", ">", "!"):
        cleaned = cleaned.replace(part, "")
    cleaned = cleaned.strip()
    return int(cleaned) if cleaned.isdigit() else None


def _tier_to_cap(tier: str) -> int | None:
    normalized = tier.strip().casefold()
    if normalized in {"coach", "standard", "base"}:
        return 16
    if normalized in {"premium", "coach premium"}:
        return 22
    if normalized in {"premium+", "premium plus", "coach premium+", "coach premium plus"}:
        return 25
    return None


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off", ""}:
            return False
    return False


def _desired_cap_for_member(
    member: discord.Member,
    *,
    coach_role_id: int | None,
    premium_role_id: int | None,
    premium_plus_role_id: int | None,
) -> int | None:
    role_ids = {role.id for role in member.roles}
    if premium_plus_role_id and premium_plus_role_id in role_ids:
        return 25
    if premium_role_id and premium_role_id in role_ids:
        return 22
    if coach_role_id and coach_role_id in role_ids:
        return 16
    return None


async def _fetch_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.DiscordException:
        return None


async def _set_coach_tier(
    interaction: discord.Interaction,
    *,
    coach_id: int,
    tier: str,
) -> tuple[bool, str]:
    guild = interaction.guild
    if guild is None:
        return False, "This action must be used in a guild."

    settings = getattr(interaction.client, "settings", None)
    if settings is None:
        return False, "Bot configuration is not loaded."

    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        return False, "I need the `Manage Roles` permission to assign coach tier roles."

    coach_role_id = resolve_role_id(settings, guild_id=guild.id, field="role_coach_id")
    premium_role_id = resolve_role_id(settings, guild_id=guild.id, field="role_coach_premium_id")
    premium_plus_role_id = resolve_role_id(
        settings, guild_id=guild.id, field="role_coach_premium_plus_id"
    )
    if not coach_role_id or not premium_role_id or not premium_plus_role_id:
        return (
            False,
            "Coach tier roles are not configured yet. Ensure the bot has `Manage Roles` and MongoDB is configured, then restart the bot.",
        )

    member = await _fetch_member(guild, coach_id)
    if member is None:
        return False, "Coach not found in this server."

    desired_cap = _tier_to_cap(tier)
    if desired_cap is None:
        return False, "Tier must be one of: Coach, Premium, Premium+."

    tier_role_id: int
    if desired_cap == 16:
        tier_role_id = coach_role_id
    elif desired_cap == 22:
        tier_role_id = premium_role_id
    else:
        tier_role_id = premium_plus_role_id

    tier_role = guild.get_role(tier_role_id)
    if tier_role is None:
        return (
            False,
            "Tier role not found. Ensure the bot has `Manage Roles` and MongoDB is configured, then restart the bot.",
        )

    remove_ids = {coach_role_id, premium_role_id, premium_plus_role_id} - {tier_role_id}
    to_remove = [r for r in member.roles if r.id in remove_ids]

    try:
        if to_remove:
            await member.remove_roles(*to_remove, reason="Offside: set coach tier")
        if tier_role not in member.roles:
            await member.add_roles(tier_role, reason="Offside: set coach tier")
    except discord.Forbidden:
        return False, "I couldn't edit this member's roles (role hierarchy / permissions)."
    except discord.DiscordException:
        return False, "Failed to update roles due to a Discord API error."

    if not settings.mongodb_uri:
        return True, f"Updated tier role for <@{coach_id}>. (MongoDB not configured; roster cap not synced.)"

    try:
        # Best-effort: sync roster cap to match the tier.
        roster = get_roster_for_coach(coach_id)
        if roster is None:
            return True, f"Updated tier role for <@{coach_id}>. No roster found to sync."

        record_staff_action(
            roster_id=roster["_id"],
            action=AUDIT_ACTION_TIER_CHANGED,
            staff_discord_id=interaction.user.id,
            staff_display_name=getattr(interaction.user, "display_name", None),
            staff_username=str(interaction.user),
            details={
                "coach_discord_id": coach_id,
                "tier": tier_role.name,
                "desired_cap": desired_cap,
            },
        )

        current_count = count_roster_players(roster["_id"])
        current_cap = roster.get("cap")
        if isinstance(current_cap, int) and desired_cap < current_count:
            record_staff_action(
                roster_id=roster["_id"],
                action=AUDIT_ACTION_CAP_SYNC_SKIPPED,
                staff_discord_id=interaction.user.id,
                staff_display_name=getattr(interaction.user, "display_name", None),
                staff_username=str(interaction.user),
                details={
                    "from_cap": current_cap,
                    "to_cap": desired_cap,
                    "player_count": current_count,
                    "reason": "tier_change",
                },
            )
            return True, (
                f"Updated tier role for <@{coach_id}>, but did not reduce roster cap below current "
                f"player count ({current_count}). Remove players, then re-run Sync Caps."
            )

        if isinstance(current_cap, int) and current_cap != desired_cap:
            update_roster_cap(roster["_id"], desired_cap)
            record_staff_action(
                roster_id=roster["_id"],
                action=AUDIT_ACTION_CAP_SYNCED,
                staff_discord_id=interaction.user.id,
                staff_display_name=getattr(interaction.user, "display_name", None),
                staff_username=str(interaction.user),
                details={
                    "from_cap": current_cap,
                    "to_cap": desired_cap,
                    "player_count": current_count,
                    "reason": "tier_change",
                },
            )

        return True, f"Updated tier role for <@{coach_id}> and synced roster cap to {desired_cap}."
    except Exception:
        return True, f"Updated tier role for <@{coach_id}>. (DB unavailable; roster cap not synced.)"


async def _unlock_roster(
    interaction: discord.Interaction,
    *,
    coach_id: int,
    tournament: str | None,
) -> tuple[bool, str]:
    settings = getattr(interaction.client, "settings", None)
    if settings is None:
        return False, "Bot configuration is not loaded."

    roster = None
    cycle_name = None
    if tournament:
        cycle_doc = ensure_cycle_by_name(tournament.strip())
        roster = get_roster_for_coach(coach_id, cycle_id=cycle_doc["_id"])
        cycle_name = cycle_doc.get("name")
    else:
        roster = get_roster_for_coach(coach_id)

    if roster is None and tournament is None:
        roster = get_latest_roster_for_coach(coach_id)
        cycle_name = None

    if roster is None:
        return False, "Roster not found for that coach."

    try:
        set_roster_status(
            roster["_id"],
            ROSTER_STATUS_UNLOCKED,
            expected_updated_at=roster.get("updated_at"),
        )
    except RuntimeError as exc:
        return False, str(exc)

    submission = delete_submission_by_roster(roster["_id"])
    if submission:
        channel_id = submission.get("staff_channel_id")
        message_id = submission.get("staff_message_id")
        if isinstance(channel_id, int) and isinstance(message_id, int):
            channel = await fetch_channel(interaction.client, channel_id)
            if channel and hasattr(channel, "fetch_message"):
                try:
                    msg = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
                    await msg.delete()
                except discord.DiscordException:
                    pass

    record_staff_action(
        roster_id=roster["_id"],
        action=AUDIT_ACTION_UNLOCKED,
        staff_discord_id=interaction.user.id,
        staff_display_name=getattr(interaction.user, "display_name", None),
        staff_username=str(interaction.user),
    )

    suffix = f" (Tournament: {cycle_name})" if cycle_name else ""
    return True, f"Roster unlocked for <@{coach_id}>.{suffix}"


class SetCoachTierModal(discord.ui.Modal, title="Set Coach Tier"):
    coach_id: discord.ui.TextInput = discord.ui.TextInput(
        label="Coach Discord ID or mention",
        placeholder="@Coach or 1234567890",
    )
    tier: discord.ui.TextInput = discord.ui.TextInput(
        label="Tier (Coach / Premium / Premium+)",
        placeholder="Premium+",
        max_length=32,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_staff_user(interaction.user, getattr(interaction.client, "settings", None)):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        coach_id = _parse_discord_id(self.coach_id.value)
        if coach_id is None:
            await interaction.response.send_message(
                "Enter a valid coach Discord ID or mention.",
                ephemeral=True,
            )
            return
        ok, message = await _set_coach_tier(interaction, coach_id=coach_id, tier=self.tier.value)
        await interaction.response.send_message(
            embed=make_embed(
                title="Coach tier updated" if ok else "Coach tier update failed",
                description=message,
                color=SUCCESS_COLOR if ok else ERROR_COLOR,
            ),
            ephemeral=True,
        )

        settings = getattr(interaction.client, "settings", None)
        if ok and settings is not None and interaction.guild is not None:
            test_mode = bool(getattr(interaction.client, "test_mode", False))
            await upsert_premium_coaches_report(
                interaction.client,
                settings=settings,
                guild_id=interaction.guild.id,
                test_mode=test_mode,
            )


class UnlockRosterManagerModal(discord.ui.Modal, title="Unlock Roster"):
    coach_id: discord.ui.TextInput = discord.ui.TextInput(
        label="Coach Discord ID or mention",
        placeholder="@Coach or 1234567890",
    )
    tournament_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Tournament Name (optional)",
        required=False,
        placeholder="Leave blank for current active tournament",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_staff_user(interaction.user, getattr(interaction.client, "settings", None)):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        coach_id = _parse_discord_id(self.coach_id.value)
        if coach_id is None:
            await interaction.response.send_message(
                "Enter a valid coach Discord ID or mention.",
                ephemeral=True,
            )
            return

        ok, message = await _unlock_roster(
            interaction,
            coach_id=coach_id,
            tournament=self.tournament_name.value.strip() or None,
        )
        await interaction.response.send_message(
            embed=make_embed(
                title="Roster unlocked" if ok else "Unlock failed",
                description=message,
                color=SUCCESS_COLOR if ok else ERROR_COLOR,
            ),
            ephemeral=True,
        )


class DeleteRosterManagerModal(discord.ui.Modal, title="Delete Roster"):
    coach_id: discord.ui.TextInput = discord.ui.TextInput(
        label="Coach Discord ID or mention",
        placeholder="@Coach or 1234567890",
    )
    tournament_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Tournament Name (optional)",
        required=False,
        placeholder="Leave blank for current active tournament",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_staff_user(interaction.user, getattr(interaction.client, "settings", None)):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return

        perms = getattr(interaction.user, "guild_permissions", None)
        if not (perms and perms.administrator):
            await interaction.response.send_message(
                "Only server administrators can delete rosters.",
                ephemeral=True,
            )
            return

        coach_id = _parse_discord_id(self.coach_id.value)
        if coach_id is None:
            await interaction.response.send_message(
                "Enter a valid coach Discord ID or mention.",
                ephemeral=True,
            )
            return

        cycle_id = None
        if self.tournament_name.value.strip():
            cycle = ensure_cycle_by_name(self.tournament_name.value.strip())
            cycle_id = cycle["_id"]

        roster = get_roster_for_coach(coach_id, cycle_id=cycle_id)
        if roster is None:
            await interaction.response.send_message(
                "Roster not found for that coach/tournament.",
                ephemeral=True,
            )
            return

        submission = delete_submission_by_roster(roster["_id"])
        if submission:
            channel_id = submission.get("staff_channel_id")
            message_id = submission.get("staff_message_id")
            if isinstance(channel_id, int) and isinstance(message_id, int):
                channel = await fetch_channel(interaction.client, channel_id)
                if channel and hasattr(channel, "fetch_message"):
                    try:
                        msg = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
                        await msg.delete()
                    except discord.DiscordException:
                        pass

        delete_roster(roster["_id"])
        await interaction.response.send_message(
            embed=make_embed(
                title="Roster deleted",
                description=f"Deleted roster for <@{coach_id}>.",
                color=SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

        settings = getattr(interaction.client, "settings", None)
        if settings is not None and interaction.guild is not None:
            cap_value = roster.get("cap")
            if isinstance(cap_value, int) and cap_value in {22, 25}:
                test_mode = bool(getattr(interaction.client, "test_mode", False))
                await upsert_premium_coaches_report(
                    interaction.client,
                    settings=settings,
                    guild_id=interaction.guild.id,
                    test_mode=test_mode,
                )


class ManagerPortalView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

        buttons = [
            ("Set Coach Tier", discord.ButtonStyle.primary, self.on_set_tier),
            ("Unlock Roster", discord.ButtonStyle.secondary, self.on_unlock),
            ("Refresh Premium Coaches", discord.ButtonStyle.success, self.on_refresh_premium),
            ("Toggle Premium Pin", discord.ButtonStyle.secondary, self.on_toggle_premium_pin),
            ("Force Rebuild Premium", discord.ButtonStyle.danger, self.on_force_rebuild_premium),
            ("Sync Caps (Active Cycle)", discord.ButtonStyle.secondary, self.on_sync_caps),
            ("Repost Portal (staff)", discord.ButtonStyle.secondary, self.on_repost_portal),
            ("Delete Roster", discord.ButtonStyle.danger, self.on_delete_roster),
        ]
        for label, style, handler in buttons:
            button: discord.ui.Button = discord.ui.Button(label=label, style=style)
            setattr(button, "callback", handler)
            self.add_item(button)

    async def on_set_tier(self, interaction: discord.Interaction) -> None:
        if not is_staff_user(interaction.user, getattr(interaction.client, "settings", None)):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        await interaction.response.send_modal(SetCoachTierModal())

    async def on_unlock(self, interaction: discord.Interaction) -> None:
        if not is_staff_user(interaction.user, getattr(interaction.client, "settings", None)):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        await interaction.response.send_modal(UnlockRosterManagerModal())

    async def on_refresh_premium(self, interaction: discord.Interaction) -> None:
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.",
                ephemeral=True,
            )
            return
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
        test_mode = bool(getattr(interaction.client, "test_mode", False))
        await upsert_premium_coaches_report(
            interaction.client,
            settings=settings,
            guild_id=guild.id,
            test_mode=test_mode,
        )
        await interaction.response.send_message(
            embed=make_embed(
                title="Premium Coaches refreshed",
                description="Updated the Premium Coaches listing embed.",
                color=SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def on_toggle_premium_pin(self, interaction: discord.Interaction) -> None:
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.",
                ephemeral=True,
            )
            return
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

        try:
            cfg = get_guild_config(guild.id)
        except Exception:
            cfg = {}
        enabled = _parse_bool(cfg.get(PREMIUM_PIN_ENABLED_KEY))
        cfg[PREMIUM_PIN_ENABLED_KEY] = not enabled
        try:
            set_guild_config(guild.id, cfg)
        except Exception:
            await interaction.response.send_message(
                "Failed to persist the pin setting.",
                ephemeral=True,
            )
            return

        test_mode = bool(getattr(interaction.client, "test_mode", False))
        await upsert_premium_coaches_report(
            interaction.client,
            settings=settings,
            guild_id=guild.id,
            test_mode=test_mode,
        )

        status = "enabled" if not enabled else "disabled"
        await interaction.response.send_message(
            embed=make_embed(
                title="Premium Coaches pin updated",
                description=f"Pinning is now **{status}** for the Premium Coaches listing.",
                color=SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def on_force_rebuild_premium(self, interaction: discord.Interaction) -> None:
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.",
                ephemeral=True,
            )
            return
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

        test_mode = bool(getattr(interaction.client, "test_mode", False))
        deleted = await force_rebuild_premium_coaches_report(
            interaction.client,
            settings=settings,
            guild_id=guild.id,
            test_mode=test_mode,
        )
        await interaction.response.send_message(
            embed=make_embed(
                title="Premium Coaches rebuilt",
                description=f"Deleted {deleted} stale bot message(s) and rebuilt the listing.",
                color=SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def on_sync_caps(self, interaction: discord.Interaction) -> None:
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.",
                ephemeral=True,
            )
            return
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

        await interaction.response.defer(ephemeral=True)

        coach_role_id = resolve_role_id(settings, guild_id=guild.id, field="role_coach_id")
        premium_role_id = resolve_role_id(settings, guild_id=guild.id, field="role_coach_premium_id")
        premium_plus_role_id = resolve_role_id(
            settings, guild_id=guild.id, field="role_coach_premium_plus_id"
        )
        if not coach_role_id or not premium_role_id or not premium_plus_role_id:
            await interaction.followup.send(
                embed=make_embed(
                    title="Sync failed",
                    description=(
                        "Coach tier roles are not configured yet. Ensure the bot has `Manage Roles` "
                        "and MongoDB is configured, then restart the bot."
                    ),
                    color=ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        try:
            cycle_collection = get_collection(settings, record_type="tournament_cycle")
            team_rosters = get_collection(settings, record_type="team_roster")
            roster_players = get_collection(settings, record_type="roster_player")
        except Exception:
            await interaction.followup.send(
                embed=make_embed(
                    title="Sync failed",
                    description="MongoDB is not configured or unavailable.",
                    color=ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        try:
            cycle = ensure_active_cycle(collection=cycle_collection)
        except Exception:
            await interaction.followup.send(
                embed=make_embed(
                    title="Sync failed",
                    description="Could not resolve the active tournament cycle.",
                    color=ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        rosters = list(
            team_rosters.find(
                {"record_type": "team_roster", "cycle_id": cycle["_id"]},
                sort=[("created_at", 1)],
            )
        )
        if not rosters:
            await interaction.followup.send(
                embed=make_embed(
                    title="No rosters found",
                    description="There are no rosters in the active cycle to sync.",
                    color=SUCCESS_COLOR,
                ),
                ephemeral=True,
            )
            return

        roster_ids = [r.get("_id") for r in rosters if r.get("_id") is not None]
        counts: dict[object, int] = {}
        if roster_ids:
            try:
                pipeline = [
                    {"$match": {"record_type": "roster_player", "roster_id": {"$in": roster_ids}}},
                    {"$group": {"_id": "$roster_id", "count": {"$sum": 1}}},
                ]
                for doc in roster_players.aggregate(pipeline):
                    counts[doc.get("_id")] = int(doc.get("count") or 0)
            except Exception:
                counts = {}

        updated = 0
        unchanged = 0
        skipped_no_member = 0
        skipped_no_role = 0
        skipped_too_large = 0
        skipped_invalid = 0

        for roster in rosters:
            roster_id = roster.get("_id")
            coach_id_raw = roster.get("coach_discord_id")
            coach_id = int(coach_id_raw) if isinstance(coach_id_raw, int) else None
            if roster_id is None or coach_id is None:
                skipped_invalid += 1
                continue

            member = await _fetch_member(guild, coach_id)
            if member is None:
                skipped_no_member += 1
                continue

            desired_cap = _desired_cap_for_member(
                member,
                coach_role_id=coach_role_id,
                premium_role_id=premium_role_id,
                premium_plus_role_id=premium_plus_role_id,
            )
            if desired_cap is None:
                skipped_no_role += 1
                continue

            player_count = counts.get(roster_id, 0)
            current_cap_raw = roster.get("cap")
            current_cap = int(current_cap_raw) if isinstance(current_cap_raw, int) else 0

            if desired_cap < player_count:
                skipped_too_large += 1
                record_staff_action(
                    roster_id=roster_id,
                    action=AUDIT_ACTION_CAP_SYNC_SKIPPED,
                    staff_discord_id=interaction.user.id,
                    staff_display_name=getattr(interaction.user, "display_name", None),
                    staff_username=str(interaction.user),
                    details={
                        "from_cap": current_cap,
                        "to_cap": desired_cap,
                        "player_count": player_count,
                        "reason": "active_cycle_sync",
                    },
                )
                continue

            if current_cap == desired_cap:
                unchanged += 1
                continue

            update_roster_cap(roster_id, desired_cap)
            updated += 1
            record_staff_action(
                roster_id=roster_id,
                action=AUDIT_ACTION_CAP_SYNCED,
                staff_discord_id=interaction.user.id,
                staff_display_name=getattr(interaction.user, "display_name", None),
                staff_username=str(interaction.user),
                details={
                    "from_cap": current_cap,
                    "to_cap": desired_cap,
                    "player_count": player_count,
                    "reason": "active_cycle_sync",
                },
            )

        test_mode = bool(getattr(interaction.client, "test_mode", False))
        await upsert_premium_coaches_report(
            interaction.client,
            settings=settings,
            guild_id=guild.id,
            test_mode=test_mode,
        )

        await interaction.followup.send(
            embed=make_embed(
                title="Roster caps synced",
                description=(
                    f"Cycle: **{cycle.get('name', 'Current Tournament')}**\n"
                    f"Updated: **{updated}**\n"
                    f"Unchanged: **{unchanged}**\n"
                    f"Skipped (too many players): **{skipped_too_large}**\n"
                    f"Skipped (coach not in server): **{skipped_no_member}**\n"
                    f"Skipped (no coach role): **{skipped_no_role}**\n"
                    f"Skipped (invalid roster): **{skipped_invalid}**"
                ),
                color=SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def on_repost_portal(self, interaction: discord.Interaction) -> None:
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.",
                ephemeral=True,
            )
            return
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
                description="Cleaning up and reposting the Club Managers portal now.",
                color=SUCCESS_COLOR,
            ),
            ephemeral=True,
        )
        await post_manager_portal(interaction.client, guilds=[guild])

    async def on_delete_roster(self, interaction: discord.Interaction) -> None:
        if not is_staff_user(interaction.user, getattr(interaction.client, "settings", None)):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        perms = getattr(interaction.user, "guild_permissions", None)
        if not (perms and perms.administrator):
            await interaction.response.send_message(
                "Only server administrators can delete rosters.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(DeleteRosterManagerModal())


async def post_manager_portal(
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
            field="channel_manager_portal_id",
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
                        "Club Managers Control Panel",
                        "Club Managers Portal Overview",
                    }:
                        try:
                            await message.delete()
                        except discord.DiscordException:
                            pass
        except discord.DiscordException:
            pass

        intro_embed = build_manager_intro_embed()
        embed = build_manager_embed()
        view = ManagerPortalView()
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
                "Posted club managers portal embed (guild=%s channel=%s).", guild.id, target_channel_id
            )
        except discord.DiscordException as exc:
            logging.warning(
                "Failed to post club managers portal to channel %s (guild=%s): %s",
                target_channel_id,
                guild.id,
                exc,
            )
