from __future__ import annotations

import pytest

from offside_bot import dashboard


@pytest.mark.parametrize(
    "guild,expected",
    [
        ({"owner": True}, True),
        ({"owner": False, "permissions": str(dashboard.PERM_ADMINISTRATOR)}, True),
        ({"owner": False, "permissions": str(dashboard.PERM_MANAGE_GUILD)}, True),
        ({"owner": False, "permissions": str(dashboard.PERM_MANAGE_GUILD | dashboard.PERM_SEND_MESSAGES)}, True),
        ({"owner": False, "permissions": "0"}, False),
        ({"owner": False, "permissions": None}, False),
        ({"owner": False, "permissions": "not-a-number"}, False),
        ({}, False),
    ],
)
def test_guild_is_eligible(guild, expected):
    assert dashboard._guild_is_eligible(guild) is expected
