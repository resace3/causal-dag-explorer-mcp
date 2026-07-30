"""Build a custom row from a resolved spec and an already-processed day.

Custom rows are derived at read time from the stored timeline rather than by
re-running the feature pipeline. That keeps them cheap, lets them appear on
every day already in the cache, and means a row definition can never corrupt the
underlying reconstruction — the worst a bad definition can do is produce an empty
row that says why.

Everything produced here carries provenance naming the rule, the threshold and
the series it came from, exactly like the built-in rules. A row someone invented
in a text box is still a derived feature, and has to be as inspectable as one
that ships with the app.
"""

from __future__ import annotations

from datetime import datetime

from ..models.timeline import DayTimeline, Lane, Provenance, TimelineEvent, TimelineSeries
from .interpret import LaneSpec

RULE_ID = "custom_lane.threshold"
RULE_VERSION = "1.0.0"

#: A run shorter than this is noise from a single stray sample.
MIN_INTERVAL_SECONDS = 60.0


def _source_lane(timeline: DayTimeline, lane_id: str) -> Lane | None:
    for lane in timeline.lanes:
        if lane.id == lane_id:
            return lane
    return None


def _holds(value: float, comparator: str, threshold: float) -> bool:
    return value > threshold if comparator == "above" else value < threshold


def _intervals(
    spec: LaneSpec, series: TimelineSeries, lane_id: str
) -> list[TimelineEvent]:
    """Contiguous runs where the condition holds."""
    assert spec.comparator and spec.threshold is not None
    events: list[TimelineEvent] = []
    run_start: datetime | None = None
    run_points: list[float] = []
    # A series point carries no record id of its own, so provenance points at
    # the records behind the whole series rather than inventing per-sample ones.
    origin = list(series.provenance.raw_record_ids) if series.provenance else []

    def close(end: datetime) -> None:
        nonlocal run_start, run_points
        if run_start is None or not run_points:
            run_start, run_points = None, []
            return
        if (end - run_start).total_seconds() < MIN_INTERVAL_SECONDS:
            # One sample over the line is not a period; dropping it keeps the
            # row readable without hiding anything a person would call an event.
            run_start, run_points = None, []
            return
        peak = max(run_points) if spec.comparator == "above" else min(run_points)
        events.append(
            TimelineEvent(
                id=f"custom_{lane_id}_{run_start.isoformat()}",
                phenotype=lane_id,
                label=spec.label,
                event_type="interval",
                start_time=run_start,
                end_time=end,
                value=round(peak, 2),
                unit=series.unit,
                source=series.source,
                device=series.device,
                entity_id=series.entity_id,
                measured_or_derived="derived",
                data_quality="high",
                category="custom_threshold",
                metadata={
                    "durationMinutes": round((end - run_start).total_seconds() / 60, 1),
                    "sampleCount": len(run_points),
                    "meanValue": round(sum(run_points) / len(run_points), 2),
                    "peakValue": round(peak, 2),
                    "note": (
                        f"Derived from {series.label} by this row's own rule: "
                        f"{spec.comparator} {spec.threshold:g}"
                        f"{f' {series.unit}' if series.unit else ''}."
                    ),
                },
                provenance=Provenance(
                    raw_record_ids=origin,
                    source_entity_ids=[series.entity_id] if series.entity_id else [],
                    transformation_rule=RULE_ID,
                    rule_version=RULE_VERSION,
                    thresholds={
                        "comparator": spec.comparator,
                        "threshold": spec.threshold,
                        "min_interval_seconds": MIN_INTERVAL_SECONDS,
                    },
                    notes=[f"Row defined by the request: “{spec.prompt}”."],
                ),
            )
        )
        run_start, run_points = None, []

    previous: datetime | None = None
    for point in series.points:
        if _holds(point.value, spec.comparator, spec.threshold):
            if run_start is None:
                run_start = point.timestamp
                run_points = []
            run_points.append(point.value)
        elif run_start is not None:
            close(previous or point.timestamp)
        previous = point.timestamp

    if run_start is not None and previous is not None:
        close(previous)
    return events


def build(spec: LaneSpec, lane_id: str, timeline: DayTimeline) -> Lane:
    """Render `spec` against `timeline`, or explain why it produced nothing."""
    source = _source_lane(timeline, spec.lane_id)
    base = Lane(
        id=lane_id,
        phenotype=lane_id,
        label=spec.label,
        description=spec.prompt or "Custom row",
        accent=spec.accent,
        available=False,
        unavailable_reason=None,
        sources=list(source.sources) if source else [],
    )

    if source is None or not source.available:
        base.unavailable_reason = (
            f"This row reads from {spec.lane_id.replace('_', ' ')}, which has no data "
            "on this day."
        )
        return base

    if spec.mode == "events":
        base.events = [event.model_copy(deep=True) for event in source.events]
        base.units = list(source.units)
        base.available = bool(base.events)
        if not base.available:
            base.unavailable_reason = f"{source.label} recorded no events on this day."
        return base

    series = next((item for item in source.series if item.id == spec.series_id), None)
    if series is None:
        base.unavailable_reason = (
            f"The {spec.series_id or 'source'} series is not present on this day."
        )
        return base

    if spec.mode == "series":
        copy = series.model_copy(deep=True)
        copy.id = f"{lane_id}_series"
        base.series = [copy]
        base.units = [series.unit] if series.unit else []
        base.available = bool(copy.points)
        if not base.available:
            base.unavailable_reason = f"{series.label} has no samples on this day."
        return base

    base.events = _intervals(spec, series, lane_id)
    base.units = [series.unit] if series.unit else []
    base.available = True
    if not base.events:
        # An empty result is a real answer to "when was I above 100?" — the row
        # stays, saying the condition was never met, rather than vanishing.
        base.available = False
        unit = f" {series.unit}" if series.unit else ""
        base.unavailable_reason = (
            f"{series.label} was never {spec.comparator} {spec.threshold:g}{unit} "
            "on this day."
        )
    return base
