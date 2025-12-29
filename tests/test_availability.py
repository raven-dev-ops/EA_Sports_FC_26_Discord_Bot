from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from utils.availability import Availability, next_weekday_local_time, validate_availability


def test_validate_availability_rejects_invalid_range() -> None:
    with pytest.raises(ValueError, match="End hour must be greater"):
        validate_availability([0], start_hour=10, end_hour=10)


def test_next_weekday_local_time_respects_dst_offset_change() -> None:
    tz = ZoneInfo("America/New_York")
    now = datetime(2025, 3, 8, 12, 0, tzinfo=tz)  # Saturday before US DST start

    sunday_1am = next_weekday_local_time(weekday=6, hour=1, tz=tz, now=now)
    assert sunday_1am.strftime("%Y-%m-%d %H:%M") == "2025-03-09 01:00"
    assert int(sunday_1am.utcoffset().total_seconds()) == -5 * 3600

    sunday_3am = next_weekday_local_time(weekday=6, hour=3, tz=tz, now=now)
    assert sunday_3am.strftime("%Y-%m-%d %H:%M") == "2025-03-09 03:00"
    assert int(sunday_3am.utcoffset().total_seconds()) == -4 * 3600


def test_availability_dataclass_validation() -> None:
    availability = Availability(days=[0, 2, 4], start_hour=18, end_hour=22)
    availability.validate()

