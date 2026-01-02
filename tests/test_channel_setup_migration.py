import pytest

from services import channel_setup_service


class FakeTextChannel:
    def __init__(self, channel_id: int, name: str) -> None:
        self.id = channel_id
        self.name = name

    async def edit(self, *, name: str, reason: str) -> None:
        self.name = name


class FakeCategory:
    def __init__(self, text_channels: list[FakeTextChannel]) -> None:
        self.text_channels = text_channels


class FakeGuild:
    def __init__(self, channels: list[FakeTextChannel]) -> None:
        self.text_channels = channels
        self._channels_by_id = {channel.id: channel for channel in channels}

    def get_channel(self, channel_id: int):
        return self._channels_by_id.get(channel_id)


@pytest.mark.asyncio
async def test_roster_listing_migrates_to_club_listing(monkeypatch) -> None:
    roster_channel = FakeTextChannel(11, channel_setup_service.ROSTER_LISTING_CHANNEL_NAME)
    reports_category = FakeCategory([roster_channel])
    guild = FakeGuild([roster_channel])
    config = {"channel_roster_listing_id": 11}
    actions: list[str] = []

    monkeypatch.setattr(channel_setup_service.discord, "TextChannel", FakeTextChannel)

    await channel_setup_service._migrate_roster_listing_channel(
        guild,
        config=config,
        reports_category=reports_category,
        actions=actions,
    )

    assert config.get("channel_club_listing_id") == 11
    assert "channel_roster_listing_id" not in config
    assert roster_channel.name == channel_setup_service.CLUB_LISTING_CHANNEL_NAME


@pytest.mark.asyncio
async def test_existing_club_listing_wins_over_roster_listing(monkeypatch) -> None:
    roster_channel = FakeTextChannel(11, channel_setup_service.ROSTER_LISTING_CHANNEL_NAME)
    club_channel = FakeTextChannel(22, channel_setup_service.CLUB_LISTING_CHANNEL_NAME)
    reports_category = FakeCategory([club_channel, roster_channel])
    guild = FakeGuild([club_channel, roster_channel])
    config = {"channel_roster_listing_id": 11}
    actions: list[str] = []

    monkeypatch.setattr(channel_setup_service.discord, "TextChannel", FakeTextChannel)

    await channel_setup_service._migrate_roster_listing_channel(
        guild,
        config=config,
        reports_category=reports_category,
        actions=actions,
    )

    assert config.get("channel_club_listing_id") == 22
    assert "channel_roster_listing_id" not in config
    assert club_channel.name == channel_setup_service.CLUB_LISTING_CHANNEL_NAME
