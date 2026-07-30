"""Normalization: samples, state intervals, gaps and missing values."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.raw import RawRecord
from app.normalization.normalizer import UNAVAILABLE, normalize


def _record(stream, timestamp, value, entity_id="sensor.test", **attributes) -> RawRecord:
    return RawRecord(
        id=RawRecord.make_id("home_assistant", stream, timestamp.isoformat()),
        source="home_assistant",
        stream=stream,
        entity_id=entity_id,
        timestamp=timestamp,
        value=value,
        attributes=attributes,
    )


def test_numeric_streams_become_samples(new_york):
    start = datetime(2025, 6, 10, tzinfo=new_york)
    records = [
        _record("illuminance", start, 12.0),
        _record("illuminance", start + timedelta(minutes=10), 340.0),
    ]
    result = normalize(records, start, start + timedelta(days=1))
    assert [sample.value for sample in result.samples_for("illuminance")] == [12.0, 340.0]


def test_unavailable_samples_are_dropped_not_zeroed(new_york):
    start = datetime(2025, 6, 10, tzinfo=new_york)
    records = [
        _record("illuminance", start, 12.0),
        _record("illuminance", start + timedelta(minutes=10), None, unavailable=True),
        _record("illuminance", start + timedelta(minutes=20), 15.0),
    ]
    result = normalize(records, start, start + timedelta(days=1))
    values = [sample.value for sample in result.samples_for("illuminance")]
    assert values == [12.0, 15.0]
    assert 0.0 not in values


def test_state_streams_become_closed_intervals(new_york):
    start = datetime(2025, 6, 10, tzinfo=new_york)
    end = start + timedelta(days=1)
    records = [
        _record("presence", start, "home", entity_id="person.user"),
        _record("presence", start + timedelta(hours=9), "not_home", entity_id="person.user"),
        _record("presence", start + timedelta(hours=12), "home", entity_id="person.user"),
    ]
    states = normalize(records, start, end).states_for("presence")
    assert [state.state for state in states] == ["home", "not_home", "home"]
    assert states[0].end_time == states[1].start_time
    # The final state runs to the end of the fetch window.
    assert states[-1].end_time == end


def test_unavailable_state_is_marked_and_warned(new_york):
    start = datetime(2025, 6, 10, tzinfo=new_york)
    end = start + timedelta(days=1)
    records = [
        _record("presence", start, "home", entity_id="person.user"),
        _record(
            "presence",
            start + timedelta(hours=2),
            None,
            entity_id="person.user",
            unavailable=True,
        ),
    ]
    result = normalize(records, start, end)
    states = result.states_for("presence")
    assert states[1].state == UNAVAILABLE
    assert any("unavailable" in warning for warning in result.warnings)


def test_duplicate_timestamps_keep_the_last_value(new_york):
    start = datetime(2025, 6, 10, tzinfo=new_york)
    records = [
        _record("illuminance", start, 12.0),
        _record("illuminance", start, 18.0),
    ]
    # Ids collide by design, so build the second explicitly.
    records[1] = records[1].model_copy(update={"id": "raw_illuminance_second"})
    samples = normalize(records, start, start + timedelta(days=1)).samples_for("illuminance")
    assert len(samples) == 1
    assert samples[0].value == 18.0


def test_interval_streams_are_left_for_the_rules(new_york):
    """Sleep and activity keep their typed provider records; nothing is invented."""
    start = datetime(2025, 6, 10, tzinfo=new_york)
    records = [_record("sleep", start, "main_sleep", entity_id=None)]
    result = normalize(records, start, start + timedelta(days=1))
    assert result.samples == []
    assert result.states == []
    assert len(result.raw_for("sleep")) == 1
