"""Previous-local-calendar-day arithmetic.

A calendar day is not always 24 hours: DST transitions produce 23- and 25-hour
days, and in a few zones local midnight does not exist at all on the
spring-forward date. Every window in the app is derived from these helpers so
the frontend's `fractionOfDay` scale stays correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_PROBE_LIMIT = timedelta(hours=4)


def local_start_of_day(day: date, tz: ZoneInfo) -> datetime:
    """Earliest instant that belongs to `day` in `tz`.

    Normally 00:00. On a spring-forward date where midnight is skipped (for
    example America/Santiago), returns the first local wall-clock time that
    actually exists on that date.
    """
    naive = datetime.combine(day, time(0, 0))
    candidate = naive.replace(tzinfo=tz, fold=0)
    if _wall_clock_exists(candidate, tz):
        return candidate

    # Midnight was skipped. Walk forward a minute at a time to the first
    # wall-clock time that exists; DST jumps always land on a minute boundary.
    for minutes in range(1, int(_PROBE_LIMIT.total_seconds() // 60) + 1):
        shifted = (naive + timedelta(minutes=minutes)).replace(tzinfo=tz, fold=0)
        if _wall_clock_exists(shifted, tz):
            return shifted
    raise ValueError(f"Could not find a valid local start of day for {day} in {tz.key}")


def _wall_clock_exists(dt: datetime, tz: ZoneInfo) -> bool:
    """False when `dt` names a wall-clock time skipped by a DST jump.

    The comparison is on the naive wall-clock fields on purpose: comparing the
    aware values would compare instants, and a skipped time round-trips to the
    same instant as the time it was folded into.
    """
    roundtrip = dt.astimezone(timezone.utc).astimezone(tz)
    return roundtrip.replace(tzinfo=None, fold=0) == dt.replace(tzinfo=None, fold=0)


def elapsed(start: datetime, end: datetime) -> timedelta:
    """Real elapsed time between two aware datetimes.

    Python subtracts two datetimes that share a `tzinfo` object using their
    naive wall-clock fields, which silently reports a 23- or 25-hour day as 24
    hours. Normalising to UTC first is what makes the day scale correct.
    """
    return end.astimezone(timezone.utc) - start.astimezone(timezone.utc)



def _instant(moment: datetime) -> datetime:
    """Sort/compare key that ignores wall-clock ambiguity around DST."""
    return moment.astimezone(timezone.utc)


@dataclass(frozen=True)
class DayWindow:
    """The half-open interval [start, end) covering one local calendar day."""

    day: date
    start: datetime
    end: datetime
    timezone_name: str

    @property
    def length(self) -> timedelta:
        return elapsed(self.start, self.end)

    @property
    def length_hours(self) -> float:
        return self.length.total_seconds() / 3600.0

    @property
    def iso_date(self) -> str:
        return self.day.isoformat()

    def contains(self, moment: datetime) -> bool:
        instant = moment.astimezone(timezone.utc)
        return (
            self.start.astimezone(timezone.utc)
            <= instant
            < self.end.astimezone(timezone.utc)
        )

    def fraction_of_day(self, moment: datetime) -> float:
        """Position of `moment` in the window, clamped to [0, 1]."""
        total = self.length.total_seconds()
        if total <= 0:
            return 0.0
        offset = elapsed(self.start, moment).total_seconds()
        return max(0.0, min(1.0, offset / total))

    def clip(self, start: datetime, end: datetime) -> tuple[datetime, datetime] | None:
        """Intersect an interval with the day, or None when it does not overlap."""
        lower = max(start, self.start, key=_instant)
        upper = min(end, self.end, key=_instant)
        if _instant(upper) <= _instant(lower):
            return None
        return lower, upper

    def overlaps(self, start: datetime, end: datetime | None) -> bool:
        if end is None:
            return self.contains(start)
        return self.clip(start, end) is not None


def day_window(day: date, tz: ZoneInfo) -> DayWindow:
    return DayWindow(
        day=day,
        start=local_start_of_day(day, tz),
        end=local_start_of_day(day + timedelta(days=1), tz),
        timezone_name=tz.key,
    )


def previous_day(tz: ZoneInfo, *, now: datetime | None = None) -> DayWindow:
    """The local calendar day before the one `now` falls in."""
    reference = (now or datetime.now(timezone.utc)).astimezone(tz)
    return day_window(reference.date() - timedelta(days=1), tz)


def extended_window(window: DayWindow, *, before: timedelta, after: timedelta) -> tuple[datetime, datetime]:
    """Fetch window that also captures sleep starting the night before."""
    return window.start - before, window.end + after
