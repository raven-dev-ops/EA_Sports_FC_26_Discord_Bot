from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class Availability:
    days: list[int]
    start_hour: int
    end_hour: int

    def validate(self) -> None:
        validate_availability(self.days, start_hour=self.start_hour, end_hour=self.end_hour)


def validate_availability(days: list[int], *, start_hour: int, end_hour: int) -> None:
    if not days:
        raise ValueError("Select at least one day.")
    for day in days:
        if day < 0 or day > 6:
            raise ValueError("Day values must be between 0 (Mon) and 6 (Sun).")
    if start_hour < 0 or start_hour > 23:
        raise ValueError("Start hour must be between 0 and 23.")
    if end_hour < 0 or end_hour > 23:
        raise ValueError("End hour must be between 0 and 23.")
    if end_hour <= start_hour:
        raise ValueError("End hour must be greater than start hour.")


def format_days(days: list[int]) -> str:
    ordered = sorted({d for d in days if 0 <= d <= 6})
    return ", ".join(WEEKDAY_LABELS[d] for d in ordered)


def next_weekday_local_time(
    *,
    weekday: int,
    hour: int,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> datetime:
    """
    Return the next occurrence of a weekday+hour in the given timezone, using local wall time.

    `weekday`: Python weekday (Mon=0 .. Sun=6)
    `hour`: 0..23
    """
    if now is None:
        now = datetime.now(tz)
    local_now = now.astimezone(tz)

    delta_days = (weekday - local_now.weekday()) % 7
    target_date = local_now.date() + timedelta(days=delta_days)
    candidate = datetime.combine(target_date, time(hour=hour, minute=0), tzinfo=tz)
    if candidate <= local_now:
        candidate = datetime.combine(
            target_date + timedelta(days=7),
            time(hour=hour, minute=0),
            tzinfo=tz,
        )

    roundtrip = candidate.astimezone(timezone.utc).astimezone(tz)
    if roundtrip.replace(tzinfo=None) != candidate.replace(tzinfo=None):
        candidate = roundtrip
    return candidate


def next_availability_start(
    availability: Availability,
    *,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> datetime | None:
    availability.validate()
    soonest: datetime | None = None
    for day in sorted(set(availability.days)):
        candidate = next_weekday_local_time(weekday=day, hour=availability.start_hour, tz=tz, now=now)
        if soonest is None or candidate < soonest:
            soonest = candidate
    return soonest

