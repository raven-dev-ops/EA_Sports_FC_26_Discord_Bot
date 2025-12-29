from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import discord

from interactions.club_posts import upsert_club_ad_posts
from interactions.recruit_posts import upsert_recruit_profile_posts
from repositories.tournament_repo import ensure_cycle_by_name
from services.banlist_service import get_ban_reason
from services.clubs_service import update_club_ad_posts, upsert_club_ad
from services.permission_service import resolve_roster_cap_from_settings
from services.recruitment_service import (
    recruit_profile_is_listing_ready,
    update_recruit_profile_posts,
    upsert_recruit_profile,
)
from services.roster_service import (
    add_player,
    count_roster_players,
    create_roster,
    get_roster_by_id,
    get_roster_for_coach,
    remove_player,
    roster_is_locked,
    update_roster_name,
)
from utils.cooldowns import Cooldown
from utils.errors import log_interaction_error, send_interaction_error
from utils.flags import feature_enabled
from utils.validation import (
    ensure_safe_text,
    normalize_console,
    normalize_platform,
    normalize_timezone,
    normalize_yes_no,
    parse_discord_id,
    parse_int_in_range,
    sanitize_text,
    validate_team_name,
)

RECRUIT_PROFILE_EDIT_COOLDOWN = Cooldown(seconds=30.0)
CLUB_AD_EDIT_COOLDOWN = Cooldown(seconds=30.0)


class SafeModal(discord.ui.Modal):
    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[Any] | None = None,
        /,
    ) -> None:
        log_interaction_error(error, interaction, source="modal")
        await send_interaction_error(interaction)


class CreateRosterModal(SafeModal, title="Create Roster"):
    team_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Team Name",
        min_length=2,
        max_length=32,
        placeholder="Enter your team name",
    )
    tournament_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Tournament Name (optional)",
        required=False,
        placeholder="Leave blank for current tournament",
    )

    def __init__(self, *, cycle_id: Any | None = None) -> None:
        super().__init__()
        self.cycle_id = cycle_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.", ephemeral=True
            )
            return

        roles = getattr(interaction.user, "roles", [])
        role_ids = [role.id for role in roles]
        cap = resolve_roster_cap_from_settings(role_ids, settings)
        if cap is None:
            await interaction.response.send_message(
                "You are not eligible to create a roster.", ephemeral=True
            )
            return

        name = self.team_name.value.strip()
        if not validate_team_name(name):
            await interaction.response.send_message(
                "Team name must be 2-32 characters using letters, numbers, spaces, '-' or '_'.",
                ephemeral=True,
            )
            return

        from interactions.dashboard import build_roster_dashboard

        selected_cycle = (
            self.tournament_name.value.strip()
            if self.tournament_name.value
            else ""
        )
        cycle_id = self.cycle_id
        if selected_cycle:
            cycle = ensure_cycle_by_name(selected_cycle)
            cycle_id = cycle["_id"]

        existing = get_roster_for_coach(interaction.user.id, cycle_id=cycle_id)
        if existing:
            embed, view = build_roster_dashboard(interaction, cycle_id=cycle_id)
            await interaction.response.send_message(
                "Roster already exists.", embed=embed, view=view, ephemeral=True
            )
            return

        create_roster(
            coach_discord_id=interaction.user.id,
            team_name=name,
            cap=cap,
            cycle_id=cycle_id,
        )

        embed, view = build_roster_dashboard(interaction, cycle_id=cycle_id)
        await interaction.response.send_message(
            "Roster created.", embed=embed, view=view, ephemeral=True
        )


class AddPlayerModal(SafeModal, title="Add Player"):
    def __init__(self, *, roster_id: Any, player_discord_id: int | None = None) -> None:
        super().__init__()
        self.roster_id = roster_id
        if isinstance(player_discord_id, int) and player_discord_id > 0:
            self.discord_id.default = str(player_discord_id)

    discord_id: discord.ui.TextInput = discord.ui.TextInput(
        label="Player Discord ID or mention",
        placeholder="@Player or 1234567890",
    )
    gamertag: discord.ui.TextInput = discord.ui.TextInput(label="Gamertag or PSN")
    ea_id: discord.ui.TextInput = discord.ui.TextInput(label="EA ID")
    console: discord.ui.TextInput = discord.ui.TextInput(label="Console (PS, XBOX, PC, SWITCH)")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        roster = get_roster_by_id(self.roster_id)
        if roster is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return

        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.", ephemeral=True
            )
            return

        if roster_is_locked(roster):
            await interaction.response.send_message(
                "This roster is locked and cannot be edited.",
                ephemeral=True,
            )
            return

        player_id = parse_discord_id(self.discord_id.value)
        if player_id is None:
            await interaction.response.send_message(
                "Enter a valid Discord mention or ID for the player.",
                ephemeral=True,
            )
            return

        try:
            ban_reason = get_ban_reason(settings, player_id)
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if ban_reason:
            await interaction.response.send_message(
                f"Player is banned: {ban_reason}",
                ephemeral=True,
            )
            return

        console_value = normalize_console(self.console.value)
        if console_value is None:
            await interaction.response.send_message(
                "Console must be one of: PS, XBOX, PC, SWITCH.",
                ephemeral=True,
            )
            return

        try:
            add_player(
                roster_id=self.roster_id,
                player_discord_id=player_id,
                gamertag=self.gamertag.value.strip(),
                ea_id=self.ea_id.value.strip(),
                console=console_value,
                cap=int(roster.get("cap", 0)),
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        count = count_roster_players(self.roster_id)
        cap = roster.get("cap", "N/A")
        await interaction.response.send_message(
            f"Player added. Roster now {count}/{cap}.",
            ephemeral=True,
        )


class RemovePlayerModal(SafeModal, title="Remove Player"):
    def __init__(self, *, roster_id: Any) -> None:
        super().__init__()
        self.roster_id = roster_id

    discord_id: discord.ui.TextInput = discord.ui.TextInput(
        label="Player Discord ID or mention",
        placeholder="@Player or 1234567890",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        roster = get_roster_by_id(self.roster_id)
        if roster is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return

        if roster_is_locked(roster):
            await interaction.response.send_message(
                "This roster is locked and cannot be edited.",
                ephemeral=True,
            )
            return

        player_id = parse_discord_id(self.discord_id.value)
        if player_id is None:
            await interaction.response.send_message(
                "Enter a valid Discord mention or ID for the player.",
                ephemeral=True,
            )
            return

        removed = remove_player(
            roster_id=self.roster_id,
            player_discord_id=player_id,
        )
        if not removed:
            await interaction.response.send_message(
                "Player not found on this roster.",
                ephemeral=True,
            )
            return

        count = count_roster_players(self.roster_id)
        cap = roster.get("cap", "N/A")
        await interaction.response.send_message(
            f"Player removed. Roster now {count}/{cap}.",
            ephemeral=True,
        )


class RenameRosterModal(SafeModal, title="Edit Team Name"):
    def __init__(self, *, roster_id: Any) -> None:
        super().__init__()
        self.roster_id = roster_id

    team_name: discord.ui.TextInput = discord.ui.TextInput(
        label="New Team Name",
        min_length=2,
        max_length=32,
        placeholder="Enter your team name",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        roster = get_roster_by_id(self.roster_id)
        if roster is None:
            await interaction.response.send_message(
                "Roster not found. Please open the dashboard again.",
                ephemeral=True,
            )
            return

        if roster_is_locked(roster):
            await interaction.response.send_message(
                "This roster is locked and cannot be edited.",
                ephemeral=True,
            )
            return

        name = self.team_name.value.strip()
        if not validate_team_name(name):
            await interaction.response.send_message(
                "Team name must be 2-32 characters using letters, numbers, spaces, '-' or '_'.",
                ephemeral=True,
            )
            return

        update_roster_name(self.roster_id, name)
        await interaction.response.send_message(
            f"Team name updated to **{name}**.", ephemeral=True
        )


class RecruitProfileModalStep1(SafeModal, title="Recruit Profile (1/2)"):
    age: discord.ui.TextInput = discord.ui.TextInput(
        label="Age (optional)",
        required=False,
        max_length=2,
        placeholder="e.g., 18",
    )
    platform: discord.ui.TextInput = discord.ui.TextInput(
        label="Platform (PC/PS5)",
        max_length=16,
        placeholder="PC or PS5",
    )
    mic: discord.ui.TextInput = discord.ui.TextInput(
        label="Mic (yes/no)",
        max_length=8,
        placeholder="yes or no",
    )
    server_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Server name / region",
        max_length=40,
        placeholder="e.g., NA East, EU, Pro Clubs Central",
    )
    timezone: discord.ui.TextInput = discord.ui.TextInput(
        label="Timezone (IANA)",
        max_length=64,
        placeholder="e.g., America/New_York",
    )

    def __init__(self, *, existing_profile: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.existing_profile = existing_profile or {}
        if self.existing_profile.get("age") is not None:
            self.age.default = str(self.existing_profile.get("age") or "")
        if self.existing_profile.get("platform"):
            self.platform.default = str(self.existing_profile.get("platform") or "")
        if "mic" in self.existing_profile:
            self.mic.default = "yes" if self.existing_profile.get("mic") else "no"
        if self.existing_profile.get("server_name"):
            self.server_name.default = str(self.existing_profile.get("server_name") or "")
        if self.existing_profile.get("timezone"):
            self.timezone.default = str(self.existing_profile.get("timezone") or "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This flow must be used in a guild.",
                ephemeral=True,
            )
            return

        age = None
        if self.age.value.strip():
            age = parse_int_in_range(self.age.value, min_value=13, max_value=99)
            if age is None:
                await interaction.response.send_message(
                    "Age must be a number between 13 and 99.",
                    ephemeral=True,
                )
                return

        platform = normalize_platform(self.platform.value)
        if platform is None:
            await interaction.response.send_message(
                "Platform must be one of: PC, PS5.",
                ephemeral=True,
            )
            return

        mic = normalize_yes_no(self.mic.value)
        if mic is None:
            await interaction.response.send_message(
                "Mic must be yes or no.",
                ephemeral=True,
            )
            return

        try:
            server_name = ensure_safe_text(self.server_name.value, max_length=40)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        server_name = server_name.lower()

        timezone = normalize_timezone(self.timezone.value)
        if timezone is None:
            await interaction.response.send_message(
                "Timezone must be a valid IANA name (e.g., America/New_York) or UTC.",
                ephemeral=True,
            )
            return

        step1 = {
            "age": age,
            "platform": platform,
            "mic": mic,
            "server_name": server_name,
            "timezone": timezone,
        }
        await interaction.response.send_modal(
            RecruitProfileModalStep2(existing_profile=self.existing_profile, step1=step1)
        )


class RecruitProfileModalStep2(SafeModal, title="Recruit Profile (2/2)"):
    main_position: discord.ui.TextInput = discord.ui.TextInput(
        label="Main position",
        max_length=20,
        placeholder="e.g., ST, CM, CB, GK",
    )
    main_archetype: discord.ui.TextInput = discord.ui.TextInput(
        label="Main archetype",
        max_length=30,
        placeholder="e.g., Target Man, Box-to-Box",
    )
    secondary_position: discord.ui.TextInput = discord.ui.TextInput(
        label="Secondary position (optional)",
        required=False,
        max_length=20,
        placeholder="e.g., RW",
    )
    secondary_archetype: discord.ui.TextInput = discord.ui.TextInput(
        label="Secondary archetype (optional)",
        required=False,
        max_length=30,
        placeholder="e.g., Inverted Winger",
    )
    notes: discord.ui.TextInput = discord.ui.TextInput(
        label="Notes/experience (optional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=200,
        placeholder="Short summary (no @everyone/@here).",
    )

    def __init__(self, *, existing_profile: dict[str, Any], step1: dict[str, Any]) -> None:
        super().__init__()
        self.existing_profile = existing_profile
        self.step1 = step1

        if self.existing_profile.get("main_position"):
            self.main_position.default = str(self.existing_profile.get("main_position") or "")
        if self.existing_profile.get("main_archetype"):
            self.main_archetype.default = str(self.existing_profile.get("main_archetype") or "")
        if self.existing_profile.get("secondary_position"):
            self.secondary_position.default = str(self.existing_profile.get("secondary_position") or "")
        if self.existing_profile.get("secondary_archetype"):
            self.secondary_archetype.default = str(self.existing_profile.get("secondary_archetype") or "")
        if self.existing_profile.get("notes"):
            self.notes.default = str(self.existing_profile.get("notes") or "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This flow must be used in a guild.",
                ephemeral=True,
            )
            return

        try:
            main_position = ensure_safe_text(self.main_position.value, max_length=20).upper()
            main_archetype = ensure_safe_text(self.main_archetype.value, max_length=30).lower()
            secondary_position = (
                ensure_safe_text(self.secondary_position.value, max_length=20).upper()
                if self.secondary_position.value.strip()
                else None
            )
            secondary_archetype = (
                ensure_safe_text(self.secondary_archetype.value, max_length=30).lower()
                if self.secondary_archetype.value.strip()
                else None
            )
            notes = (
                ensure_safe_text(self.notes.value, max_length=200)
                if self.notes.value.strip()
                else None
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.",
                ephemeral=True,
            )
            return

        user_tag = str(interaction.user)
        display_name = getattr(interaction.user, "display_name", None)
        profile_payload = {
            **self.step1,
            "user_tag": sanitize_text(user_tag, max_length=64, allow_newlines=False),
            "display_name": sanitize_text(str(display_name or ""), max_length=64, allow_newlines=False)
            if display_name
            else None,
            "main_position": main_position,
            "main_archetype": main_archetype,
            "secondary_position": secondary_position,
            "secondary_archetype": secondary_archetype,
            "notes": notes,
        }

        cooldown = RECRUIT_PROFILE_EDIT_COOLDOWN.check(
            f"recruit_profile:{guild.id}:{interaction.user.id}"
        )
        if not cooldown.allowed:
            retry = cooldown.retry_after_seconds
            retry_text = f" Try again in ~{int(retry)}s." if retry is not None else ""
            await interaction.response.send_message(
                f"You're updating your profile too quickly.{retry_text}",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            saved = upsert_recruit_profile(
                guild.id,
                interaction.user.id,
                profile=profile_payload,
            )
        except Exception as exc:
            await interaction.followup.send(
                f"Failed to save profile: {exc}",
                ephemeral=True,
            )
            return

        listing_ready = recruit_profile_is_listing_ready(saved)
        logging.info(
            "Recruit profile saved guild=%s user=%s listing_ready=%s",
            guild.id,
            interaction.user.id,
            listing_ready,
        )
        if not listing_ready:
            await interaction.followup.send(
                "Profile saved. Set your Availability in the Recruitment Portal to publish your listing.",
                ephemeral=True,
            )
            return

        test_mode = bool(getattr(interaction.client, "test_mode", False))
        refs = await upsert_recruit_profile_posts(
            interaction.client,
            settings=settings,
            guild_id=guild.id,
            profile=saved,
            test_mode=test_mode,
        )

        try:
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

        await interaction.followup.send(
            "Profile saved.",
            ephemeral=True,
        )


class ClubAdModalStep1(SafeModal, title="Club Ad (1/2)"):
    club_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Club name",
        max_length=40,
        placeholder="Enter your club name",
    )
    region: discord.ui.TextInput = discord.ui.TextInput(
        label="Region",
        max_length=32,
        placeholder="e.g., NA East, EU",
    )
    timezone: discord.ui.TextInput = discord.ui.TextInput(
        label="Timezone (IANA)",
        max_length=64,
        placeholder="e.g., America/New_York",
    )
    formation: discord.ui.TextInput = discord.ui.TextInput(
        label="Formation (optional)",
        required=False,
        max_length=16,
        placeholder="e.g., 4-3-3",
    )
    positions_needed: discord.ui.TextInput = discord.ui.TextInput(
        label="Positions needed (comma-separated)",
        max_length=120,
        placeholder="e.g., ST, CM, CB, GK",
    )

    def __init__(self, *, existing_ad: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.existing_ad = existing_ad or {}
        if self.existing_ad.get("club_name"):
            self.club_name.default = str(self.existing_ad.get("club_name") or "")
        if self.existing_ad.get("region"):
            self.region.default = str(self.existing_ad.get("region") or "")
        if self.existing_ad.get("timezone"):
            self.timezone.default = str(self.existing_ad.get("timezone") or "")
        if self.existing_ad.get("formation"):
            self.formation.default = str(self.existing_ad.get("formation") or "")
        positions = self.existing_ad.get("positions_needed") or []
        if isinstance(positions, list) and positions:
            self.positions_needed.default = ", ".join(str(p) for p in positions)[:120]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This flow must be used in a guild.",
                ephemeral=True,
            )
            return

        try:
            club_name = ensure_safe_text(self.club_name.value, max_length=40)
            region = ensure_safe_text(self.region.value, max_length=32)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        tz = normalize_timezone(self.timezone.value)
        if tz is None:
            await interaction.response.send_message(
                "Timezone must be a valid IANA name (e.g., America/New_York) or UTC.",
                ephemeral=True,
            )
            return

        formation = None
        if self.formation.value.strip():
            try:
                formation = ensure_safe_text(self.formation.value, max_length=16)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

        raw_positions = self.positions_needed.value.strip()
        if not raw_positions:
            await interaction.response.send_message(
                "Positions needed is required (comma-separated).",
                ephemeral=True,
            )
            return
        positions: list[str] = []
        for part in raw_positions.split(","):
            pos = part.strip()
            if not pos:
                continue
            try:
                positions.append(ensure_safe_text(pos, max_length=20).upper())
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        if not positions:
            await interaction.response.send_message(
                "Positions needed is required (comma-separated).",
                ephemeral=True,
            )
            return

        step1 = {
            "club_name": club_name,
            "region": region,
            "timezone": tz,
            "formation": formation,
            "positions_needed": positions[:20],
        }
        await interaction.response.send_modal(
            ClubAdModalStep2(existing_ad=self.existing_ad, step1=step1)
        )


class ClubAdModalStep2(SafeModal, title="Club Ad (2/2)"):
    keywords: discord.ui.TextInput = discord.ui.TextInput(
        label="Keywords (comma-separated, optional)",
        required=False,
        max_length=120,
        placeholder="e.g., competitive, chill, mature",
    )
    description: discord.ui.TextInput = discord.ui.TextInput(
        label="What you're looking for",
        max_length=500,
        style=discord.TextStyle.paragraph,
        placeholder="Short, clear description (no @everyone/@here).",
    )
    tryout_time: discord.ui.TextInput = discord.ui.TextInput(
        label="Tryout time (optional)",
        required=False,
        max_length=32,
        placeholder="YYYY-MM-DD HH:MM (local to your timezone)",
    )
    contact: discord.ui.TextInput = discord.ui.TextInput(
        label="Contact instructions (optional)",
        required=False,
        max_length=120,
        placeholder="Default: DM the owner",
    )

    def __init__(self, *, existing_ad: dict[str, Any], step1: dict[str, Any]) -> None:
        super().__init__()
        self.existing_ad = existing_ad
        self.step1 = step1

        keywords = self.existing_ad.get("keywords") or []
        if isinstance(keywords, list) and keywords:
            self.keywords.default = ", ".join(str(k) for k in keywords)[:120]
        if self.existing_ad.get("description"):
            self.description.default = str(self.existing_ad.get("description") or "")[:500]
        if self.existing_ad.get("contact"):
            self.contact.default = str(self.existing_ad.get("contact") or "")[:120]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This flow must be used in a guild.",
                ephemeral=True,
            )
            return

        try:
            description = ensure_safe_text(self.description.value, max_length=500)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if len(description) < 30:
            await interaction.response.send_message(
                "Description must be at least 30 characters.",
                ephemeral=True,
            )
            return

        keywords: list[str] = []
        if self.keywords.value.strip():
            for part in self.keywords.value.split(","):
                token = part.strip()
                if not token:
                    continue
                try:
                    keywords.append(ensure_safe_text(token, max_length=20).lower())
                except ValueError as exc:
                    await interaction.response.send_message(str(exc), ephemeral=True)
                    return
        keywords = sorted(set(keywords))[:20]

        tryout_at = None
        if self.tryout_time.value.strip():
            tz_name = str(self.step1.get("timezone") or "UTC")
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = ZoneInfo("UTC")
            try:
                naive = datetime.strptime(self.tryout_time.value.strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                await interaction.response.send_message(
                    "Tryout time must match: YYYY-MM-DD HH:MM (e.g., 2025-01-31 19:30).",
                    ephemeral=True,
                )
                return
            local_dt = naive.replace(tzinfo=tz)
            tryout_at = local_dt.astimezone(timezone.utc)

        contact = self.contact.value.strip()
        if contact:
            try:
                contact = ensure_safe_text(contact, max_length=120)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        else:
            contact = f"DM <@{interaction.user.id}>"

        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message(
                "Bot configuration is not loaded.",
                ephemeral=True,
            )
            return

        owner_tag = sanitize_text(str(interaction.user), max_length=64, allow_newlines=False)
        display_name = getattr(interaction.user, "display_name", None)
        payload = {
            **self.step1,
            "owner_tag": owner_tag,
            "owner_display_name": sanitize_text(str(display_name or ""), max_length=64, allow_newlines=False)
            if display_name
            else None,
            "keywords": keywords,
            "description": description,
            "tryout_at": tryout_at,
            "contact": contact,
        }
        approval_enabled = feature_enabled("club_ads_approval", settings)
        if approval_enabled and not self.existing_ad.get("listing_message_id"):
            payload["approval_status"] = "pending"

        cooldown = CLUB_AD_EDIT_COOLDOWN.check(f"club_ad:{guild.id}:{interaction.user.id}")
        if not cooldown.allowed:
            retry = cooldown.retry_after_seconds
            retry_text = f" Try again in ~{int(retry)}s." if retry is not None else ""
            await interaction.response.send_message(
                f"You're updating your club ad too quickly.{retry_text}",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            saved = upsert_club_ad(
                guild.id,
                interaction.user.id,
                ad=payload,
            )
        except Exception as exc:
            await interaction.followup.send(
                f"Failed to save club ad: {exc}",
                ephemeral=True,
            )
            return
        logging.info(
            "Club ad saved guild=%s user=%s",
            guild.id,
            interaction.user.id,
        )

        test_mode = bool(getattr(interaction.client, "test_mode", False))
        refs = await upsert_club_ad_posts(
            interaction.client,
            settings=settings,
            guild_id=guild.id,
            ad=saved,
            test_mode=test_mode,
        )
        try:
            update_club_ad_posts(
                guild.id,
                interaction.user.id,
                listing_channel_id=refs.get("listing_channel_id"),
                listing_message_id=refs.get("listing_message_id"),
                staff_channel_id=refs.get("staff_channel_id"),
                staff_message_id=refs.get("staff_message_id"),
            )
        except Exception:
            pass

        await interaction.followup.send(
            "Club ad submitted for staff approval." if approval_enabled and not saved.get("listing_message_id") else "Club ad saved.",
            ephemeral=True,
        )
