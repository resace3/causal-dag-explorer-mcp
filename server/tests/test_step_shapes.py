"""Steps reach the Activity row in two shapes, and confusing them is silent.

A cumulative counter has to be differenced to get a rate. Interval buckets are
already the increment. Run either through the other's path and nothing raises —
you get a plausible-looking line that is wrong by a factor of the day, or one
that hovers around zero. So the two paths are kept apart, and this file is the
thing that notices if they are ever quietly joined up.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.connectors.wearables.base import StepBucket, WearableCapabilities
from app.connectors.wearables.connector import WearablePayload
from app.feature_engineering.context import RuleContext
from app.feature_engineering.rules import activity
from app.models.raw import RawRecord
from app.normalization.normalizer import normalize
from app.services.day import day_window

DAY = date(2025, 6, 10)


def _at(new_york, hour: float) -> datetime:
    return datetime(2025, 6, 10, tzinfo=new_york) + timedelta(hours=hour)


def _payload(buckets: list[StepBucket]) -> WearablePayload:
    return WearablePayload(
        steps=buckets,
        capabilities=WearableCapabilities(
            provider="google_health_mcp",
            device="Inspire 3",
            capabilities=["steps"],
        ),
        status="connected",
    )


def _buckets(new_york, spec: list[tuple[float, float, int]]) -> list[StepBucket]:
    """`(start_hour, end_hour, steps_per_minute)` expanded to per-minute buckets."""
    out: list[StepBucket] = []
    for start_hour, end_hour, per_minute in spec:
        cursor = _at(new_york, start_hour)
        finish = _at(new_york, end_hour)
        while cursor < finish:
            out.append(
                StepBucket(
                    start=cursor,
                    end=cursor + timedelta(minutes=1),
                    count=per_minute,
                    device="Inspire 3",
                )
            )
            cursor += timedelta(minutes=1)
    return out


def _counter(new_york, readings: list[tuple[float, int]]) -> list[RawRecord]:
    return [
        RawRecord(
            id=RawRecord.make_id("home_assistant", "steps", f"sensor.steps|{hour}"),
            source="home_assistant",
            stream="steps",
            entity_id="sensor.steps",
            device="Fitbit",
            timestamp=_at(new_york, hour),
            value=float(total),
            unit="steps",
            attributes={"raw_state": str(total), "unavailable": False},
        )
        for hour, total in readings
    ]


def _context(new_york, sync_service, *, records=None, payload=None) -> RuleContext:
    window = day_window(DAY, new_york)
    start = window.start - timedelta(hours=14)
    end = window.end + timedelta(hours=12)
    return RuleContext(
        window=window,
        fetch_start=start,
        fetch_end=end,
        tz=new_york,
        config=sync_service.config.feature_engineering,
        normalized=normalize(records or [], start, end, now=end),
        wearable=payload or WearablePayload(),
    )


def _series(lane):
    return lane.series[0] if lane.series else None


# --------------------------------------------------------------------------
# Interval buckets
# --------------------------------------------------------------------------


def test_buckets_are_summed_into_bins_never_differenced(new_york, sync_service):
    """One hour at a steady 100 steps/min is 100 steps/min, not zero.

    Differencing deltas gives the change *between* minutes, which for a steady
    walk is nothing at all — a bug that draws a flat line through a brisk hour.
    """
    payload = _payload(_buckets(new_york, [(9, 10, 100)]))
    lane = activity.build_lane(_context(new_york, sync_service, payload=payload))
    series = _series(lane)

    assert series is not None
    walking = [point for point in series.points if point.value > 0]
    assert walking, "an hour of walking must not flatten to nothing"
    assert all(abs(point.value - 100) < 1e-6 for point in walking)
    assert series.metadata["totalStepsForDay"] == 6000
    assert series.metadata["shape"] == "interval_deltas"


def test_a_minute_the_provider_omitted_is_zero_not_missing(new_york, sync_service):
    """This source omits minutes with no steps. A night is stillness, not a fault."""
    payload = _payload(_buckets(new_york, [(9, 9.5, 80)]))
    lane = activity.build_lane(_context(new_york, sync_service, payload=payload))
    series = _series(lane)

    assert series is not None
    assert series.gaps == [], "silence in a delta stream is zero, not a recording gap"
    assert any(point.value == 0 for point in series.points), "quiet bins are drawn as zero"
    assert "not as missing data" in series.metadata["note"]


def test_the_line_stops_at_the_last_reported_minute(new_york, sync_service):
    """On a day still running, after the last bucket nothing is known — not zero."""
    payload = _payload(_buckets(new_york, [(9, 10, 90)]))
    lane = activity.build_lane(_context(new_york, sync_service, payload=payload))
    series = _series(lane)

    assert series is not None
    assert max(point.timestamp for point in series.points) < _at(new_york, 10.25)


def test_a_walk_in_buckets_becomes_a_walking_period(new_york, sync_service):
    payload = _payload(_buckets(new_york, [(9, 10, 110)]))
    lane = activity.build_lane(_context(new_york, sync_service, payload=payload))

    walking = [event for event in lane.events if event.category == "walking_period"]
    assert len(walking) == 1
    assert walking[0].metadata["steps"] == pytest.approx(6600, abs=1)
    assert walking[0].provenance.raw_record_ids


def test_a_walk_is_only_located_as_finely_as_the_bins_are(new_york, sync_service):
    """A partly-filled bin has a partly-diluted rate, and can fall under the
    cadence threshold. That is the cost of `bucket_minutes`, not a bug — but it
    is the reason to keep bins near the resolution of the source rather than
    wide enough to hide a burst-syncing counter that no longer feeds this."""
    # 45 minutes of walking: 9:00-9:30 fills a bin, 9:30-9:45 fills half of one.
    payload = _payload(_buckets(new_york, [(9, 9.75, 110)]))
    lane = activity.build_lane(_context(new_york, sync_service, payload=payload))

    walking = [event for event in lane.events if event.category == "walking_period"]
    assert [event.metadata["steps"] for event in walking] == [3300]
    # None of the steps are lost — they are all still in the day's total.
    assert _series(lane).metadata["totalStepsForDay"] == 4950


def test_a_discarded_device_is_disclosed_even_when_flagged_outside_the_day(
    new_york, sync_service
):
    """The connector marks the first bucket it returns, which is the previous
    evening. Looking for the mark only inside the day silently loses it."""
    payload = _payload(_buckets(new_york, [(-3, -2, 50), (9, 10, 100)]))
    payload.steps[0].metadata["chosenOver"] = [
        {"device": None, "platform": "HEALTH_CONNECT", "buckets": 120, "steps": 7084}
    ]
    context = _context(new_york, sync_service, payload=payload)
    lane = activity.build_lane(context)

    assert lane.series[0].metadata["otherSourcesDiscarded"]
    warning = next(w for w in context.warnings if "7,084 steps" in w)
    assert "would inflate the day" in warning


def test_bucket_provenance_says_it_was_not_differenced(new_york, sync_service):
    payload = _payload(_buckets(new_york, [(9, 10, 100)]))
    lane = activity.build_lane(_context(new_york, sync_service, payload=payload))

    notes = " ".join(_series(lane).provenance.notes)
    assert "never differenced" in notes


# --------------------------------------------------------------------------
# The cumulative counter, which must keep working
# --------------------------------------------------------------------------


def test_a_counter_is_still_differenced_when_no_buckets_arrive(new_york, sync_service):
    records = _counter(new_york, [(9, 1000), (9.5, 4000), (10, 4100)])
    lane = activity.build_lane(_context(new_york, sync_service, records=records))
    series = _series(lane)

    assert series is not None
    assert series.metadata.get("shape") != "interval_deltas"
    # 3000 steps across 30 minutes.
    assert series.points[0].value == pytest.approx(100.0)
    assert series.metadata["totalStepsForDay"] == 4100


def test_counter_silence_is_still_a_gap(new_york, sync_service):
    """A counter reports on a schedule, so silence really is missing data —
    the opposite reading from the delta stream, and deliberately so."""
    records = _counter(new_york, [(1, 100), (1.5, 200), (2, 300)])
    lane = activity.build_lane(_context(new_york, sync_service, records=records))

    assert _series(lane).gaps, "a counter that stops reporting is missing, not still"


# --------------------------------------------------------------------------
# Which one wins
# --------------------------------------------------------------------------


def test_buckets_win_over_a_counter_and_are_not_added_to_it(new_york, sync_service):
    """Both sources describe the same feet. Summing them would double the day."""
    payload = _payload(_buckets(new_york, [(9, 10, 100)]))
    records = _counter(new_york, [(9, 1000), (9.5, 4000), (10, 4100)])
    lane = activity.build_lane(
        _context(new_york, sync_service, records=records, payload=payload)
    )
    series = _series(lane)

    assert series.metadata["shape"] == "interval_deltas"
    assert series.metadata["totalStepsForDay"] == 6000
    assert series.source.startswith("wearable:")


def test_a_provider_with_no_steps_for_the_day_falls_back_to_the_counter(
    new_york, sync_service
):
    """Pinning governs which provider answers; an empty answer is still empty,
    and the row would rather show the coarser shape than nothing."""
    records = _counter(new_york, [(9, 1000), (9.5, 4000), (10, 4100)])
    lane = activity.build_lane(
        _context(new_york, sync_service, records=records, payload=_payload([]))
    )

    assert _series(lane).metadata["totalStepsForDay"] == 4100
