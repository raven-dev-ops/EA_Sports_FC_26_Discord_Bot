from __future__ import annotations

from typing import Any

import discord

from config.settings import Settings
from services.guild_config_service import get_guild_config

REQUIRES_STAFF_KEY = "requires_staff"
STAFF_ONLY_COGS = {"StaffCog", "TournamentCog", "ConfigCog"}
STAFF_ROLE_IDS_KEY = "staff_role_ids"


def _parse_int_set(value: Any) -> set[int]:
    if value is None:
        return set()
    if isinstance(value, bool):
        return set()
    if isinstance(value, int):
        return {value}
    if isinstance(value, str):
        out: set[int] = set()
        for part in value.split(","):
            token = part.strip()
            if not token:
                continue
            try:
                out.add(int(token))
            except ValueError:
                continue
        return out
    if isinstance(value, (list, tuple, set)):
        out = set()
        for item in value:
            if isinstance(item, int) and not isinstance(item, bool):
                out.add(item)
            elif isinstance(item, str):
                try:
                    out.add(int(item.strip()))
                except ValueError:
                    continue
        return out
    return set()


def is_staff_user(user: discord.abc.User, settings: Settings | None, *, guild_id: int | None = None) -> bool:
    """
    Determine if a Discord user should be treated as staff.
    Prefers configured STAFF_ROLE_IDS; falls back to manage_guild permission.
    """
    if settings is None:
        return False
    perms = getattr(user, "guild_permissions", None)
    if perms and getattr(perms, "manage_guild", False):
        return True
    staff_role_ids = set(getattr(settings, "staff_role_ids", set()))
    if guild_id and getattr(settings, "mongodb_uri", None):
        try:
            cfg = get_guild_config(guild_id)
        except Exception:
            cfg = {}
        staff_role_ids |= _parse_int_set(cfg.get(STAFF_ROLE_IDS_KEY))
    user_roles = {r.id for r in getattr(user, "roles", []) if hasattr(r, "id")}
    return bool(user_roles.intersection(staff_role_ids))


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
    if is_staff_user(interaction.user, settings, guild_id=getattr(interaction, "guild_id", None)):
        return True
    try:
        await interaction.response.send_message(
            "You do not have permission to run this command.", ephemeral=True
        )
    except discord.DiscordException:
        pass
    return False
