"""Workout / activity sessions, and the step-rate line beneath them.

Rule: prefer explicit wearable workout records. Elevated heart rate alone is
never sufficient evidence for a workout — `allow_heart_rate_only_inference`
exists so that behaviour is a deliberate, recorded configuration choice rather
than a hidden default.

Steps arrive in one of two shapes and the difference matters enough that they
are handled by separate code paths rather than converted into one another:

* **Interval buckets** (`wearable.steps`) — "37 steps in this minute". The
  source's own shape. Absent minutes mean zero steps, not missing data.
* **A cumulative daily counter** (`entities.steps`) — a running total that
  resets at midnight. Rate has to be differenced out of it, and silence means
  the counter stopped reporting, which genuinely is missing data.

Reading one as the other is silently wrong in both directions: differencing
deltas produces noise around zero, and accumulating a counter's readings
multiplies the day. The bucket path is preferred when a provider offers it,
because differencing throws away timing the counter never had.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ...connectors.wearables.base import StepBucket
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

#: `(start, end, steps, steps_per_minute, raw_record_ids)`. Both step shapes
#: reduce to this before walking periods are looked for, so the detection reads
#: the same evidence whichever source the day came from.
Increment = tuple[datetime, datetime, float, float, list[str]]


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
    """The step-rate series and walking periods, from whichever shape is available."""
    buckets = [
        bucket
        for bucket in context.wearable.steps
        if context.window.contains(bucket.start)
    ]
    if buckets:
        return _steps_from_buckets(context, buckets)
    return _steps_from_counter(context)


# --------------------------------------------------------------------------
# Interval buckets — a provider that reports steps per minute
# --------------------------------------------------------------------------


def _steps_from_buckets(
    context: RuleContext, buckets: list[StepBucket]
) -> tuple[TimelineSeries | None, list[TimelineEvent], str | None]:
    """Aggregate per-minute step deltas into readable bins.

    Drawing a point per minute would be a picket fence rather than a line, and
    `step_activity.bucket_minutes` exists to say how coarse to make it. Absent
    minutes are summed as **zero**, not skipped: this source omits a minute it
    counted no steps in, so treating omission as missing would draw every night
    as a recording failure.
    """
    rule = context.config.step_activity
    width = timedelta(minutes=rule.bucket_minutes)
    if width <= timedelta(0):
        return None, [], None

    ordered = sorted(buckets, key=lambda bucket: bucket.start)
    payload = context.wearable
    source = payload.source_id
    device = ordered[0].device or payload.device

    # Bins are anchored to the start of the day so the same clock times line up
    # from one day to the next, and stop at the last minute actually reported —
    # past that, on a day still running, nothing is known rather than zero.
    origin = context.window.start
    last = max(bucket.end for bucket in ordered)
    bins: dict[int, list[StepBucket]] = {}
    for bucket in ordered:
        index = int((bucket.start - origin) / width)
        bins.setdefault(index, []).append(bucket)

    total_bins = int((min(last, context.window.end) - origin) / width) + 1
    points: list[SeriesPoint] = []
    increments: list[tuple[datetime, datetime, float, float, list[str]]] = []

    for index in range(max(0, total_bins)):
        bin_start = origin + width * index
        bin_end = min(bin_start + width, context.window.end)
        minutes = (bin_end - bin_start).total_seconds() / 60
        if minutes <= 0:
            continue
        members = bins.get(index, [])
        steps = sum(member.count for member in members)
        rate = steps / minutes
        points.append(
            SeriesPoint(timestamp=bin_start, value=round(rate, 2), quality=1.0)
        )
        increments.append(
            (
                bin_start,
                bin_end,
                steps,
                rate,
                [
                    f"{source}:step_bucket:{member.start.isoformat()}"
                    for member in members
                ],
            )
        )

    if not points:
        return None, [], None

    # More than one device counted these feet and only one of them is drawn.
    # That is the right call, but it is not a small one: it can be thousands of
    # steps, so it is said out loud rather than left in the difference between
    # this row and a phone's own step screen.
    # Read off the whole fetch window, not `ordered`. The connector marks the
    # first bucket it returns, and that one is usually the previous evening —
    # filtering to the day would drop the marker and lose the disclosure.
    discarded = next(
        (
            bucket.metadata["chosenOver"]
            for bucket in context.wearable.steps
            if bucket.metadata.get("chosenOver")
        ),
        [],
    )
    if discarded:
        others = ", ".join(
            f"{item.get('device') or item.get('platform') or 'an unnamed source'} "
            f"({item.get('steps'):,} steps)"
            for item in discarded
        )
        context.warnings.append(
            f"Steps came from {device or 'one source'} alone. {others} also reported "
            "steps for this day and were left out — the same walk counted by a watch "
            "and a phone is one walk, and adding them would inflate the day."
        )

    total_steps = sum(bucket.count for bucket in ordered)
    series = TimelineSeries(
        id="series_step_rate",
        phenotype="activity",
        label="Step rate",
        unit="steps/min",
        source=source,
        device=device,
        measured_or_derived="derived",
        points=points,
        # No silence gaps. A minute with no bucket is a minute with no steps,
        # which this source expresses by omission — drawing eight hours of sleep
        # as a recording gap would be the row inventing a fault.
        gaps=[],
        min_value=0,
        metadata={
            "totalStepsForDay": int(round(total_steps)),
            "bucketMinutes": rule.bucket_minutes,
            "sourceBuckets": len(ordered),
            "shape": "interval_deltas",
            "otherSourcesDiscarded": discarded,
            "note": (
                f"The provider reports steps per interval. They are summed into "
                f"{rule.bucket_minutes:g}-minute bins and divided by the bin, so this "
                "line is when movement happened rather than a running total. An "
                "interval the provider did not send is counted as zero steps, which "
                "is what it means — not as missing data."
            ),
        },
        provenance=build_provenance(
            rule=RULE_STEPS,
            version=rule.rule_version,
            raw_record_ids=[
                record_id for _s, _e, _c, _r, ids in increments for record_id in ids
            ],
            thresholds={"bucket_minutes": rule.bucket_minutes},
            input_range=(ordered[0].start, last),
            assumptions=[
                "An interval the provider did not report is zero steps rather than "
                "unknown, so a still night lowers no coverage figure.",
            ],
            notes=[
                "Read as interval deltas, never differenced: this shape already is "
                "the increment.",
            ],
        ),
    )

    events = _walking_periods(context, increments, None, source)
    return series, events, source


# --------------------------------------------------------------------------
# A cumulative daily counter
# --------------------------------------------------------------------------


def _steps_from_counter(
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
    increments: list[Increment] = []

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
        increments.append(
            (previous.timestamp, current.timestamp, delta, rate, [current.raw_record_id])
        )

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
            notes=[
                "Differenced out of a cumulative counter, so the timing is only as "
                "fine as the counter's reporting interval.",
            ],
        ),
    )

    events = _walking_periods(context, increments, entity_id, source)
    return series, events, source


def _walking_periods(
    context: RuleContext,
    increments: list[Increment],
    entity_id: str | None,
    source: str,
) -> list[TimelineEvent]:
    """Contiguous stretches where the step rate stayed at a walking pace."""
    rule = context.config.step_activity
    minimum = timedelta(minutes=rule.min_active_minutes)

    runs: list[list[Increment]] = []
    current: list[Increment] = []
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
                    raw_record_ids=[record_id for item in run for record_id in item[4]],
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
