from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from repositories.tournament_repo import ensure_cycle_by_name, get_cycle_by_id
from services.audit_service import AUDIT_ACTION_UNLOCKED, record_staff_action
from services.recruitment_service import search_recruit_profiles
from services.roster_service import (
    ROSTER_STATUS_UNLOCKED,
    get_latest_roster_for_coach,
    get_roster_for_coach,
    set_roster_status,
)
from services.submission_service import delete_submission_by_roster
from utils.discord_wrappers import fetch_channel
from utils.validation import normalize_platform


class StaffCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        settings = getattr(self.bot, "settings", None)
        if settings is None:
            return False
        role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
        if settings.staff_role_ids:
            return bool(role_ids.intersection(settings.staff_role_ids))
        perms = getattr(interaction.user, "guild_permissions", None)
        return bool(getattr(perms, "manage_guild", False))

    @app_commands.command(name="unlock_roster", description="Unlock a roster for edits.")
    @app_commands.describe(
        coach="Coach whose roster should be unlocked",
        tournament="Optional tournament cycle name",
    )
    async def unlock_roster(
        self,
        interaction: discord.Interaction,
        coach: discord.Member,
        tournament: str | None = None,
    ) -> None:
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You do not have permission to unlock rosters.",
                ephemeral=True,
            )
            return

        roster = None
        cycle_name = None
        if tournament:
            cycle_doc = ensure_cycle_by_name(tournament.strip())
            roster = get_roster_for_coach(coach.id, cycle_id=cycle_doc["_id"])
            cycle_name = cycle_doc.get("name")
        else:
            roster = get_roster_for_coach(coach.id)

        if roster is None and tournament is None:
            roster = get_latest_roster_for_coach(coach.id)
            if roster:
                cycle = get_cycle_by_id(roster.get("cycle_id"))
                cycle_name = cycle.get("name") if cycle else None

        if roster is None:
            await interaction.response.send_message(
                "Roster not found for that coach.",
                ephemeral=True,
            )
            return

        try:
            set_roster_status(
                roster["_id"],
                ROSTER_STATUS_UNLOCKED,
                expected_updated_at=roster.get("updated_at"),
            )
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        submission = delete_submission_by_roster(roster["_id"])
        if submission:
            channel_id = submission.get("staff_channel_id")
            message_id = submission.get("staff_message_id")
            if isinstance(channel_id, int) and isinstance(message_id, int):
                channel = await fetch_channel(self.bot, channel_id)
                if channel:
                    try:
                        msg = await channel.fetch_message(message_id)
                        await msg.delete()
                    except discord.DiscordException:
                        pass
        record_staff_action(
            roster_id=roster["_id"],
            action=AUDIT_ACTION_UNLOCKED,
            guild_id=getattr(interaction, "guild_id", None),
            source="staff_command",
            staff_discord_id=interaction.user.id,
            staff_display_name=getattr(interaction.user, "display_name", None),
            staff_username=str(interaction.user),
        )
        suffix = f" (Tournament: {cycle_name})" if cycle_name else ""
        await interaction.response.send_message(
            f"Roster unlocked for {coach.mention}.{suffix}",
            ephemeral=True,
        )

    @app_commands.command(
        name="player_pool",
        description="Search recruit profiles (staff only).",
    )
    @app_commands.describe(
        position="Position filter (e.g., ST, CM)",
        archetype="Archetype filter (free text)",
        platform="Platform filter (PC/PS5)",
        mic="Require mic (true/false)",
    )
    async def player_pool(
        self,
        interaction: discord.Interaction,
        position: str | None = None,
        archetype: str | None = None,
        platform: str | None = None,
        mic: bool | None = None,
    ) -> None:
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True,
            )
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command must be used in a guild.",
                ephemeral=True,
            )
            return

        platform_value = None
        if platform and platform.strip():
            platform_value = normalize_platform(platform)
            if platform_value is None:
                await interaction.response.send_message(
                    "Platform must be PC or PS5.",
                    ephemeral=True,
                )
                return

        results = search_recruit_profiles(
            guild.id,
            position=position,
            archetype=archetype,
            platform=platform_value,
            mic=mic,
            limit=50,
            offset=0,
        )

        lines: list[str] = []
        for profile in results:
            line = _format_player_pool_line(guild.id, profile)
            if not line:
                continue
            if sum(len(existing_line) + 1 for existing_line in lines) + len(line) > 1800:
                break
            lines.append(line)

        header = "**Player Pool Results**\n"
        if not lines:
            await interaction.response.send_message(
                header + "No matching profiles found.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await interaction.response.send_message(
            header + "\n".join(lines),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(
        name="player_pool_index",
        description="Player pool listings now live in the web dashboard (staff only).",
    )
    async def player_pool_index(self, interaction: discord.Interaction) -> None:
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Player pool listings now live in the web dashboard. Use /player_pool for quick search.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StaffCog(bot))


def _profile_jump_link(guild_id: int, profile: dict) -> str | None:
    channel_id = profile.get("listing_channel_id")
    message_id = profile.get("listing_message_id")
    if isinstance(channel_id, int) and isinstance(message_id, int):
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
    return None


def _format_player_pool_line(guild_id: int, profile: dict, *, include_link: bool = False) -> str | None:
    user_id = profile.get("user_id")
    if not isinstance(user_id, int):
        return None
    pos = str(profile.get("main_position") or "?")
    arch = str(profile.get("main_archetype") or "").title()
    plat = str(profile.get("platform") or "")
    mic = profile.get("mic")
    mic_text = "Mic" if mic is True else "No mic" if mic is False else ""
    display = str(profile.get("display_name") or profile.get("user_tag") or user_id).strip()
    parts = [f"<@{user_id}>", display, f"{pos} ({arch})".strip(), plat, mic_text]
    parts = [p for p in parts if p]
    line = "- " + " — ".join(parts)
    if include_link:
        link = _profile_jump_link(guild_id, profile)
        if link:
            line += f" — <{link}>"
    return line[:200]
