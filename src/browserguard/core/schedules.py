"""Time-based rules, e.g. block social media during school hours.

Browser policy has no concept of time, so schedules work by recomputing the
effective settings and rewriting policy whenever a window opens or closes. The
background task registered in :mod:`browserguard.core.scheduler` drives that.

A schedule can only ever add restrictions on top of the base settings. It cannot
remove one, which keeps schedules from becoming a way around the cooldown.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, time
from typing import Any

from browserguard.core.config import ProtectionSettings

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass
class Schedule:
    """A recurring window during which extra restrictions apply."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = "New schedule"
    enabled: bool = True
    days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    start: str = "09:00"
    end: str = "15:00"
    categories: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Schedule:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def describe(self) -> str:
        if len(self.days) == 7:
            days = "Every day"
        elif self.days == [0, 1, 2, 3, 4]:
            days = "Weekdays"
        elif self.days == [5, 6]:
            days = "Weekends"
        else:
            days = ", ".join(DAY_NAMES[d] for d in sorted(self.days))
        what = ", ".join(self.categories) if self.categories else ""
        if self.urls:
            what = f"{what} +{len(self.urls)} sites" if what else f"{len(self.urls)} sites"
        return f"{days} {self.start}-{self.end}" + (f" - blocks {what}" if what else "")


def _parse_time(value: str) -> time:
    hour, _, minute = value.partition(":")
    return time(int(hour), int(minute or 0))


def is_active(schedule: Schedule, now: datetime | None = None) -> bool:
    """Whether a schedule's window covers the given moment.

    Windows that wrap past midnight (22:00-06:00) are handled by treating the
    day-of-week as the day the window started.
    """
    if not schedule.enabled:
        return False
    now = now or datetime.now()
    start = _parse_time(schedule.start)
    end = _parse_time(schedule.end)
    current = now.time()
    weekday = now.weekday()

    if start <= end:
        return weekday in schedule.days and start <= current < end
    # Overnight window.
    if weekday in schedule.days and current >= start:
        return True
    previous_day = (weekday - 1) % 7
    return previous_day in schedule.days and current < end


def active_schedules(schedules: list[Schedule], now: datetime | None = None) -> list[Schedule]:
    return [s for s in schedules if is_active(s, now)]


def effective_settings(
    base: ProtectionSettings,
    schedules: list[Schedule],
    now: datetime | None = None,
) -> ProtectionSettings:
    """Merge any active schedule's restrictions into the base settings."""
    active = active_schedules(schedules, now)
    if not active:
        return base

    categories = list(base.blocked_categories)
    urls = list(base.custom_blocked)
    for schedule in active:
        for category in schedule.categories:
            if category not in categories:
                categories.append(category)
        for url in schedule.urls:
            if url not in urls:
                urls.append(url)
    return replace(base, blocked_categories=categories, custom_blocked=urls)


def load_schedules(raw: list[dict[str, Any]]) -> list[Schedule]:
    result = []
    for item in raw:
        try:
            result.append(Schedule.from_dict(item))
        except (TypeError, ValueError):
            continue
    return result


def next_transition(schedules: list[Schedule], now: datetime | None = None) -> str:
    """Describe the next time the effective policy will change, for the UI."""
    now = now or datetime.now()
    active = active_schedules(schedules, now)
    if active:
        ends = sorted(s.end for s in active)
        return f"Active until {ends[0]}"
    upcoming = sorted(
        (s.start, s.name) for s in schedules if s.enabled and now.weekday() in s.days
    )
    for start, name in upcoming:
        if _parse_time(start) > now.time():
            return f"{name} starts at {start}"
    return "No schedule active"
