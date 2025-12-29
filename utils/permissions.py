from __future__ import annotations

import discord

from config.settings import Settings

REQUIRES_STAFF_KEY = "requires_staff"
STAFF_ONLY_COGS = {"StaffCog", "TournamentCog", "ConfigCog"}


def is_staff_user(user: discord.abc.User, settings: Settings | None) -> bool:
    """
    Determine if a Discord user should be treated as staff.
    Prefers configured STAFF_ROLE_IDS; falls back to manage_guild permission.
    """
    if settings is None:
        return False
    perms = getattr(user, "guild_permissions", None)
    if perms and getattr(perms, "manage_guild", False):
        return True
    user_roles = {r.id for r in getattr(user, "roles", []) if hasattr(r, "id")}
    return bool(user_roles.intersection(getattr(settings, "staff_role_ids", set())))


def mark_staff_command(command: discord.app_commands.Command) -> discord.app_commands.Command:
    """
    Add metadata used by the global permission guard to require staff access.
    """
    command.extras[REQUIRES_STAFF_KEY] = True
    return command


async def enforce_command_permissions(interaction: discord.Interaction) -> bool:
    """
    Global guard attached to the command tree.
    Honors command.extras[REQUIRES_STAFF_KEY] to enforce staff-only actions.
    """
    cmd = interaction.command
    if cmd is None:
        return True
    requires_staff = bool(cmd.extras.get(REQUIRES_STAFF_KEY))
    if getattr(cmd, "qualified_name", None):
        binding = getattr(cmd, "binding", None)
        if binding is not None:
            cog_name = getattr(binding, "__class__", type("", (), {})).__name__
            if cog_name in STAFF_ONLY_COGS:
                requires_staff = True
    if not requires_staff:
        return True
    settings = getattr(interaction.client, "settings", None)
    if is_staff_user(interaction.user, settings):
        return True
    try:
        await interaction.response.send_message(
            "You do not have permission to run this command.", ephemeral=True
        )
    except discord.DiscordException:
        pass
    return False
