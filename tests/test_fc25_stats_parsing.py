from __future__ import annotations

import json
from pathlib import Path

from interactions.fc25_stats_modals import _extract_club_name, _find_member
from interactions.recruit_embeds import _format_fc25_totals
from utils.fc25 import parse_club_id_from_url, platform_key_from_user_input


def _fixture_members_career_stats() -> dict:
    path = Path(__file__).parent / "fixtures" / "fc25_members_career_stats.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_parse_club_id_from_url() -> None:
    assert parse_club_id_from_url("12345") == 12345
    assert parse_club_id_from_url("https://example.com/?clubId=555") == 555
    assert parse_club_id_from_url("clubId=777") == 777
    assert parse_club_id_from_url("nope") is None


def test_platform_key_from_user_input() -> None:
    assert platform_key_from_user_input("", default="common-gen5") == "common-gen5"
    assert platform_key_from_user_input("pc", default="common-gen5") == "common-pc"
    assert platform_key_from_user_input("PS5", default="common-pc") == "common-gen5"
    assert platform_key_from_user_input("xbox", default="common-gen5") is None


def test_find_member_and_totals() -> None:
    data = _fixture_members_career_stats()
    assert _extract_club_name(data) == "Example FC"

    member, stats = _find_member(data, "playerone")
    assert member == "PlayerOne"
    assert stats is not None
    assert stats["goals"] == 45

    totals = _format_fc25_totals(stats)
    assert totals is not None
    assert "Matches: 123" in totals
    assert "Goals: 45" in totals
    assert "Assists: 27" in totals


def test_find_member_by_nested_name() -> None:
    data = _fixture_members_career_stats()
    member, stats = _find_member(data, "playertwo")
    assert member == "PlayerTwo"
    assert stats is not None
    assert stats["gamesPlayed"] == 12

