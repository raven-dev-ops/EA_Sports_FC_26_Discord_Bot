from __future__ import annotations

import discord
from config.settings import Settings


def is_staff_user(user: discord.abc.User, settings: Settings | None) -> bool:
    """
    Determine if a Discord user should be treated as staff.
    Prefers configured STAFF_ROLE_IDS; falls back to manage_guild permission.
    """
    if settings is None:
        return False
    if getattr(user, "guild_permissions", None) and user.guild_permissions.manage_guild:
        return True
    user_roles = {r.id for r in getattr(user, "roles", []) if hasattr(r, "id")}
    return bool(user_roles.intersection(getattr(settings, "staff_role_ids", set())))
