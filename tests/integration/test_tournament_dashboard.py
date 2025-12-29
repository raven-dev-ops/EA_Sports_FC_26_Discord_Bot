from types import SimpleNamespace

import pytest

from cogs.tournament import TournamentCog


class DummyResponse:
    def __init__(self):
        self.sent = None
        self.kw = None

    async def send_message(self, *args, **kwargs):
        self.sent = args
        self.kw = kwargs


class DummyInteraction:
    def __init__(self, user):
        self.user = user
        self.response = DummyResponse()


@pytest.mark.asyncio
async def test_tournament_dashboard_allows_staff(monkeypatch):
    # Staff via manage_guild
    settings = SimpleNamespace(staff_role_ids=set())
    user = SimpleNamespace(roles=[], guild_permissions=SimpleNamespace(manage_guild=True))
    bot = SimpleNamespace(settings=settings)
    cog = TournamentCog(bot)

    interaction = DummyInteraction(user)
    await cog.tournament_dashboard.callback(cog, interaction)
    # Should have sent an embed ephemerally
    assert interaction.response.kw["ephemeral"] is True
    assert "embed" in interaction.response.kw or "embeds" in interaction.response.kw
