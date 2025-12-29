from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from config import Settings
from interactions.recruit_posts import upsert_recruit_profile_posts
from interactions.views import SafeView
from services.recruitment_service import (
    get_recruit_profile,
    update_recruit_profile_availability,
    update_recruit_profile_posts,
)
from utils.availability import (
    Availability,
    format_days,
    next_availability_start,
    validate_availability,
)
from utils.embeds import DEFAULT_COLOR, ERROR_COLOR, SUCCESS_COLOR, make_embed


class RecruitAvailabilityView(SafeView):
    def __init__(
        self,
        *,
        settings: Settings,
        guild_id: int,
        user_id: int,
        profile: dict,
    ) -> None:
        super().__init__(timeout=300)
        self.settings = settings
        self.guild_id = guild_id
        self.user_id = user_id
        self.profile = profile

        self.days = list(profile.get("availability_days") or [])
        self.start_hour = int(profile.get("availability_start_hour") or 18)
        self.end_hour = int(profile.get("availability_end_hour") or 22)

        self.days_select: discord.ui.Select = discord.ui.Select(
            placeholder="Days",
            min_values=1,
            max_values=7,
            options=[
                discord.SelectOption(label=label, value=str(idx), default=idx in self.days)
                for idx, label in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
            ],
        )
        self.days_select.callback = self._on_days_change  # type: ignore[assignment]
        self.add_item(self.days_select)

        self.start_select: discord.ui.Select = discord.ui.Select(
            placeholder="Start hour",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=f"{hour:02d}:00",
                    value=str(hour),
                    default=hour == self.start_hour,
                )
                for hour in range(24)
            ],
        )
        self.start_select.callback = self._on_start_change  # type: ignore[assignment]
        self.add_item(self.start_select)

        self.end_select: discord.ui.Select = discord.ui.Select(
            placeholder="End hour",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=f"{hour:02d}:00",
                    value=str(hour),
                    default=hour == self.end_hour,
                )
                for hour in range(24)
            ],
        )
        self.end_select.callback = self._on_end_change  # type: ignore[assignment]
        self.add_item(self.end_select)

        save_btn: discord.ui.Button = discord.ui.Button(label="Save", style=discord.ButtonStyle.success)
        setattr(save_btn, "callback", self._on_save)
        self.add_item(save_btn)

        cancel_btn: discord.ui.Button = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.secondary
        )
        setattr(cancel_btn, "callback", self._on_cancel)
        self.add_item(cancel_btn)

    def build_embed(self) -> discord.Embed:
        days_text = format_days(self.days) if self.days else "None"
        embed = make_embed(
            title="Availability",
            description="Select your available days and hours, then Save.",
            color=DEFAULT_COLOR,
        )
        embed.add_field(name="Days", value=days_text, inline=False)
        embed.add_field(
            name="Hours",
            value=f"{self.start_hour:02d}:00 - {self.end_hour:02d}:00",
            inline=False,
        )
        tz_name = self.profile.get("timezone") or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        try:
            availability = Availability(days=self.days, start_hour=self.start_hour, end_hour=self.end_hour)
            next_start = next_availability_start(availability, tz=tz, now=datetime.now(tz))
        except Exception:
            next_start = None
        if next_start is not None:
            embed.add_field(
                name="Next start (viewer-local)",
                value=f"{discord.utils.format_dt(next_start, style='F')} ({discord.utils.format_dt(next_start, style='R')})",
                inline=False,
            )
        return embed

    async def _on_days_change(self, interaction: discord.Interaction) -> None:
        self.days = [int(v) for v in self.days_select.values]
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_start_change(self, interaction: discord.Interaction) -> None:
        self.start_hour = int(self.start_select.values[0])
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_end_change(self, interaction: discord.Interaction) -> None:
        self.end_hour = int(self.end_select.values[0])
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_save(self, interaction: discord.Interaction) -> None:
        try:
            validate_availability(self.days, start_hour=self.start_hour, end_hour=self.end_hour)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            update_recruit_profile_availability(
                self.guild_id,
                self.user_id,
                availability_days=sorted(set(self.days)),
                availability_start_hour=self.start_hour,
                availability_end_hour=self.end_hour,
            )
        except Exception as exc:
            await interaction.followup.send(
                embed=make_embed(
                    title="Failed to save availability",
                    description=str(exc),
                    color=ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        updated_profile = None
        try:
            updated_profile = get_recruit_profile(self.guild_id, self.user_id)
        except Exception:
            updated_profile = None

        if updated_profile:
            self.profile = updated_profile
            test_mode = bool(getattr(interaction.client, "test_mode", False))
            try:
                refs = await upsert_recruit_profile_posts(
                    interaction.client,
                    settings=self.settings,
                    guild_id=self.guild_id,
                    profile=updated_profile,
                    test_mode=test_mode,
                )
                update_recruit_profile_posts(
                    self.guild_id,
                    self.user_id,
                    listing_channel_id=refs.get("listing_channel_id"),
                    listing_message_id=refs.get("listing_message_id"),
                    staff_channel_id=refs.get("staff_channel_id"),
                    staff_message_id=refs.get("staff_message_id"),
                )
            except Exception:
                pass

        self.disable_items()
        try:
            if interaction.message:
                await interaction.message.edit(embed=self.build_embed(), view=self)
        except discord.DiscordException:
            pass
        await interaction.followup.send(
            embed=make_embed(
                title="Availability saved",
                description="Your availability has been updated.",
                color=SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        self.disable_items()
        await interaction.response.edit_message(
            embed=make_embed(
                title="Availability",
                description="Canceled.",
                color=DEFAULT_COLOR,
            ),
            view=self,
        )
