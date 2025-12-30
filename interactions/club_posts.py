from __future__ import annotations

from typing import Any

import discord

from config import Settings
from interactions.club_embeds import build_club_ad_embed
from services.club_ad_audit_service import (
    CLUB_AD_ACTION_APPROVED,
    CLUB_AD_ACTION_REJECTED,
    record_club_ad_action,
)
from services.clubs_service import set_club_ad_approval, update_club_ad_posts
from utils.channel_routing import resolve_channel_id
from utils.discord_wrappers import edit_message, fetch_channel, send_message
from utils.errors import log_interaction_error, send_interaction_error
from utils.flags import feature_enabled


async def upsert_club_ad_posts(
    client: discord.Client,
    *,
    settings: Settings,
    guild_id: int,
    ad: dict[str, Any],
    test_mode: bool,
) -> dict[str, int | None]:
    approval_enabled = feature_enabled("club_ads_approval", settings)
    approval_status = str(ad.get("approval_status") or "").strip().lower()
    existing_listing_message_id = _parse_int(ad.get("listing_message_id"))
    approval_required = approval_enabled and not existing_listing_message_id and approval_status != "approved"

    embed = build_club_ad_embed(ad)
    staff_embed = build_club_ad_embed(ad)
    if approval_required:
        staff_embed.add_field(
            name="Approval",
            value="Pending staff approval (use the buttons below).",
            inline=False,
        )

    listing_channel_id = resolve_channel_id(
        settings,
        guild_id=guild_id,
        field="channel_club_listing_id",
        test_mode=test_mode,
    )

    staff_channel_id = None
    if test_mode:
        staff_channel_id = listing_channel_id
    else:
        staff_channel_id = resolve_channel_id(
            settings,
            guild_id=guild_id,
            field="channel_staff_monitor_id",
            test_mode=False,
        ) or resolve_channel_id(
            settings,
            guild_id=guild_id,
            field="channel_staff_portal_id",
            test_mode=False,
        )

    listing_message = None
    listing_message_id = existing_listing_message_id
    if listing_channel_id and not approval_required:
        listing_message = await _upsert_embed_post(
            client,
            channel_id=listing_channel_id,
            message_id=listing_message_id,
            embed=embed,
            view=None,
        )

    staff_message = None
    staff_message_id = _parse_int(ad.get("staff_message_id"))
    if staff_channel_id and (listing_message is None or staff_channel_id != listing_channel_id):
        staff_message = await _upsert_embed_post(
            client,
            channel_id=staff_channel_id,
            message_id=staff_message_id,
            embed=staff_embed,
            view=ClubAdApprovalView(guild_id=guild_id, owner_id=ad.get("owner_id"))
            if approval_required
            else None,
        )

    refs: dict[str, int | None] = {
        "listing_channel_id": listing_channel_id,
        "listing_message_id": listing_message.id if listing_message else None,
        "staff_channel_id": staff_channel_id,
        "staff_message_id": staff_message.id if staff_message else None,
    }
    if (
        staff_channel_id
        and listing_message is not None
        and staff_channel_id == listing_channel_id
    ):
        refs["staff_channel_id"] = listing_channel_id
        refs["staff_message_id"] = refs["listing_message_id"]
    return refs


async def _upsert_embed_post(
    client: discord.Client,
    *,
    channel_id: int,
    message_id: int | None,
    embed: discord.Embed,
    view: discord.ui.View | None,
) -> discord.Message | None:
    channel = await fetch_channel(client, channel_id)
    if channel is None:
        return None
    msg = None
    if message_id and hasattr(channel, "fetch_message"):
        try:
            msg = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
        except discord.DiscordException:
            msg = None
    if msg is not None:
        edited = await edit_message(msg, embed=embed, view=view)
        if edited is not None:
            return edited
    return await send_message(
        channel,
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions.none(),
    )


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class ClubAdApprovalView(discord.ui.View):
    def __init__(self, *, guild_id: int, owner_id: Any) -> None:
        super().__init__(timeout=3600)
        self.guild_id = guild_id
        self.owner_id = int(owner_id) if isinstance(owner_id, int) else None

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:  # type: ignore[override]
        log_interaction_error(error, interaction, source="club_ad_approval_view")
        await send_interaction_error(interaction)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="club_ad:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.owner_id is None:
            await interaction.response.send_message("Club ad owner not found.", ephemeral=True)
            return
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message("Bot configuration is not loaded.", ephemeral=True)
            return
        if not _is_staff(interaction, settings):
            await interaction.response.send_message("You do not have permission to approve ads.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        try:
            updated = set_club_ad_approval(
                self.guild_id,
                self.owner_id,
                status="approved",
                staff_discord_id=interaction.user.id,
                reason=None,
            )
        except Exception as exc:
            await interaction.followup.send(f"Failed to approve ad: {exc}", ephemeral=True)
            return

        test_mode = bool(getattr(interaction.client, "test_mode", False))
        refs = await upsert_club_ad_posts(
            interaction.client,
            settings=settings,
            guild_id=self.guild_id,
            ad=updated,
            test_mode=test_mode,
        )
        try:
            update_club_ad_posts(
                self.guild_id,
                self.owner_id,
                listing_channel_id=refs.get("listing_channel_id"),
                listing_message_id=refs.get("listing_message_id"),
                staff_channel_id=refs.get("staff_channel_id"),
                staff_message_id=refs.get("staff_message_id"),
            )
        except Exception:
            pass
        try:
            record_club_ad_action(
                guild_id=self.guild_id,
                owner_id=self.owner_id,
                action=CLUB_AD_ACTION_APPROVED,
                staff_discord_id=interaction.user.id,
                staff_display_name=getattr(interaction.user, "display_name", None),
                staff_username=str(interaction.user),
                source="club_posts",
            )
        except Exception:
            pass

        await interaction.followup.send("Club ad approved and published.", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="club_ad:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.owner_id is None:
            await interaction.response.send_message("Club ad owner not found.", ephemeral=True)
            return
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message("Bot configuration is not loaded.", ephemeral=True)
            return
        if not _is_staff(interaction, settings):
            await interaction.response.send_message("You do not have permission to reject ads.", ephemeral=True)
            return
        staff_channel_id = getattr(interaction.channel, "id", None)
        staff_message_id = getattr(interaction.message, "id", None)
        if not isinstance(staff_channel_id, int) or not isinstance(staff_message_id, int):
            await interaction.response.send_message("Could not resolve the staff review message.", ephemeral=True)
            return
        await interaction.response.send_modal(
            ClubAdRejectModal(
                guild_id=self.guild_id,
                owner_id=self.owner_id,
                staff_channel_id=staff_channel_id,
                staff_message_id=staff_message_id,
            )
        )


class ClubAdRejectModal(discord.ui.Modal, title="Reject Club Ad"):
    reason: discord.ui.TextInput = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        max_length=300,
        placeholder="Explain what needs to change before approval.",
    )

    def __init__(
        self,
        *,
        guild_id: int,
        owner_id: int,
        staff_channel_id: int,
        staff_message_id: int,
    ) -> None:
        super().__init__()
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.staff_channel_id = staff_channel_id
        self.staff_message_id = staff_message_id

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:  # type: ignore[override]
        log_interaction_error(error, interaction, source="club_ad_reject_modal")
        await send_interaction_error(interaction)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        settings = getattr(interaction.client, "settings", None)
        if settings is None:
            await interaction.response.send_message("Bot configuration is not loaded.", ephemeral=True)
            return
        if not _is_staff(interaction, settings):
            await interaction.response.send_message("You do not have permission to reject ads.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        reason = str(self.reason.value or "").strip()[:300]

        try:
            updated = set_club_ad_approval(
                self.guild_id,
                self.owner_id,
                status="rejected",
                staff_discord_id=interaction.user.id,
                reason=reason or None,
            )
        except Exception as exc:
            await interaction.followup.send(f"Failed to reject ad: {exc}", ephemeral=True)
            return
        try:
            record_club_ad_action(
                guild_id=self.guild_id,
                owner_id=self.owner_id,
                action=CLUB_AD_ACTION_REJECTED,
                staff_discord_id=interaction.user.id,
                staff_display_name=getattr(interaction.user, "display_name", None),
                staff_username=str(interaction.user),
                source="club_posts",
                reason=reason or None,
            )
        except Exception:
            pass

        channel = await fetch_channel(interaction.client, self.staff_channel_id)
        if channel is not None and hasattr(channel, "fetch_message"):
            try:
                msg = await channel.fetch_message(self.staff_message_id)  # type: ignore[attr-defined]
            except discord.DiscordException:
                msg = None
            if msg is not None:
                embed = build_club_ad_embed(updated)
                embed.add_field(
                    name="Approval",
                    value=f"Rejected: {reason or 'No reason provided'}",
                    inline=False,
                )
                await edit_message(msg, embed=embed, view=None)

        await interaction.followup.send("Club ad rejected.", ephemeral=True)


def _is_staff(interaction: discord.Interaction, settings: Settings) -> bool:
    role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
    if settings.staff_role_ids:
        return bool(role_ids.intersection(settings.staff_role_ids))
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(getattr(perms, "manage_guild", False))
