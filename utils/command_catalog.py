from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class CommandInfo:
    name: str
    category: str
    description: str
    permissions: str
    example: Optional[str] = None


COMMANDS: List[CommandInfo] = [
    # Roster / Coach
    CommandInfo(
        name="/roster [tournament]",
        category="Roster",
        description="Open the roster dashboard to create/add/remove/view/submit a team.",
        permissions="Coach roles",
        example="/roster tournament:\"Summer Cup\"",
    ),
    CommandInfo(
        name="/me",
        category="Recruitment",
        description="Show your stored recruit profile preview (ephemeral).",
        permissions="Anyone (in a guild)",
    ),
    CommandInfo(
        name="/unlock_roster <coach> [tournament]",
        category="Roster",
        description="Unlock a coach roster for edits and clear stale submissions.",
        permissions="Staff",
        example="/unlock_roster @CoachUser tournament:\"Summer Cup\"",
    ),
    CommandInfo(
        name="/player_pool [position] [archetype] [platform] [mic]",
        category="Staff",
        description="Search recruit profiles (ephemeral).",
        permissions="Staff",
    ),
    CommandInfo(
        name="/player_pool_index",
        category="Staff",
        description="Post/update a pinned Player Pool index in the recruit listing channel.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/ping",
        category="Operations",
        description="Health check.",
        permissions="Anyone",
    ),
    CommandInfo(
        name="/help",
        category="Operations",
        description="Command catalog and workflow guidance (ephemeral).",
        permissions="Anyone",
    ),
    CommandInfo(
        name="/config_view",
        category="Operations",
        description="View non-secret runtime settings.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/config_set <field> <value>",
        category="Operations",
        description="Set a runtime config value (no persistence).",
        permissions="Staff",
        example="/config_set banlist_cache_ttl_seconds 600",
    ),
    CommandInfo(
        name="/config_guild_view",
        category="Operations",
        description="View per-guild overrides.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/config_guild_set <field> <value>",
        category="Operations",
        description="Set a per-guild override.",
        permissions="Staff",
        example="/config_guild_set announcements_channel 1234567890",
    ),
    CommandInfo(
        name="/rules_template",
        category="Operations",
        description="Get a starter rules template to paste and edit.",
        permissions="Staff",
    ),
    # Tournament
    CommandInfo(
        name="/tournament_dashboard",
        category="Tournament",
        description="Staff quick reference for tournament commands.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/tournament_create",
        category="Tournament",
        description="Create a tournament.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/tournament_state",
        category="Tournament",
        description="Update tournament state (DRAFT/REG_OPEN/IN_PROGRESS/COMPLETED).",
        permissions="Staff",
    ),
    CommandInfo(
        name="/tournament_register",
        category="Tournament",
        description="Register a team into a tournament.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/tournament_bracket",
        category="Tournament",
        description="Publish first-round bracket and advance state.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/tournament_bracket_preview",
        category="Tournament",
        description="Preview first-round bracket (no DB writes).",
        permissions="Staff",
    ),
    CommandInfo(
        name="/advance_round",
        category="Tournament",
        description="Advance to next round from recorded winners.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/tournament_stats",
        category="Tournament",
        description="Show wins/losses/GD leaderboard.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/match_report",
        category="Tournament",
        description="Report a match score.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/match_confirm",
        category="Tournament",
        description="Confirm a reported match.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/match_deadline",
        category="Tournament",
        description="Set or update a match deadline.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/match_forfeit",
        category="Tournament",
        description="Forfeit a match to a winner.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/match_reschedule",
        category="Tournament",
        description="Request a reschedule for a match.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/dispute_add",
        category="Tournament",
        description="File a dispute on a match.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/dispute_resolve",
        category="Tournament",
        description="Resolve the latest dispute on a match.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/group_create",
        category="Tournament",
        description="Create a group.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/group_register",
        category="Tournament",
        description="Register a team into a group.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/group_generate_fixtures",
        category="Tournament",
        description="Generate group fixtures (supports double_round).",
        permissions="Staff",
    ),
    CommandInfo(
        name="/group_match_report",
        category="Tournament",
        description="Report a group-stage match score.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/group_standings",
        category="Tournament",
        description="Show group standings.",
        permissions="Staff",
    ),
    CommandInfo(
        name="/group_advance",
        category="Tournament",
        description="Advance top N from group into bracket.",
        permissions="Staff",
    ),
]


def commands_by_category() -> dict[str, list[CommandInfo]]:
    buckets: dict[str, list[CommandInfo]] = {}
    for cmd in COMMANDS:
        buckets.setdefault(cmd.category, []).append(cmd)
    return buckets
