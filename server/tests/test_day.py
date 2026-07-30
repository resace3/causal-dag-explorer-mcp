"""Previous-day arithmetic, including daylight-saving transitions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.day import day_window, local_start_of_day, previous_day


def test_previous_day_is_the_local_calendar_day_before(new_york):
    now = datetime(2025, 6, 11, 0, 30, tzinfo=new_york)
    window = previous_day(new_york, now=now)
    assert window.day == date(2025, 6, 10)
    assert window.start.isoformat() == "2025-06-10T00:00:00-04:00"
    assert window.end.isoformat() == "2025-06-11T00:00:00-04:00"
    assert window.length_hours == 24.0


def test_previous_day_uses_local_time_not_utc(new_york):
    """01:00 UTC on the 11th is still the 10th in New York."""
    now = datetime(2025, 6, 11, 1, 0, tzinfo=ZoneInfo("UTC"))
    window = previous_day(new_york, now=now)
    assert window.day == date(2025, 6, 9)


def test_spring_forward_day_is_23_hours(new_york):
    window = day_window(date(2025, 3, 9), new_york)
    assert window.length_hours == pytest.approx(23.0)
    assert window.start.utcoffset() == timedelta(hours=-5)
    assert window.end.utcoffset() == timedelta(hours=-4)


def test_fall_back_day_is_25_hours(new_york):
    window = day_window(date(2025, 11, 2), new_york)
    assert window.length_hours == pytest.approx(25.0)


def test_fraction_of_day_uses_real_day_length(new_york):
    window = day_window(date(2025, 3, 9), new_york)

    # 11.5 hours of *real* elapsed time is the midpoint of a 23-hour day.
    midpoint = window.start.astimezone(ZoneInfo("UTC")) + timedelta(hours=11.5)
    assert window.fraction_of_day(midpoint) == pytest.approx(0.5)

    # Local noon is 11 real hours in, so it must sit before the midpoint —
    # a naive 24-hour assumption would place it at exactly 0.5.
    local_noon = datetime(2025, 3, 9, 12, 0, tzinfo=new_york)
    assert window.fraction_of_day(local_noon) == pytest.approx(11 / 23)
    assert window.fraction_of_day(local_noon) < 0.5


def test_midnight_that_does_not_exist_falls_forward():
    """America/Santiago skips 00:00 on its spring-forward date."""
    santiago = ZoneInfo("America/Santiago")
    start = local_start_of_day(date(2025, 9, 7), santiago)
    assert start.date() == date(2025, 9, 7)
    assert start.hour == 1
    assert start.minute == 0


def test_clip_returns_none_when_outside_the_day(new_york):
    window = day_window(date(2025, 6, 10), new_york)
    before = datetime(2025, 6, 9, 10, tzinfo=new_york)
    assert window.clip(before, before + timedelta(hours=2)) is None


def test_clip_trims_an_interval_crossing_midnight(new_york):
    window = day_window(date(2025, 6, 10), new_york)
    start = datetime(2025, 6, 9, 23, 10, tzinfo=new_york)
    end = datetime(2025, 6, 10, 7, 0, tzinfo=new_york)
    clipped = window.clip(start, end)
    assert clipped is not None
    assert clipped[0] == window.start
    assert clipped[1] == end


def test_utc_timezone_day_is_24_hours():
    window = day_window(date(2025, 3, 9), ZoneInfo("UTC"))
    assert window.length_hours == 24.0
