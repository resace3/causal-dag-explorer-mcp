"""Rows described in words.

The reader is local and rule-based, which makes one failure mode the thing
worth testing hardest: matching something *near* what was asked for. A request
for heart rate variability that quietly becomes heart rate would produce a row
full of the wrong data and no sign anything went wrong.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.custom_lanes.build import build
from app.custom_lanes.interpret import LaneSpec, interpret
from app.main import create_app
from app.models.timeline import (
    DayCoverage,
    DayTimeline,
    Lane,
    SeriesPoint,
    SyncSummary,
    TimelineEvent,
    TimelineSeries,
)

DAY_START = "2026-07-29T00:00:00-04:00"
DAY_END = "2026-07-30T00:00:00-04:00"


def _series(points: list[tuple[str, float]]) -> TimelineSeries:
    return TimelineSeries(
        id="series_heart_rate",
        phenotype="heart_rate",
        label="Heart rate",
        unit="bpm",
        source="wearable:test",
        points=[SeriesPoint(timestamp=stamp, value=value) for stamp, value in points],
    )


def _timeline(*, with_hrv: bool = False) -> DayTimeline:
    lanes = [
        Lane(
            id="heart_rate",
            phenotype="heart_rate",
            label="Heart Rate",
            description="Wearable cardiovascular signal",
            accent="blue",
            available=True,
            series=[
                _series(
                    [
                        ("2026-07-29T01:00:00-04:00", 48.0),
                        ("2026-07-29T01:10:00-04:00", 47.0),
                        ("2026-07-29T01:20:00-04:00", 62.0),
                        ("2026-07-29T12:00:00-04:00", 130.0),
                        ("2026-07-29T12:20:00-04:00", 140.0),
                        ("2026-07-29T12:40:00-04:00", 80.0),
                    ]
                )
            ],
        ),
        Lane(
            id="sleep",
            phenotype="sleep",
            label="Sleep",
            description="Sleep periods and stages",
            accent="orange",
            available=True,
            events=[
                TimelineEvent(
                    id="sleep_1",
                    phenotype="sleep",
                    label="Main sleep",
                    event_type="interval",
                    start_time="2026-07-29T00:00:00-04:00",
                    end_time="2026-07-29T06:00:00-04:00",
                    source="wearable:test",
                    measured_or_derived="measured",
                    category="main_sleep",
                )
            ],
        ),
        Lane(
            id="hrv",
            phenotype="hrv",
            label="Heart Rate Variability",
            description="Nightly beat-to-beat variation",
            accent="indigo",
            available=with_hrv,
            unavailable_reason=None if with_hrv else "No HRV data was available.",
            series=(
                [
                    TimelineSeries(
                        id="series_hrv",
                        phenotype="hrv",
                        label="HRV",
                        unit="ms",
                        source="wearable:test",
                        points=[
                            SeriesPoint(timestamp="2026-07-29T03:00:00-04:00", value=38.0)
                        ],
                    )
                ]
                if with_hrv
                else []
            ),
        ),
    ]
    return DayTimeline(
        date="2026-07-29",
        local_timezone="America/New_York",
        day_start=DAY_START,
        day_end=DAY_END,
        day_length_hours=24.0,
        generated_at="2026-07-30T01:00:00-04:00",
        lanes=lanes,
        summary=SyncSummary(
            date_processed="2026-07-29",
            local_timezone="America/New_York",
            day_start=DAY_START,
            day_end=DAY_END,
            day_length_hours=24.0,
            coverage=DayCoverage(),
        ),
    )


@pytest.fixture
def client(repository, sync_service):
    app = create_app()
    routes.configure(repository, sync_service)
    with TestClient(app) as test_client:
        routes.configure(repository, sync_service)
        yield test_client


# --------------------------------------------------------------------------
# Reading the request
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt,comparator,threshold",
    [
        ("heart rate above 100", "above", 100.0),
        ("heart rate over 100", "above", 100.0),
        ("hr greater than 100", "above", 100.0),
        ("pulse > 100", "above", 100.0),
        ("heart rate below 50", "below", 50.0),
        ("heart rate under 50", "below", 50.0),
        ("hr less than 50", "below", 50.0),
        ("heart rate above 62.5", "above", 62.5),
    ],
)
def test_thresholds_are_read_in_the_ways_people_write_them(prompt, comparator, threshold):
    reading = interpret(prompt, _timeline())
    assert reading.understood, reading.problem
    assert reading.spec.comparator == comparator
    assert reading.spec.threshold == threshold
    assert reading.spec.series_id == "series_heart_rate"


def test_a_stream_named_alone_is_plotted_as_recorded():
    reading = interpret("heart rate", _timeline())
    assert reading.understood
    assert reading.spec.mode == "series"
    assert reading.summary == "Heart rate, as recorded"


def test_a_lane_without_a_series_gives_its_events():
    reading = interpret("sleep", _timeline())
    assert reading.understood
    assert reading.spec.mode == "events"
    assert reading.spec.lane_id == "sleep"


def test_the_longest_stream_name_wins_over_a_substring_of_it():
    """"Heart rate variability" must never quietly resolve to "heart rate"."""
    reading = interpret("heart rate variability above 40", _timeline(with_hrv=True))
    assert reading.understood
    assert reading.spec.lane_id == "hrv"


def test_a_stream_with_no_data_today_is_named_rather_than_substituted():
    # The dangerous failure: hrv is absent, "heart rate" is a substring of the
    # request, and matching it would build a plausible-looking wrong row.
    reading = interpret("heart rate variability", _timeline(with_hrv=False))
    assert not reading.understood
    assert "Heart Rate Variability" in reading.problem
    assert "no data" in reading.problem


def test_an_unknown_stream_is_refused_and_the_real_ones_listed():
    reading = interpret("blood glucose above 7", _timeline())
    assert not reading.understood
    assert "Heart rate" in reading.known
    assert "Sleep" in reading.known


def test_a_threshold_with_no_stream_is_refused():
    reading = interpret("above 100", _timeline())
    assert not reading.understood


def test_an_empty_request_is_refused():
    assert not interpret("   ", _timeline()).understood


def test_an_unprocessed_day_cannot_define_a_row():
    reading = interpret("heart rate above 100", None)
    assert not reading.understood
    assert "not been reconstructed" in reading.problem


# --------------------------------------------------------------------------
# Building the row
# --------------------------------------------------------------------------


def test_a_threshold_row_finds_the_runs_where_it_held():
    timeline = _timeline()
    spec = interpret("heart rate above 100", timeline).spec
    lane = build(spec, "custom_hr", timeline)

    assert lane.available
    assert len(lane.events) == 1
    event = lane.events[0]
    assert event.start_time.hour == 12
    assert event.value == 140.0
    assert event.measured_or_derived == "derived"


def test_a_built_row_carries_provenance_like_any_other_derived_feature():
    timeline = _timeline()
    spec = interpret("heart rate above 100", timeline).spec
    event = build(spec, "custom_hr", timeline).events[0]

    assert event.provenance is not None
    assert event.provenance.transformation_rule == "custom_lane.threshold"
    assert event.provenance.thresholds["threshold"] == 100.0
    assert event.provenance.thresholds["comparator"] == "above"
    assert any("heart rate above 100" in note for note in event.provenance.notes)


def test_a_row_whose_condition_never_held_says_so_instead_of_vanishing():
    timeline = _timeline()
    spec = interpret("heart rate above 200", timeline).spec
    lane = build(spec, "custom_hr", timeline)

    assert not lane.available
    assert "never above 200 bpm" in lane.unavailable_reason


def test_a_single_sample_over_the_line_is_not_an_interval():
    timeline = _timeline()
    # 130 at 12:00 then 140 at 12:20 is a run; a lone crossing is not.
    spec = interpret("heart rate above 135", timeline).spec
    lane = build(spec, "custom_hr", timeline)
    assert lane.events == []


def test_a_row_reading_from_a_lane_with_no_data_explains_itself():
    timeline = _timeline(with_hrv=False)
    spec = LaneSpec(label="HRV", prompt="hrv", lane_id="hrv")
    lane = build(spec, "custom_hrv", timeline)
    assert not lane.available
    assert "no data on this day" in lane.unavailable_reason


def test_a_plain_series_row_copies_the_samples():
    timeline = _timeline()
    spec = interpret("heart rate", timeline).spec
    lane = build(spec, "custom_hr", timeline)
    assert lane.available
    assert len(lane.series) == 1
    assert len(lane.series[0].points) == 6


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


@pytest.fixture
def synced(client):
    """A processed day, which a row definition is resolved against."""
    client.get("/api/yesterday")
    return client


def test_the_preview_does_not_create_anything(client):
    response = client.post("/api/rows/interpret", json={"prompt": "heart rate above 100"})
    assert response.status_code == 200
    assert client.get("/api/rows").json()["rows"] == []


def test_a_row_can_be_added_listed_and_removed(synced):
    created = synced.post("/api/rows", json={"prompt": "heart rate above 100"})
    assert created.status_code == 200, created.json()
    row_id = created.json()["id"]

    listed = synced.get("/api/rows").json()["rows"]
    assert [row["id"] for row in listed] == [row_id]
    assert listed[0]["prompt"] == "heart rate above 100"

    assert synced.delete(f"/api/rows/{row_id}").status_code == 200
    assert synced.get("/api/rows").json()["rows"] == []


def test_an_unreadable_request_is_refused_with_a_reason(synced):
    response = synced.post("/api/rows", json={"prompt": "blood glucose above 7"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unreadable_row_request"


def test_removing_a_row_that_does_not_exist_is_a_404(client):
    assert client.delete("/api/rows/custom_nothing").status_code == 404


def test_two_rows_with_the_same_description_get_distinct_ids(synced):
    first = synced.post("/api/rows", json={"prompt": "heart rate above 100"}).json()["id"]
    second = synced.post("/api/rows", json={"prompt": "hr over 100"}).json()["id"]
    assert first != second


def test_an_added_row_appears_on_the_day_timeline(synced):
    synced.post("/api/rows", json={"prompt": "heart rate above 100"})
    body = synced.get("/api/yesterday").json()
    custom = [lane for lane in body["lanes"] if lane["id"].startswith("custom_")]
    assert len(custom) == 1
    assert custom[0]["label"] == "Heart rate above 100 bpm"
