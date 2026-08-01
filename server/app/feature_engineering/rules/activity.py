"""Workout / activity sessions.

Rule: prefer explicit wearable workout records. Elevated heart rate alone is
never sufficient evidence for a workout — `allow_heart_rate_only_inference`
exists so that behaviour is a deliberate, recorded configuration choice rather
than a hidden default.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ...models.raw import NormalizedSample
from ...models.timeline import Lane, SeriesPoint, TimelineEvent, TimelineSeries
from ..context import RuleContext, sort_events
from ..provenance import build_provenance, detect_gaps

RULE_ID = "activity.workout_session"
RULE_STEPS = "activity.step_rate"
RULE_WALKING = "activity.sustained_walking"

LANE = {
    "id": "activity",
    "phenotype": "activity",
    "label": "Activity",
    "description": "Exercise and movement",
    "accent": "green",
}

ACTIVITY_LABELS = {
    "strength_training": "Strength training",
    "running": "Run",
    "walk": "Walk",
    "cycling": "Ride",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)
    sources: list[str] = []

    events, workout_reason = _workout_events(context)
    if events:
        sources.append(context.wearable.source_id)

    # A step counter is a second, independent source of movement evidence.
    step_series, step_events, step_source = _step_activity(context)

    # `prefer_wearable_records` also means not reporting the same walk twice:
    # a step-derived period that overlaps a recorded session adds no
    # information, and two nodes on the same minute only make the lane harder
    # to read. The step-rate line still shows the movement.
    if context.config.workout_session.prefer_wearable_records:
        step_events = [
            step
            for step in step_events
            if not any(
                step.start_time < (workout.end_time or workout.start_time)
                and (step.end_time or step.start_time) > workout.start_time
                for workout in events
            )
        ]

    events.extend(step_events)
    if step_source and step_source not in sources:
        sources.append(step_source)

    lane.events = sort_events(events)
    lane.series = [step_series] if step_series else []
    lane.available = bool(lane.events or lane.series)
    lane.sources = sources
    lane.units = ["min"] + (["steps/min"] if step_series else [])
    if not lane.available:
        lane.unavailable_reason = workout_reason
    return lane


def _step_activity(
    context: RuleContext,
) -> tuple[TimelineSeries | None, list[TimelineEvent], str | None]:
    """Turn a cumulative step counter into a step-rate series plus walking periods.

    A counter tells you totals, not when you moved. The rate between consecutive
    readings does, so that is what gets drawn — and each bucket records the two
    counter readings it came from.
    """
    rule = context.config.step_activity
    samples = sorted(
        (
            sample
            for sample in context.normalized.samples_for("steps")
            if context.window.contains(sample.timestamp)
        ),
        key=lambda sample: sample.timestamp,
    )
    if len(samples) < 3:
        return None, [], None

    entity_id = samples[0].entity_id
    source = samples[0].source
    points: list[SeriesPoint] = []
    increments: list[tuple[datetime, datetime, float, float, NormalizedSample, NormalizedSample]] = []

    for previous, current in zip(samples, samples[1:]):
        minutes = (current.timestamp - previous.timestamp).total_seconds() / 60
        if minutes <= 0:
            continue
        if current.quality == 0.5 or current.value < previous.value:
            # The counter reset here; the increment across the boundary is unknown.
            continue
        delta = current.value - previous.value
        rate = delta / minutes
        points.append(SeriesPoint(timestamp=current.timestamp, value=round(rate, 2), quality=1.0))
        increments.append((previous.timestamp, current.timestamp, delta, rate, previous, current))

    if not points:
        return None, [], None

    total_steps = max(sample.value for sample in samples)
    series = TimelineSeries(
        id="series_step_rate",
        phenotype="activity",
        label="Step rate",
        unit="steps/min",
        source=source,
        device=samples[0].device,
        entity_id=entity_id,
        measured_or_derived="derived",
        points=points,
        # A counter that stops reporting hides *when* the steps happened, so a
        # long silence is drawn as a gap rather than a smooth line.
        gaps=detect_gaps(
            samples,
            context.window.start,
            context.window.end,
            context.stale_gap,
            reason="The step counter did not report for longer than the staleness limit.",
        ),
        min_value=0,
        metadata={
            "totalStepsForDay": int(total_steps),
            "counterReadings": len(samples),
            "note": (
                "The step sensor is a cumulative daily counter. This line is the rate "
                "between consecutive readings, so it shows when movement happened "
                "rather than the running total."
            ),
        },
        provenance=build_provenance(
            rule=RULE_STEPS,
            version=rule.rule_version,
            raw_record_ids=[sample.raw_record_id for sample in samples],
            entity_ids=[entity_id] if entity_id else [],
            thresholds={"bucket_minutes": rule.bucket_minutes},
            input_range=(samples[0].timestamp, samples[-1].timestamp),
            assumptions=[
                "A decrease in the counter is treated as a midnight reset, and the "
                "increment across that boundary is not estimated."
            ],
        ),
    )

    events = _walking_periods(context, increments, entity_id, source)
    return series, events, source


def _walking_periods(
    context: RuleContext,
    increments: list,
    entity_id: str | None,
    source: str,
) -> list[TimelineEvent]:
    """Contiguous stretches where the step rate stayed at a walking pace."""
    rule = context.config.step_activity
    minimum = timedelta(minutes=rule.min_active_minutes)

    runs: list[list] = []
    current: list = []
    for item in increments:
        if item[3] >= rule.active_steps_per_minute:
            current.append(item)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)

    events: list[TimelineEvent] = []
    for index, run in enumerate(runs):
        start = run[0][0]
        end = run[-1][1]
        if end - start < minimum:
            continue
        steps = sum(item[2] for item in run)
        minutes = (end - start).total_seconds() / 60
        events.append(
            TimelineEvent(
                id=f"activity_walking_{index}_{int(start.timestamp())}",
                phenotype="activity",
                label="Sustained walking period",
                event_type="interval",
                start_time=start,
                end_time=end,
                value=int(steps),
                unit="steps",
                source=source,
                entity_id=entity_id,
                measured_or_derived="derived",
                confidence=0.65,
                data_quality="medium",
                category="walking_period",
                metadata={
                    "steps": int(steps),
                    "durationMinutes": round(minutes, 1),
                    "meanStepsPerMinute": round(steps / minutes, 1) if minutes else None,
                    "note": (
                        "Derived from a step counter, not from a workout record. The "
                        "activity type is unknown — only that steps accumulated at a "
                        "walking pace."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_WALKING,
                    version=rule.rule_version,
                    raw_record_ids=[item[5].raw_record_id for item in run],
                    entity_ids=[entity_id] if entity_id else [],
                    thresholds={
                        "active_steps_per_minute": rule.active_steps_per_minute,
                        "min_active_minutes": rule.min_active_minutes,
                    },
                    input_range=(start, end),
                    notes=[
                        "Step cadence is not sufficient evidence to name an exercise "
                        "type; none is claimed."
                    ],
                ),
            )
        )
    return events


def _workout_events(context: RuleContext) -> tuple[list[TimelineEvent], str]:
    rule = context.config.workout_session
    events: list[TimelineEvent] = []
    payload = context.wearable

    if not payload.supports("activity"):
        return events, (
            "The configured wearable provider does not expose activity records, and no "
            "step counter is mapped in config.yaml."
        )

    minimum = timedelta(minutes=rule.min_duration_minutes)

    for record in payload.activity:
        duration = record.end - record.start
        if duration < minimum:
            continue
        clipped = context.clip_to_day(record.start, record.end)
        if clipped is None:
            continue
        start, end, before, after = clipped

        events.append(
            TimelineEvent(
                id=f"activity_{record.id}",
                phenotype="activity",
                label=record.label or ACTIVITY_LABELS.get(record.activity_type, "Activity"),
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round(duration.total_seconds() / 60, 1),
                unit="min",
                source=payload.source_id,
                device=record.device or payload.device,
                measured_or_derived="measured" if record.detection == "workout_record" else "derived",
                confidence=0.98 if record.detection == "workout_record" else 0.6,
                data_quality="high" if record.detection == "workout_record" else "medium",
                category=record.activity_type,
                continues_before=before,
                continues_after=after,
                metadata={
                    "activityType": record.activity_type,
                    "detection": record.detection,
                    "fullStart": record.start.isoformat(),
                    "fullEnd": record.end.isoformat(),
                    "durationMinutes": round(duration.total_seconds() / 60, 1),
                    "steps": record.steps,
                    "distanceMeters": record.distance_meters,
                    "averageHeartRate": record.average_heart_rate,
                    "maxHeartRate": record.max_heart_rate,
                    "activeCalories": record.active_calories,
                    **record.metadata,
                },
                provenance=build_provenance(
                    rule=RULE_ID,
                    version=rule.rule_version,
                    raw_record_ids=[
                        raw.id
                        for raw in payload.raw_records
                        if raw.stream == "activity"
                        and raw.attributes.get("id") == record.id
                    ],
                    thresholds={
                        "prefer_wearable_records": rule.prefer_wearable_records,
                        "allow_heart_rate_only_inference": rule.allow_heart_rate_only_inference,
                        "min_duration_minutes": rule.min_duration_minutes,
                    },
                    input_range=(record.start, record.end),
                    notes=[
                        "Taken directly from the provider's workout record; no inference applied."
                        if record.detection == "workout_record"
                        else f"Detected by the provider using '{record.detection}'."
                    ],
                ),
            )
        )

    if not events:
        return events, "No activity sessions were recorded on this day."
    return events, ""
