from __future__ import annotations

import discord

from utils.channel_routing import resolve_channel_id
from utils.errors import send_interaction_error
from interactions.views import SafeView


def build_admin_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Admin Control Panel",
        description=(
            "Admin controls for the tournament bot. Use the buttons below to view quick actions "
            "and command references. All responses are ephemeral to you."
        ),
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Bot Controls",
        value="Toggle test mode, health checks.",
        inline=False,
    )
    embed.add_field(
        name="Tournaments",
        value="Lifecycle, rules, fixtures.",
        inline=False,
    )
    embed.add_field(
        name="Coaches & Rosters",
        value="Unlock, review, roster dashboards.",
        inline=False,
    )
    embed.add_field(
        name="Players",
        value="Player eligibility and ban checks.",
        inline=False,
    )
    embed.add_field(
        name="DB & Analytics",
        value="Data checks, health, and exports.",
        inline=False,
    )
    return embed


def bot_controls_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Bot Controls",
        description="Test mode, health, and diagnostics.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Commands",
        value=(
            "- `/dev_on` — route staff submissions + logs to test channel.\n"
            "- `/dev_off` — return routing to normal channels.\n"
            "- `/ping` — health check."
        ),
        inline=False,
    )
    embed.set_footer(text="Ephemeral responses only.")
    return embed


def tournaments_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Tournaments",
        description="Multi-cycle roster selection and staff review.",
        color=discord.Color.dark_blue(),
    )
    embed.add_field(
        name="Usage",
        value=(
            "- Coaches: `/roster [tournament:\"Name\"]` to open roster modal/dashboard.\n"
            "- Staff: approve/reject via buttons on submission posts.\n"
            "- Staff: `/unlock_roster @Coach [tournament:\"Name\"]` to unlock."
        ),
        inline=False,
    )
    embed.add_field(
        name="Notes",
        value=(
            "- Tournament name is optional; only use staff-provided names.\n"
            "- Roster caps are based on coach roles."
        ),
        inline=False,
    )
    embed.set_footer(text="Ephemeral responses only.")
    return embed


def coaches_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Coaches & Rosters",
        description="Coach eligibility, help, and unlocks.",
        color=discord.Color.dark_teal(),
    )
    embed.add_field(
        name="Commands",
        value=(
            "- `/roster [tournament]` — coach dashboard (create/add/remove/view/submit).\n"
            "- `/help` — coach-facing instructions.\n"
            "- `/unlock_roster @Coach [tournament]` — staff unlock."
        ),
        inline=False,
    )
    embed.add_field(
        name="Caps & Roles",
        value="Caps resolved from coach roles; ineligible coaches cannot create rosters.",
        inline=False,
    )
    embed.set_footer(text="Ephemeral responses only.")
    return embed


def rosters_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Rosters",
        description="Submission flow and audit trail.",
        color=discord.Color.dark_purple(),
    )
    embed.add_field(
        name="Flow",
        value=(
            "1) Coach opens `/roster` and creates roster.\n"
            "2) Coach adds players, then submits (locks roster).\n"
            "3) Staff approve/reject via submission buttons.\n"
            "4) Staff can unlock via `/unlock_roster`."
        ),
        inline=False,
    )
    embed.add_field(
        name="Audit",
        value="Approvals/rejections/unlocks are logged to the audit collection.",
        inline=False,
    )
    embed.set_footer(text="Ephemeral responses only.")
    return embed


def players_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Players",
        description="Add/remove validation and ban checks.",
        color=discord.Color.dark_green(),
    )
    embed.add_field(
        name="Add Player modal fields",
        value="Discord ID/mention, Gamertag/PSN, EA ID, Console (PS/XBOX/PC/SWITCH).",
        inline=False,
    )
    embed.add_field(
        name="Ban list (optional)",
        value="Enabled when BANLIST_* and GOOGLE_SHEETS_CREDENTIALS_JSON are set.",
        inline=False,
    )
    embed.add_field(
        name="Common errors",
        value="- Duplicate player, cap reached, invalid console, banned player.",
        inline=False,
    )
    embed.set_footer(text="Ephemeral responses only.")
    return embed


def db_embed() -> discord.Embed:
    embed = discord.Embed(
        title="DB & Analytics",
        description="MongoDB storage and future metrics/exports.",
        color=discord.Color.dark_gold(),
    )
    embed.add_field(
        name="Collections",
        value="tournament_cycle, team_roster, roster_player, submission_message, roster_audit.",
        inline=False,
    )
    embed.add_field(
        name="Indexes",
        value="Uniq roster per coach/cycle, roster player, submission message, audit idx.",
        inline=False,
    )
    embed.add_field(
        name="Future hooks",
        value="Health checks, exports, analytics dashboards.",
        inline=False,
    )
    embed.set_footer(text="Ephemeral responses only.")
    return embed


class AdminPortalView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

        buttons = [
            ("Bot Controls", discord.ButtonStyle.primary, self.on_bot_controls),
            ("Tournaments", discord.ButtonStyle.primary, self.on_tournaments),
            ("Coaches", discord.ButtonStyle.primary, self.on_coaches),
            ("Rosters", discord.ButtonStyle.primary, self.on_rosters),
            ("Players", discord.ButtonStyle.primary, self.on_players),
            ("DB Analytics", discord.ButtonStyle.primary, self.on_db),
        ]
        for label, style, handler in buttons:
            button = discord.ui.Button(label=label, style=style)
            button.callback = handler
            self.add_item(button)

    def _staff_only(self, interaction: discord.Interaction) -> bool:
        settings = getattr(interaction.client, "settings", None)
        role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
        if settings and settings.staff_role_ids:
            return bool(role_ids.intersection(settings.staff_role_ids))
        perms = getattr(interaction.user, "guild_permissions", None)
        return bool(perms and perms.manage_guild)

    async def _ensure_staff(self, interaction: discord.Interaction) -> bool:
        if not self._staff_only(interaction):
            await interaction.response.send_message(
                "You do not have permission to use this panel.",
                ephemeral=True,
            )
            return False
        return True

    async def on_bot_controls(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=bot_controls_embed(),
            ephemeral=True,
        )

    async def on_tournaments(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=tournaments_embed(),
            ephemeral=True,
        )

    async def on_coaches(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=coaches_embed(),
            ephemeral=True,
        )

    async def on_rosters(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=rosters_embed(),
            ephemeral=True,
        )

    async def on_players(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=players_embed(),
            ephemeral=True,
        )

    async def on_db(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=db_embed(),
            ephemeral=True,
        )


async def send_admin_portal_message(
    interaction: discord.Interaction,
) -> None:
    settings = getattr(interaction.client, "settings", None)
    if settings is None:
        await send_interaction_error(interaction)
        return

    test_mode = bool(getattr(interaction.client, "test_mode", False))
    target_channel_id = resolve_channel_id(
        settings, settings.channel_admin_portal_id, test_mode=test_mode
    )

    channel = interaction.client.get_channel(target_channel_id)
    if channel is None:
        try:
            channel = await interaction.client.fetch_channel(target_channel_id)
        except discord.DiscordException:
            await interaction.response.send_message(
                "Admin portal channel not found.",
                ephemeral=True,
            )
            return

    embed = build_admin_embed()
    view = AdminPortalView()
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(
        f"Posted admin control panel to <#{target_channel_id}>.",
        ephemeral=True,
    )
