from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Set
from zoneinfo import ZoneInfo


def _parse_field(token: str, *, minimum: int, maximum: int) -> Optional[Set[int]]:
    token = token.strip()
    if token == "*":
        return None

    values: Set[int] = set()
    for part in token.split(","):
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
            if base == "*":
                start, end = minimum, maximum
            elif "-" in base:
                start_text, end_text = base.split("-", 1)
                start, end = int(start_text), int(end_text)
            else:
                start = int(base)
                end = maximum
            values.update(range(start, end + 1, step))
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            values.update(range(int(start_text), int(end_text) + 1))
            continue
        values.add(int(part))
    return values


@dataclass(frozen=True)
class CronExpression:
    minute: Optional[Set[int]]
    hour: Optional[Set[int]]
    day_of_month: Optional[Set[int]]
    month: Optional[Set[int]]
    day_of_week: Optional[Set[int]]
    timezone: str = "UTC"

    @classmethod
    def parse(cls, expr: str, *, timezone: str = "UTC") -> "CronExpression":
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError("Cron expression must have 5 fields.")
        return cls(
            minute=_parse_field(parts[0], minimum=0, maximum=59),
            hour=_parse_field(parts[1], minimum=0, maximum=23),
            day_of_month=_parse_field(parts[2], minimum=1, maximum=31),
            month=_parse_field(parts[3], minimum=1, maximum=12),
            day_of_week=_parse_field(parts[4], minimum=0, maximum=6),
            timezone=timezone,
        )

    def slot_for(self, when: datetime) -> datetime:
        localized = when.astimezone(ZoneInfo(self.timezone))
        return localized.replace(second=0, microsecond=0)

    def matches(self, when: datetime) -> bool:
        slot = self.slot_for(when)
        return all(
            matcher is None or value in matcher
            for matcher, value in (
                (self.minute, slot.minute),
                (self.hour, slot.hour),
                (self.day_of_month, slot.day),
                (self.month, slot.month),
                (self.day_of_week, (slot.weekday() + 1) % 7),
            )
        )
