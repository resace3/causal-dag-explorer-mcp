"""Placing the causal graph on a real day's clock.

The nodes are the only part of the DAG view that claims to be observation, so
these tests are mostly about what grounding refuses to do: invent a time,
attach an arrow to a state that held all day, or let an effect precede its
cause.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.causal.dag import build_dag
from app.causal import grounding, knowledge
from app.causal.grounding import IMMEDIATE_MAX_MINUTES, ground
from app.main import create_app
from app.models.timeline import DayTimeline, Lane, SeriesPoint, TimelineEvent, TimelineSeries

TZ = "America/New_York"


@pytest.fixture
def client(repository, sync_service):
    app = create_app()
    routes.configure(repository, sync_service)
    with TestClient(app) as test_client:
        routes.configure(repository, sync_service)
        yield test_client


@pytest.fixture
def seeded_day(client):
    """A processed mock day, so the endpoint has a clock to place things on."""
    client.post("/api/yesterday/sync", json={"forceRefresh": True})
    return client


def _day() -> tuple[datetime, datetime]:
    start = datetime.fromisoformat("2026-07-27T00:00:00-04:00")
    return start, start + timedelta(days=1)


def _event(
    event_id: str,
    phenotype: str,
    category: str,
    start_hour: float,
    duration_minutes: float | None = None,
    value: float | str | None = None,
    unit: str | None = None,
    metadata: dict | None = None,
    continues_before: bool = False,
) -> TimelineEvent:
    day_start, _ = _day()
    start = day_start + timedelta(hours=start_hour)
    # The pipeline always publishes durationMinutes for an interval; the
    # captions rely on it, so the fixtures have to carry it too.
    metadata = dict(metadata or {})
    if duration_minutes and "durationMinutes" not in metadata:
        metadata["durationMinutes"] = duration_minutes
    return TimelineEvent(
        id=event_id,
        phenotype=phenotype,
        label=category.replace("_", " ").title(),
        event_type="interval" if duration_minutes else "point",
        start_time=start,
        end_time=start + timedelta(minutes=duration_minutes) if duration_minutes else None,
        value=value,
        unit=unit,
        source="test",
        measured_or_derived="derived",
        category=category,
        continues_before=continues_before,
        metadata=metadata,
    )


def _timeline(*lanes: Lane) -> DayTimeline:
    day_start, day_end = _day()
    return DayTimeline.model_construct(
        date="2026-07-27",
        local_timezone=TZ,
        day_start=day_start,
        day_end=day_end,
        day_length_hours=24.0,
        generated_at=day_start,
        lanes=list(lanes),
        summary=None,
        highlights=[],
        mock_data=True,
    )


def _lane(lane_id: str, events=(), series=(), available: bool = True) -> Lane:
    return Lane(
        id=lane_id,
        phenotype=lane_id,
        label=lane_id.title(),
        description="",
        accent="blue",
        available=available,
        events=list(events),
        series=list(series),
    )


@pytest.fixture
def workout_and_sleep() -> DayTimeline:
    """A workout in the morning, and the sleep that followed that evening."""
    return _timeline(
        _lane("activity", [_event("w1", "activity", "running", 7.0, 60, 1200, "steps")]),
        _lane(
            "sleep",
            [
                _event("s0", "sleep", "main_sleep", 0.0, 300, 300, "min", continues_before=True),
                _event("s1", "sleep", "main_sleep", 22.0, 120, 120, "min"),
            ],
        ),
    )


# --------------------------------------------------------------------------
# Nodes only where the day recorded something
# --------------------------------------------------------------------------


def test_a_node_appears_at_the_hour_the_event_happened(workout_and_sleep):
    grounded = ground(build_dag("sleep_duration", "exercise"), workout_and_sleep)
    exercise = [item for item in grounded.occurrences if item.variable == "exercise"]
    assert len(exercise) == 1
    assert exercise[0].start.hour == 7
    assert exercise[0].end is not None and exercise[0].end.hour == 8


def test_a_variable_the_day_never_recorded_gets_no_node(workout_and_sleep):
    grounded = ground(build_dag("sleep_duration", "exercise"), workout_and_sleep)
    assert not [item for item in grounded.occurrences if item.variable == "hrv"]
    row = next(row for row in grounded.rows if row.variable == "hrv")
    assert row.status == "absent"
    assert row.note


def test_an_unmeasured_variable_is_kept_as_a_row_but_never_placed(workout_and_sleep):
    grounded = ground(build_dag("sleep_duration", "exercise"), workout_and_sleep)
    row = next(row for row in grounded.rows if row.variable == "work_schedule")
    assert row.status == "unmeasured"
    assert not [item for item in grounded.occurrences if item.variable == "work_schedule"]


def test_a_once_daily_series_value_becomes_a_reading():
    """Readiness and HRV arrive as a one-point series, not an event."""
    day_start, _ = _day()
    series = TimelineSeries(
        id="series_readiness",
        phenotype="readiness",
        label="Readiness",
        unit="0-100",
        source="test",
        points=[SeriesPoint(timestamp=day_start + timedelta(hours=9), value=92.0)],
    )
    timeline = _timeline(_lane("readiness", series=[series]))
    grounded = ground(build_dag("readiness"), timeline)
    readings = [item for item in grounded.occurrences if item.variable == "readiness"]
    assert len(readings) == 1
    assert readings[0].kind == "reading"
    assert readings[0].start.hour == 9


def test_a_densely_sampled_signal_does_not_become_nodes():
    """Picking a moment out of a continuous trace would invent salience."""
    day_start, _ = _day()
    series = TimelineSeries(
        id="series_skin_temperature",
        phenotype="temperature",
        label="Skin temperature",
        unit="F",
        source="test",
        points=[
            SeriesPoint(timestamp=day_start + timedelta(minutes=index * 10), value=91.0)
            for index in range(60)
        ],
    )
    timeline = _timeline(_lane("temperature", series=[series]))
    grounded = ground(build_dag("skin_temperature", "exercise"), timeline)
    assert not [item for item in grounded.occurrences if item.variable == "skin_temperature"]
    row = next(row for row in grounded.rows if row.variable == "skin_temperature")
    assert row.status == "continuous"
    assert row.band_start and row.band_end  # it was active; it just cannot carry an arrow


def test_a_derived_value_is_not_read_off_a_raw_trace():
    """A dense heart-rate trace is not a resting heart rate, and must not stand in."""
    day_start, _ = _day()
    series = TimelineSeries(
        id="series_heart_rate",
        phenotype="heart_rate",
        label="Heart rate",
        unit="bpm",
        source="test",
        points=[
            SeriesPoint(timestamp=day_start + timedelta(minutes=index * 10), value=60.0)
            for index in range(60)
        ],
    )
    timeline = _timeline(_lane("heart_rate", series=[series]))
    grounded = ground(build_dag("readiness"), timeline)
    assert not [item for item in grounded.occurrences if item.variable == "resting_heart_rate"]


# --------------------------------------------------------------------------
# Time ordering
# --------------------------------------------------------------------------


def test_an_effect_is_never_linked_to_a_cause_that_came_after_it(workout_and_sleep):
    grounded = ground(build_dag("sleep_duration", "exercise"), workout_and_sleep)
    by_id = {item.id: item for item in grounded.occurrences}
    for link in grounded.links:
        assert by_id[link.target].start >= by_id[link.source].start, (
            f"{link.source_variable} -> {link.target_variable} points backwards in time"
        )


def test_the_effect_chosen_is_the_first_one_that_follows(workout_and_sleep):
    """With sleep both before and after the workout, only the later one links."""
    grounded = ground(build_dag("sleep_duration", "exercise"), workout_and_sleep)
    links = [link for link in grounded.links if link.source_variable == "exercise"]
    assert len(links) == 1
    target = next(item for item in grounded.occurrences if item.id == links[0].target)
    assert target.start.hour == 22


def test_a_long_gap_is_reported_as_delayed_and_a_short_one_as_immediate(workout_and_sleep):
    grounded = ground(build_dag("sleep_duration", "exercise"), workout_and_sleep)
    link = next(link for link in grounded.links if link.source_variable == "exercise")
    assert link.kind == "delayed"
    assert link.lag_minutes > IMMEDIATE_MAX_MINUTES
    # 08:00 workout end to 22:00 sleep onset.
    assert link.lag_minutes == pytest.approx(14 * 60, abs=1)


def test_an_effect_beginning_during_its_cause_has_no_negative_lag():
    """Resting heart rate is measured inside the sleep it summarises."""
    timeline = _timeline(
        _lane("sleep", [_event("s1", "sleep", "main_sleep", 0.0, 300, 300, "min")]),
        _lane("heart_rate", [_event("h1", "heart_rate", "resting", 2.5, None, 52.0, "bpm")]),
    )
    grounded = ground(build_dag("resting_heart_rate", "sleep_duration"), timeline)
    link = next(
        link
        for link in grounded.links
        if link.source_variable == "sleep_duration"
        and link.target_variable == "resting_heart_rate"
    )
    assert link.lag_minutes == 0
    assert link.kind == "immediate"


# --------------------------------------------------------------------------
# What cannot be drawn is reported, not dropped
# --------------------------------------------------------------------------


def test_an_edge_from_an_unmeasured_variable_is_reported_with_a_reason(workout_and_sleep):
    grounded = ground(build_dag("sleep_duration", "exercise"), workout_and_sleep)
    unplaced = {(item["source"], item["target"]): item for item in grounded.unplaced}
    assert ("work_schedule", "exercise") in unplaced
    assert "not measured" in unplaced[("work_schedule", "exercise")]["reason"]


def test_an_edge_whose_effect_never_followed_is_reported(workout_and_sleep):
    """Silence would read as evidence that the link is absent."""
    timeline = _timeline(
        _lane("activity", [_event("w1", "activity", "running", 22.0, 30, 900, "steps")]),
        _lane("sleep", [_event("s0", "sleep", "main_sleep", 1.0, 300, 300, "min")]),
    )
    grounded = ground(build_dag("sleep_duration", "exercise"), timeline)
    assert not [link for link in grounded.links if link.source_variable == "exercise"]
    reason = next(
        item["reason"]
        for item in grounded.unplaced
        if item["source"] == "exercise" and item["target"] == "sleep_duration"
    )
    assert "only recorded before" in reason


def test_every_unplaced_edge_names_both_variables_in_words(workout_and_sleep):
    grounded = ground(build_dag("sleep_duration", "exercise"), workout_and_sleep)
    for item in grounded.unplaced:
        assert item["sourceLabel"] and item["targetLabel"]
        assert item["reason"].strip()


# --------------------------------------------------------------------------
# Whole-day states
# --------------------------------------------------------------------------


def test_a_state_that_held_all_day_becomes_a_band_not_a_moment():
    timeline = _timeline(
        _lane(
            "location",
            [_event("p1", "location", "place", 0.0, 1440, "Needham, MA")],
        ),
        _lane("presence", [_event("a1", "presence", "presence_away", 0.0, 1440, "not_home")]),
    )
    grounded = ground(build_dag("step_count", "time_away"), timeline)
    away = [item for item in grounded.occurrences if item.variable == "time_away"]
    assert away and all(item.kind == "span" for item in away)
    assert all(not item.placeable for item in away)


def test_no_arrow_attaches_to_a_whole_day_state():
    timeline = _timeline(
        _lane("location", [_event("p1", "location", "place", 0.0, 1440, "Needham, MA")]),
        _lane("presence", [_event("a1", "presence", "presence_away", 0.0, 1440, "not_home")]),
    )
    grounded = ground(build_dag("step_count", "time_away"), timeline)
    assert not [link for link in grounded.links if link.source_variable == "time_away"]
    reason = next(
        item["reason"] for item in grounded.unplaced if item["source"] == "time_away"
    )
    assert "held all day" in reason


def test_the_day_of_the_week_is_known_for_every_hour(workout_and_sleep):
    grounded = ground(build_dag("sleep_duration", "exercise"), workout_and_sleep)
    constant = next(item for item in grounded.occurrences if item.variable == "day_of_week")
    assert constant.kind == "constant"
    assert constant.label == "Monday"
    assert constant.start == grounded.day_start
    assert constant.end == grounded.day_end


# --------------------------------------------------------------------------
# Captions describe, they never interpret
# --------------------------------------------------------------------------


def test_a_caption_does_not_repeat_the_duration_as_a_value(workout_and_sleep):
    grounded = ground(build_dag("sleep_duration"), workout_and_sleep)
    sleep = next(item for item in grounded.occurrences if item.variable == "sleep_duration")
    # The value *is* the duration; saying "300 min · 5 h" twice helps nobody.
    assert sleep.detail == "5 h"


def test_a_ratio_stored_as_a_fraction_is_captioned_as_a_percentage(monkeypatch):
    """A metric-backed grounding reads 0.912 as 91.2%, not as 0.9.

    No variable is grounded on a metadata metric at the moment — sleep
    efficiency was the last one, and it left with the stage data when the sleep
    row became a duration row. The machinery is still how any future ratio
    would be captioned, so the grounding is installed here rather than the test
    deleted along with the only thing that happened to use it.
    """
    monkeypatch.setitem(
        grounding.GROUNDINGS,
        "sleep_efficiency",
        (grounding.Grounding(lane="sleep", categories=("main_sleep",), metric="efficiency"),),
    )
    # Unmeasured variables are never placed, so it has to be measured again
    # for the duration of the test as well as grounded.
    monkeypatch.setitem(
        knowledge.VARIABLES,
        "sleep_efficiency",
        replace(knowledge.VARIABLES["sleep_efficiency"], measured=True, lane="sleep"),
    )
    timeline = _timeline(
        _lane(
            "sleep",
            [
                _event(
                    "s1",
                    "sleep",
                    "main_sleep",
                    0.0,
                    300,
                    300,
                    "min",
                    metadata={"efficiency": 0.912, "durationMinutes": 300},
                )
            ],
        )
    )
    grounded = ground(build_dag("sleep_duration", "sleep_efficiency"), timeline)
    efficiency = next(
        item for item in grounded.occurrences if item.variable == "sleep_efficiency"
    )
    assert "91.2%" in efficiency.detail


def test_no_caption_reads_as_a_judgement(workout_and_sleep):
    grounded = ground(build_dag("sleep_duration", "exercise"), workout_and_sleep)
    for item in grounded.occurrences:
        lowered = f"{item.label} {item.detail}".lower()
        for banned in ("good", "poor", "great", "bad", "improved", "should"):
            assert banned not in lowered


# --------------------------------------------------------------------------
# The payload as the frontend receives it
# --------------------------------------------------------------------------


def test_the_endpoint_returns_a_grounded_timeline(client, seeded_day):
    body = client.post("/api/dag", json={"outcome": "sleep_duration"}).json()
    assert body["estimated"] is False
    assert body["timeline"] is not None
    assert body["timeline"]["localTimezone"]
    assert body["timeline"]["dayStart"] < body["timeline"]["dayEnd"]
    for occurrence in body["timeline"]["occurrences"]:
        assert occurrence["start"]
        assert occurrence["variable"]


def test_a_grounded_link_still_reports_no_effect_size(client, seeded_day):
    body = client.post("/api/dag", json={"outcome": "sleep_duration"}).json()
    serialized = str(body["timeline"]).lower()
    for banned in ("p_value", "p-value", "effect_size", "coefficient", "significant"):
        assert banned not in serialized
