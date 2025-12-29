from __future__ import annotations

import discord

from utils.channel_routing import resolve_channel_id
from utils.errors import send_interaction_error
from interactions.views import SafeView
from discord.ext import commands


def _coach_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Coach Guide",
        description="How coaches create and submit rosters.",
        color=discord.Color.green(),
    )
    embed.add_field(
        name="Create & Manage",
        value=(
            "1) Open the roster dashboard and create your roster.\n"
            "2) Use the buttons to add/remove players and view the roster.\n"
            "3) Submit the roster to staff; it locks until staff acts."
        ),
        inline=False,
    )
    embed.add_field(
        name="Player details",
        value="Discord mention/ID, Gamertag/PSN, EA ID, Console (PS/XBOX/PC/SWITCH).",
        inline=False,
    )
    embed.add_field(
        name="After submit",
        value="Roster is locked; staff can unlock for edits.",
        inline=False,
    )
    return embed

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
        description="Test mode, health, and diagnostics (staff only).",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Actions",
        value="Toggle test-mode routing and check bot health.",
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
            "- Coaches open the roster dashboard from the portal.\n"
            "- Staff approve/reject via buttons on submission posts.\n"
            "- Staff can unlock locked rosters from this portal."
        ),
        inline=False,
    )
    embed.add_field(
        name="Notes",
        value="- Tournament name is optional; only use staff-provided names.\n- Roster caps are based on coach roles.",
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
        name="Actions",
        value=(
            "- Open coach dashboard for create/add/remove/view/submit.\n"
            "- Show coach instructions.\n"
            "- Unlock a roster for edits."
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
            view=BotControlsView(),
        )

    async def on_tournaments(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=tournaments_embed(),
            ephemeral=True,
            view=TournamentsView(),
        )

    async def on_coaches(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=coaches_embed(),
            ephemeral=True,
            view=CoachesView(),
        )

    async def on_rosters(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=rosters_embed(),
            ephemeral=True,
            view=RostersView(),
        )

    async def on_players(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=players_embed(),
            ephemeral=True,
            view=PlayersView(),
        )

    async def on_db(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.send_message(
            embed=db_embed(),
            ephemeral=True,
            view=DBView(),
        )


class BotControlsView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        btn_on = discord.ui.Button(label="Test Mode On", style=discord.ButtonStyle.success)
        btn_off = discord.ui.Button(label="Test Mode Off", style=discord.ButtonStyle.danger)
        btn_ping = discord.ui.Button(label="Health Check", style=discord.ButtonStyle.primary)
        btn_on.callback = self.on_enable
        btn_off.callback = self.on_disable
        btn_ping.callback = self.on_ping
        self.add_item(btn_on)
        self.add_item(btn_off)
        self.add_item(btn_ping)

    async def on_enable(self, interaction: discord.Interaction) -> None:
        interaction.client.test_mode = True
        await interaction.response.send_message("Test mode enabled for this session.", ephemeral=True)

    async def on_disable(self, interaction: discord.Interaction) -> None:
        interaction.client.test_mode = False
        await interaction.response.send_message("Test mode disabled for this session.", ephemeral=True)

    async def on_ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("pong", ephemeral=True)


class TournamentsView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        btn_dashboard = discord.ui.Button(label="Coach Dashboard", style=discord.ButtonStyle.primary)
        btn_staff = discord.ui.Button(label="Staff Review Tips", style=discord.ButtonStyle.secondary)
        btn_unlock = discord.ui.Button(label="Unlock Guidance", style=discord.ButtonStyle.secondary)
        btn_dashboard.callback = self.on_dashboard
        btn_staff.callback = self.on_staff
        btn_unlock.callback = self.on_unlock
        self.add_item(btn_dashboard)
        self.add_item(btn_staff)
        self.add_item(btn_unlock)

    async def on_dashboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Coaches open the roster dashboard from the portal; choose the correct tournament when prompted.",
            ephemeral=True,
        )

    async def on_staff(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Staff approve/reject from the submission message buttons; keep submissions channel tidy.",
            ephemeral=True,
        )

    async def on_unlock(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Unlock rosters from this portal after verifying coach intent; locked rosters cannot be edited by coaches.",
            ephemeral=True,
        )


class CoachesView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        btn_help = discord.ui.Button(label="Coach Help", style=discord.ButtonStyle.primary)
        btn_unlock = discord.ui.Button(label="Unlock Roster", style=discord.ButtonStyle.secondary)
        btn_help.callback = self.on_help
        btn_unlock.callback = self.on_unlock
        self.add_item(btn_help)
        self.add_item(btn_unlock)

    async def on_help(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=_coach_help_embed(), ephemeral=True)

    async def on_unlock(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "To unlock, confirm the coach and tournament cycle, then use the portal unlock action.",
            ephemeral=True,
        )


class RostersView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        btn_flow = discord.ui.Button(label="Submission Flow", style=discord.ButtonStyle.primary)
        btn_audit = discord.ui.Button(label="Audit Info", style=discord.ButtonStyle.secondary)
        btn_flow.callback = self.on_flow
        btn_audit.callback = self.on_audit
        self.add_item(btn_flow)
        self.add_item(btn_audit)

    async def on_flow(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Flow: create roster → add players → submit (locks) → staff approve/reject → unlock if needed.",
            ephemeral=True,
        )

    async def on_audit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Approvals, rejections, and unlocks are recorded in the audit collection.",
            ephemeral=True,
        )


class PlayersView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        btn_fields = discord.ui.Button(label="Player Fields", style=discord.ButtonStyle.primary)
        btn_ban = discord.ui.Button(label="Ban Checks", style=discord.ButtonStyle.secondary)
        btn_errors = discord.ui.Button(label="Common Errors", style=discord.ButtonStyle.secondary)
        btn_fields.callback = self.on_fields
        btn_ban.callback = self.on_ban
        btn_errors.callback = self.on_errors
        self.add_item(btn_fields)
        self.add_item(btn_ban)
        self.add_item(btn_errors)

    async def on_fields(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Player fields: Discord mention/ID, Gamertag/PSN, EA ID, Console (PS/XBOX/PC/SWITCH).",
            ephemeral=True,
        )

    async def on_ban(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Ban checks run when configured with BANLIST_* and Google Sheets credentials; blocked players are rejected.",
            ephemeral=True,
        )

    async def on_errors(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Common errors: duplicate player, cap reached, invalid console, banned player.",
            ephemeral=True,
        )


class DBView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        btn_schema = discord.ui.Button(label="Schema", style=discord.ButtonStyle.primary)
        btn_indexes = discord.ui.Button(label="Indexes", style=discord.ButtonStyle.secondary)
        btn_future = discord.ui.Button(label="Future", style=discord.ButtonStyle.secondary)
        btn_schema.callback = self.on_schema
        btn_indexes.callback = self.on_indexes
        btn_future.callback = self.on_future
        self.add_item(btn_schema)
        self.add_item(btn_indexes)
        self.add_item(btn_future)

    async def on_schema(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Collections: tournament_cycle, team_roster, roster_player, submission_message, roster_audit.",
            ephemeral=True,
        )

    async def on_indexes(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Indexes: unique roster per coach/cycle, roster player, submission message, audit index.",
            ephemeral=True,
        )

    async def on_future(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Future: health checks, exports, analytics dashboards.",
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
        settings, settings.channel_staff_portal_id, test_mode=test_mode
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

    # Delete prior portal embeds posted by the bot to keep the channel tidy.
    try:
        async for message in channel.history(limit=20):
            if message.author.id == interaction.client.user.id:
                if message.embeds and message.embeds[0].title == "Admin Control Panel":
                    try:
                        await message.delete()
                    except discord.DiscordException:
                        pass
    except discord.DiscordException:
        pass

    embed = build_admin_embed()
    view = AdminPortalView()
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(
        f"Posted admin control panel to <#{target_channel_id}>.",
        ephemeral=True,
    )


async def post_admin_portal(bot: commands.Bot) -> None:
    settings = getattr(bot, "settings", None)
    if settings is None:
        return

    test_mode = bool(getattr(bot, "test_mode", False))
    target_channel_id = resolve_channel_id(
        settings, settings.channel_staff_portal_id, test_mode=test_mode
    )

    channel = bot.get_channel(target_channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(target_channel_id)
        except discord.DiscordException:
            return

    try:
        async for message in channel.history(limit=20):
            if message.author.id == bot.user.id:
                if message.embeds and message.embeds[0].title == "Admin Control Panel":
                    try:
                        await message.delete()
                    except discord.DiscordException:
                        pass
    except discord.DiscordException:
        pass

    embed = build_admin_embed()
    view = AdminPortalView()
    try:
        await channel.send(embed=embed, view=view)
    except discord.DiscordException:
        return
