"""Feature-engineering rules: outputs, provenance, and honest missing data."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.config.schema import LightBand, LightCategoryRule
from app.connectors.wearables.mock import MockWearableProvider


@pytest.fixture
async def timeline(sync_service, fixed_now):
    return await sync_service.sync(force_refresh=True, now=fixed_now)


def _lane(timeline, lane_id):
    return next(lane for lane in timeline.lanes if lane.id == lane_id)


async def test_every_lane_is_present_and_ordered(timeline):
    assert [lane.id for lane in timeline.lanes] == [
        "activity",
        "heart_rate",
        "hrv",
        "readiness",
        "sleep",
        "temperature",
        "environment",
        "presence",
        "location",
    ]


async def test_activity_events_come_from_wearable_records_with_provenance(timeline):
    lane = _lane(timeline, "activity")
    assert len(lane.events) == 3
    for event in lane.events:
        assert event.measured_or_derived == "measured"
        assert event.provenance is not None
        assert event.provenance.transformation_rule == "activity.workout_session"
        assert event.provenance.rule_version
        assert event.provenance.raw_record_ids
        assert (
            event.provenance.thresholds["allow_heart_rate_only_inference"] is False
        ), "a workout must never be inferred from heart rate alone by default"


async def test_sleep_crosses_midnight_in_both_directions(timeline):
    lane = _lane(timeline, "sleep")
    main = [event for event in lane.events if event.category == "main_sleep"]
    assert len(main) == 2

    overnight_in = main[0]
    assert overnight_in.continues_before is True
    assert overnight_in.start_time == timeline.day_start
    # The full, unclipped timestamps survive for the details panel.
    assert overnight_in.metadata["fullStart"] < timeline.day_start.isoformat()

    overnight_out = main[-1]
    assert overnight_out.continues_after is True
    assert overnight_out.end_time == timeline.day_end
    assert overnight_out.metadata["fullEnd"] > timeline.day_end.isoformat()


async def test_nap_is_labelled_separately_from_main_sleep(timeline):
    lane = _lane(timeline, "sleep")
    naps = [event for event in lane.events if event.category == "nap"]
    assert len(naps) == 1
    assert naps[0].label == "Nap"


async def test_heart_rate_series_breaks_across_the_charging_gap(timeline):
    lane = _lane(timeline, "heart_rate")
    series = lane.series[0]
    assert series.unit == "bpm"
    assert series.points
    assert series.gaps, "the mock includes a charging gap that must be reported"
    longest = max(series.gaps, key=lambda gap: gap.end_time - gap.start_time)
    assert (longest.end_time - longest.start_time) >= timedelta(minutes=60)


async def test_elevated_heart_rate_is_described_relative_to_a_personal_baseline(timeline):
    lane = _lane(timeline, "heart_rate")
    elevated = [event for event in lane.events if event.category == "elevated"]
    assert elevated
    event = elevated[0]
    assert event.measured_or_derived == "derived"
    assert "standard deviations" in event.metadata["interpretation"]
    assert event.provenance.thresholds["sd_threshold"] == 1.5
    # Never a psychological or clinical claim.
    for banned in ("stress", "anxiety", "panic", "abnormal"):
        assert banned not in event.label.lower()
        assert banned not in event.metadata["interpretation"].lower()


async def test_elevated_heart_rate_during_a_workout_says_exercise_associated(timeline):
    lane = _lane(timeline, "heart_rate")
    elevated = [event for event in lane.events if event.category == "elevated"]
    assert any(event.label == "Exercise-associated heart rate" for event in elevated)


async def test_hrv_is_one_nightly_value_not_an_invented_curve(timeline):
    lane = _lane(timeline, "hrv")
    assert lane.series == [], "a single nightly value must not be expanded into a series"
    assert len(lane.events) == 1
    event = lane.events[0]
    assert event.event_type == "point"
    assert event.metadata["metric"] == "RMSSD"
    assert event.metadata["coversSleepStart"]
    assert "not an hourly measurement" in event.metadata["note"]


async def test_readiness_is_marked_derived_and_not_called_energy(timeline):
    lane = _lane(timeline, "readiness")
    assert lane.label == "Physiological Readiness"
    assert "energy" not in lane.label.lower()
    assert lane.series[0].measured_or_derived == "derived"


async def test_temperature_lane_names_the_actual_measurement(timeline):
    lane = _lane(timeline, "temperature")
    assert lane.label == "Skin Temperature"
    assert lane.series[0].metadata["measurement"] == "skin_temperature"
    assert "core" not in lane.label.lower()


async def test_light_categories_carry_their_thresholds(timeline):
    lane = _lane(timeline, "environment")
    light = [event for event in lane.events if (event.category or "").startswith("light_")]
    assert light
    event = light[0]
    assert event.provenance.transformation_rule == "environment.light_category"
    assert "dark" in event.provenance.thresholds
    assert "illuminance" in event.metadata["classificationRule"].lower()
    assert "sunrise" in event.provenance.notes[0]


async def test_illuminance_outage_becomes_a_missing_data_event(timeline):
    lane = _lane(timeline, "environment")
    gaps = [event for event in lane.events if event.category == "missing_data"]
    assert gaps, "the mock illuminance sensor drops offline and that must be visible"
    assert gaps[0].label == "No illuminance data"
    assert "Nothing is assumed or interpolated" in gaps[0].metadata["note"]


async def test_presence_exposes_no_coordinates(timeline):
    lane = _lane(timeline, "presence")
    serialized = lane.model_dump_json()
    for banned in ("latitude", "longitude", "gps_accuracy", "\"lat\"", "\"lon\""):
        assert banned not in serialized
    home = next(event for event in lane.events if event.category == "presence_home")
    assert "No geographic coordinates" in home.metadata["note"]


async def test_presence_transitions_are_detected(timeline):
    lane = _lane(timeline, "presence")
    labels = {event.label for event in lane.events}
    assert "Left home" in labels
    assert "Arrived home" in labels


async def test_highlights_describe_timing_without_causal_language(timeline):
    assert timeline.highlights
    text = " ".join(timeline.highlights).lower()
    for banned in ("caused", "because", "improved", "led to", "due to", "thanks to"):
        assert banned not in text


async def test_coverage_reports_missing_periods(timeline):
    coverage = timeline.summary.coverage
    assert 0 < coverage.overall_fraction <= 1
    assert coverage.missing_periods
    assert set(coverage.per_lane) == {lane.id for lane in timeline.lanes}


async def test_light_classification_uses_configured_bands():
    rule = LightCategoryRule(
        thresholds={
            "dark": LightBand(max_lux=5),
            "dim": LightBand(min_lux=5, max_lux=50),
            "moderate": LightBand(min_lux=50, max_lux=300),
            "bright": LightBand(min_lux=300),
        }
    )
    assert rule.classify(0) == "dark"
    assert rule.classify(4.9) == "dark"
    assert rule.classify(5) == "dim"
    assert rule.classify(49.9) == "dim"
    assert rule.classify(50) == "moderate"
    assert rule.classify(299.9) == "moderate"
    assert rule.classify(300) == "bright"
    assert rule.classify(50_000) == "bright"


async def test_mock_provider_is_deterministic_for_a_fixed_seed(new_york):
    first = MockWearableProvider(new_york, seed=42)
    second = MockWearableProvider(new_york, seed=42)
    start = datetime(2025, 6, 10, tzinfo=new_york)
    end = start + timedelta(days=1)
    assert await first.get_activity(start, end) == await second.get_activity(start, end)
    assert await first.get_sleep(start, end) == await second.get_sleep(start, end)


async def test_a_different_seed_changes_the_day(new_york):
    start = datetime(2025, 6, 10, tzinfo=new_york)
    end = start + timedelta(days=1)
    a = await MockWearableProvider(new_york, seed=42).get_activity(start, end)
    b = await MockWearableProvider(new_york, seed=7).get_activity(start, end)
    assert [record.start for record in a] != [record.start for record in b]


async def test_mock_provider_declares_every_capability(new_york):
    capabilities = await MockWearableProvider(new_york, seed=42).get_capabilities()
    assert capabilities.status == "mock_data"
    assert set(capabilities.capabilities) == {
        "sleep",
        "heart_rate",
        "hrv",
        "activity",
        "temperature",
        "readiness",
    }


async def test_mock_heart_rate_has_a_charging_gap(new_york):
    provider = MockWearableProvider(new_york, seed=42)
    start = datetime(2025, 6, 10, tzinfo=new_york)
    points = await provider.get_heart_rate(start, start + timedelta(days=1))
    gap_window = [
        point
        for point in points
        if datetime(2025, 6, 10, 15, 30, tzinfo=new_york)
        <= point.timestamp
        < datetime(2025, 6, 10, 16, 0, tzinfo=new_york)
    ]
    assert gap_window == []


async def test_plans_are_stable_across_calls(new_york):
    provider = MockWearableProvider(new_york, seed=42)
    first = provider.plan_for(date(2025, 6, 10)).sleep_start
    second = provider.plan_for(date(2025, 6, 10)).sleep_start
    assert first == second
