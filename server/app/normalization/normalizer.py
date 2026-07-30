"""Raw records -> normalized samples and state intervals.

Normalization is deliberately boring: unit cleanup, de-duplication, ordering,
and turning Home Assistant's change-events into closed intervals. No
interpretation happens here — that is the feature-engineering layer's job.
"""

from __future__ import annotations

from datetime import datetime

from ..models.raw import (
    NormalizedRecords,
    NormalizedSample,
    NormalizedState,
    RawRecord,
)

# Streams whose value is a number on a continuous scale.
CONTINUOUS_STREAMS = {
    "illuminance",
    "room_temperature",
    "humidity",
    "heart_rate",
    "skin_temperature",
    "readiness",
    "hrv",
    "resting_heart_rate",
}

# Cumulative daily counters: they only ever increase, then reset at midnight.
COUNTER_STREAMS = {"steps"}

# Streams whose value is a categorical state that holds until the next record.
STATE_STREAMS = {
    "presence",
    "motion",
    "bed_occupancy",
    "door",
    "device_use",
    "location",
    "place",
}

UNAVAILABLE = "__unavailable__"


def _midnights_between(start: datetime, end: datetime) -> int:
    """How many local midnights a window crosses — the expected reset count."""
    return max(1, (end.date() - start.date()).days)


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def normalize(
    records: list[RawRecord],
    window_start: datetime,
    window_end: datetime,
) -> NormalizedRecords:
    """Split raw records into numeric samples and categorical state intervals."""
    normalized = NormalizedRecords(raw_records=list(records))

    by_stream_entity: dict[tuple[str, str | None], list[RawRecord]] = {}
    for record in records:
        by_stream_entity.setdefault((record.stream, record.entity_id), []).append(record)

    for (stream, entity_id), group in by_stream_entity.items():
        group.sort(key=lambda record: record.timestamp)
        group = _deduplicate(group)

        if stream in COUNTER_STREAMS:
            samples, warnings = _to_counter_samples(
                group, stream, _midnights_between(window_start, window_end)
            )
            normalized.samples.extend(samples)
            normalized.warnings.extend(warnings)
        elif stream in CONTINUOUS_STREAMS:
            normalized.samples.extend(_to_samples(group, stream))
            normalized.unavailable.extend(
                _unavailable_periods(group, stream, window_end)
            )
        elif stream in STATE_STREAMS:
            states, warnings = _to_states(group, stream, window_end)
            normalized.states.extend(states)
            normalized.warnings.extend(warnings)
        # Interval-shaped streams (sleep, activity) stay raw: the feature
        # engineering rules consume the provider's typed records directly.

    normalized.samples.sort(key=lambda sample: (sample.stream, sample.timestamp))
    normalized.states.sort(key=lambda state: (state.stream, state.start_time))
    return normalized


def _deduplicate(group: list[RawRecord]) -> list[RawRecord]:
    """Drop repeated timestamps, keeping the last value written for each."""
    deduped: list[RawRecord] = []
    for record in group:
        if deduped and deduped[-1].timestamp == record.timestamp:
            deduped[-1] = record
            continue
        deduped.append(record)
    return deduped


def _to_samples(group: list[RawRecord], stream: str) -> list[NormalizedSample]:
    samples: list[NormalizedSample] = []
    for record in group:
        if record.attributes.get("unavailable"):
            continue  # A hole, not a value. Gap detection handles it later.
        value = _to_float(record.value)
        if value is None:
            continue
        samples.append(
            NormalizedSample(
                raw_record_id=record.id,
                stream=stream,
                source=record.source,
                entity_id=record.entity_id,
                device=record.device,
                timestamp=record.timestamp,
                value=value,
                unit=record.unit,
                quality=None if record.attributes.get("estimated") else 1.0,
            )
        )
    return samples


def _unavailable_periods(
    group: list[RawRecord], stream: str, window_end: datetime
) -> list[NormalizedState]:
    """Spans where a numeric sensor said `unavailable`, held to the next value."""
    periods: list[NormalizedState] = []
    for index, record in enumerate(group):
        if not record.attributes.get("unavailable"):
            continue
        end = group[index + 1].timestamp if index + 1 < len(group) else window_end
        if end <= record.timestamp:
            continue
        periods.append(
            NormalizedState(
                raw_record_ids=[record.id],
                stream=stream,
                source=record.source,
                entity_id=record.entity_id,
                device=record.device,
                start_time=record.timestamp,
                end_time=end,
                state=UNAVAILABLE,
                attributes=dict(record.attributes),
            )
        )
    return periods


def _to_counter_samples(
    group: list[RawRecord], stream: str, expected_resets: int = 1
) -> tuple[list[NormalizedSample], list[str]]:
    """Normalize a cumulative daily counter such as a step total.

    Home Assistant's history begins with the state as it was at the start of the
    window, which for a counter is yesterday's final total. Left alone that
    produces a huge phantom drop at midnight. Each decrease is treated as a
    reset, and the sample's `quality` marks the first reading after one — the
    increment across a reset boundary is unknowable, so it is not invented.
    """
    samples: list[NormalizedSample] = []
    warnings: list[str] = []
    previous: float | None = None
    resets = 0

    for record in group:
        if record.attributes.get("unavailable"):
            previous = None
            continue
        value = _to_float(record.value)
        if value is None:
            continue

        after_reset = previous is not None and value < previous
        if after_reset:
            resets += 1
        previous = value

        samples.append(
            NormalizedSample(
                raw_record_id=record.id,
                stream=stream,
                source=record.source,
                entity_id=record.entity_id,
                device=record.device,
                timestamp=record.timestamp,
                value=value,
                unit=record.unit,
                quality=0.5 if after_reset else 1.0,
            )
        )

    if resets > expected_resets:
        entity = group[0].entity_id or stream
        warnings.append(
            f"{entity} reset {resets} times, but the window spans only {expected_resets} "
            "midnight(s). The extra resets probably mean the integration re-synced, and "
            "the affected increments are excluded rather than estimated."
        )
    return samples, warnings


def _to_states(
    group: list[RawRecord], stream: str, window_end: datetime
) -> tuple[list[NormalizedState], list[str]]:
    """Close each state at the next change, or at the end of the window."""
    states: list[NormalizedState] = []
    warnings: list[str] = []

    for index, record in enumerate(group):
        start = record.timestamp
        end = group[index + 1].timestamp if index + 1 < len(group) else window_end
        if end <= start:
            continue

        if record.attributes.get("unavailable"):
            state_value = UNAVAILABLE
        else:
            state_value = str(record.value) if record.value is not None else UNAVAILABLE

        if states and states[-1].state == state_value and states[-1].end_time == start:
            merged = states[-1]
            merged.end_time = end
            merged.raw_record_ids.append(record.id)
            continue

        states.append(
            NormalizedState(
                raw_record_ids=[record.id],
                stream=stream,
                source=record.source,
                entity_id=record.entity_id,
                device=record.device,
                start_time=start,
                end_time=end,
                state=state_value,
                attributes=dict(record.attributes),
            )
        )

    unavailable_total = sum(
        (state.end_time - state.start_time).total_seconds()
        for state in states
        if state.state == UNAVAILABLE
    )
    if unavailable_total > 0:
        entity = group[0].entity_id or stream
        warnings.append(
            f"{entity} reported unavailable for {unavailable_total / 60:.0f} minutes; "
            "that period is shown as missing rather than assumed unchanged."
        )

    return states, warnings
