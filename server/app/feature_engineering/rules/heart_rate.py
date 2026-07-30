"""Heart rate: continuous series plus neutrally-labelled notable events.

Elevated heart rate is reported relative to the user's own observed baseline.
It is never called stress, anxiety, or an abnormality — the data cannot support
those labels, and no connected source supplies them.
"""

from __future__ import annotations

from datetime import timedelta

from ...models.raw import NormalizedSample
from ...models.timeline import Lane, SeriesPoint, TimelineEvent, TimelineSeries
from ..context import Baseline, RuleContext, sort_events
from ..provenance import build_provenance, detect_gaps, mean_and_sd

RULE_ELEVATED = "heart_rate.elevated_heart_rate"
RULE_EXTREMES = "heart_rate.daily_extremes"
RULE_RESTING = "heart_rate.resting_heart_rate"

LANE = {
    "id": "heart_rate",
    "phenotype": "heart_rate",
    "label": "Heart Rate",
    "description": "Wearable cardiovascular signal",
    "accent": "blue",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)
    payload = context.wearable

    samples = [
        sample
        for sample in context.normalized.samples_for("heart_rate")
        if context.window.contains(sample.timestamp)
    ]

    if not samples:
        # Some integrations publish only a once-a-day resting value. That is a
        # real measurement, but it is not a heart-rate curve and is not drawn
        # as one.
        daily = _daily_resting_events(context)
        if daily:
            lane.events = sort_events(daily)
            lane.available = True
            lane.sources = sorted({event.source for event in daily})
            lane.units = ["bpm"]
            return lane

        if not payload.supports("heart_rate"):
            lane.unavailable_reason = (
                "No connected source publishes heart rate. The wearable provider does "
                "not expose it, and no heart-rate entity is mapped in config.yaml."
            )
        else:
            lane.unavailable_reason = "No heart-rate samples were recorded yesterday."
        return lane

    samples.sort(key=lambda sample: sample.timestamp)
    gaps = detect_gaps(
        samples,
        context.window.start,
        context.window.end,
        context.max_gap,
        reason="The wearable recorded no heart rate here (for example while charging).",
    )

    values = [sample.value for sample in samples]
    series = TimelineSeries(
        id="series_heart_rate",
        phenotype="heart_rate",
        label="Heart rate",
        unit="bpm",
        source=payload.source_id,
        device=payload.device,
        measured_or_derived="measured",
        points=[
            SeriesPoint(timestamp=sample.timestamp, value=sample.value, quality=sample.quality)
            for sample in samples
        ],
        gaps=gaps,
        min_value=min(values),
        max_value=max(values),
        metadata={
            "sampleIntervalMinutes": _median_interval_minutes(samples),
            "sampleCount": len(samples),
        },
        provenance=build_provenance(
            rule="heart_rate.series",
            version="1.0.0",
            raw_record_ids=[sample.raw_record_id for sample in samples],
            input_range=(samples[0].timestamp, samples[-1].timestamp),
            assumptions=[
                "Lines are broken across gaps longer than "
                f"{context.config.data_gap.max_gap_minutes:.0f} minutes rather than interpolated."
            ],
        ),
    )

    baseline = context.baselines.get("heart_rate") or _baseline_from_day(samples)
    events = _elevated_events(context, samples, baseline)
    events.extend(_extreme_events(context, samples))
    resting = _resting_event(context, samples)
    if resting is not None:
        events.append(resting)

    lane.series = [series]
    lane.events = sort_events(events)
    lane.available = True
    lane.sources = [payload.source_id]
    lane.units = ["bpm"]
    return lane


def _daily_resting_events(context: RuleContext) -> list[TimelineEvent]:
    """A once-a-day resting heart rate, shown as a single point."""
    samples = sorted(
        (
            sample
            for sample in context.normalized.samples_for("resting_heart_rate")
            if context.window.contains(sample.timestamp)
        ),
        key=lambda sample: sample.timestamp,
    )
    if not samples:
        return []

    # The integration may republish the same figure; one point per value is enough.
    events: list[TimelineEvent] = []
    seen: set[float] = set()
    for sample in samples:
        if sample.value in seen:
            continue
        seen.add(sample.value)
        events.append(
            TimelineEvent(
                id=f"hr_daily_resting_{int(sample.timestamp.timestamp())}",
                phenotype="heart_rate",
                label="Resting heart rate (daily)",
                event_type="point",
                start_time=sample.timestamp,
                value=round(sample.value, 1),
                unit="bpm",
                source=sample.source,
                device=sample.device,
                entity_id=sample.entity_id,
                measured_or_derived="measured",
                confidence=0.9,
                data_quality="high",
                category="resting",
                metadata={
                    "reportedAt": sample.timestamp.isoformat(),
                    "note": (
                        "This integration publishes one resting heart-rate figure per "
                        "day rather than a continuous signal. The point is placed at "
                        "the time the value was reported, not at a time it was "
                        "measured, and no curve is drawn between values."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_RESTING,
                    version="1.1.0",
                    raw_record_ids=[sample.raw_record_id],
                    entity_ids=[sample.entity_id] if sample.entity_id else [],
                    input_range=(context.window.start, context.window.end),
                    output_timestamp=sample.timestamp,
                    assumptions=[
                        "A daily summary value is not expanded into a time series."
                    ],
                ),
            )
        )
    return events


def _median_interval_minutes(samples: list[NormalizedSample]) -> float | None:
    if len(samples) < 2:
        return None
    deltas = sorted(
        (b.timestamp - a.timestamp).total_seconds() / 60 for a, b in zip(samples, samples[1:])
    )
    return round(deltas[len(deltas) // 2], 2)


def _baseline_from_day(samples: list[NormalizedSample]) -> Baseline:
    mean, sd = mean_and_sd([sample.value for sample in samples])
    return Baseline(
        stream="heart_rate",
        mean=mean,
        sd=sd,
        sample_count=len(samples),
        days=1,
        source="current_day",
    )


def _elevated_events(
    context: RuleContext, samples: list[NormalizedSample], baseline: Baseline
) -> list[TimelineEvent]:
    rule = context.config.elevated_heart_rate
    if baseline.sd <= 0:
        return []

    threshold = baseline.mean + rule.sd_threshold * baseline.sd
    minimum = timedelta(minutes=rule.min_duration_minutes)

    runs: list[list[NormalizedSample]] = []
    current: list[NormalizedSample] = []
    for sample in samples:
        if sample.value >= threshold:
            current.append(sample)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)

    activity_windows = [
        (record.start, record.end, record.label)
        for record in context.wearable.activity
    ]

    events: list[TimelineEvent] = []
    for index, run in enumerate(runs):
        start = run[0].timestamp
        end = run[-1].timestamp
        if end - start < minimum:
            continue

        overlapping = next(
            (
                label
                for window_start, window_end, label in activity_windows
                if window_start < end and window_end > start
            ),
            None,
        )
        peak = max(sample.value for sample in run)
        mean_value = sum(sample.value for sample in run) / len(run)
        z_score = baseline.z_score(peak)

        label = "Exercise-associated heart rate" if overlapping else "Elevated heart rate"
        events.append(
            TimelineEvent(
                id=f"hr_elevated_{index}_{int(start.timestamp())}",
                phenotype="heart_rate",
                label=label,
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round(peak, 1),
                unit="bpm",
                source=context.wearable.source_id,
                device=context.wearable.device,
                measured_or_derived="derived",
                confidence=0.8,
                data_quality="high",
                category="elevated",
                metadata={
                    "peakBpm": round(peak, 1),
                    "meanBpm": round(mean_value, 1),
                    "durationMinutes": round((end - start).total_seconds() / 60, 1),
                    "baselineMeanBpm": round(baseline.mean, 1),
                    "baselineSdBpm": round(baseline.sd, 2),
                    "baselineDescription": baseline.describe(),
                    "peakZScore": round(z_score, 2) if z_score is not None else None,
                    "concurrentActivity": overlapping,
                    "interpretation": (
                        f"Peak was {z_score:.1f} standard deviations above the user's "
                        f"{baseline.describe()}."
                        if z_score is not None
                        else "Baseline variability was too small to compute a z-score."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_ELEVATED,
                    version=rule.rule_version,
                    raw_record_ids=[sample.raw_record_id for sample in run],
                    thresholds={
                        "sd_threshold": rule.sd_threshold,
                        "min_duration_minutes": rule.min_duration_minutes,
                        "baseline_window_days": rule.baseline_window_days,
                        "computed_threshold_bpm": round(threshold, 1),
                    },
                    input_range=(start, end),
                    notes=[
                        f"Baseline: {baseline.describe()}.",
                        "Label is descriptive of the measurement only; no psychological "
                        "state is inferred.",
                    ]
                    + (
                        [f"Overlaps the recorded activity '{overlapping}'."]
                        if overlapping
                        else []
                    ),
                ),
            )
        )
    return events


def _extreme_events(context: RuleContext, samples: list[NormalizedSample]) -> list[TimelineEvent]:
    highest = max(samples, key=lambda sample: sample.value)
    lowest = min(samples, key=lambda sample: sample.value)
    events = []
    for kind, sample, label in (
        ("max", highest, "Heart-rate peak"),
        ("min", lowest, "Daily minimum heart rate"),
    ):
        events.append(
            TimelineEvent(
                id=f"hr_{kind}_{int(sample.timestamp.timestamp())}",
                phenotype="heart_rate",
                label=label,
                event_type="point",
                start_time=sample.timestamp,
                value=round(sample.value, 1),
                unit="bpm",
                source=context.wearable.source_id,
                device=context.wearable.device,
                measured_or_derived="derived",
                confidence=1.0,
                data_quality="high",
                category=f"extreme_{kind}",
                metadata={
                    "sampleCount": len(samples),
                    "note": f"The {'highest' if kind == 'max' else 'lowest'} single sample "
                    "recorded during the displayed day.",
                },
                provenance=build_provenance(
                    rule=RULE_EXTREMES,
                    version="1.0.0",
                    raw_record_ids=[sample.raw_record_id],
                    input_range=(context.window.start, context.window.end),
                    output_timestamp=sample.timestamp,
                ),
            )
        )
    return events


def _resting_event(context: RuleContext, samples: list[NormalizedSample]) -> TimelineEvent | None:
    """Mean heart rate across the main sleep period, when one is known."""
    main_sleep = next(
        (record for record in context.wearable.sleep if record.is_main_sleep), None
    )
    if main_sleep is None:
        return None

    during = [
        sample
        for sample in samples
        if main_sleep.start <= sample.timestamp < main_sleep.end
    ]
    if len(during) < 3:
        return None

    mean, sd = mean_and_sd([sample.value for sample in during])
    midpoint = during[len(during) // 2].timestamp
    return TimelineEvent(
        id=f"hr_resting_{int(midpoint.timestamp())}",
        phenotype="heart_rate",
        label="Resting heart rate",
        event_type="point",
        start_time=midpoint,
        value=round(mean, 1),
        unit="bpm",
        source=context.wearable.source_id,
        device=context.wearable.device,
        measured_or_derived="derived",
        confidence=0.9,
        data_quality="high",
        category="resting",
        metadata={
            "meanBpm": round(mean, 1),
            "sdBpm": round(sd, 2),
            "sampleCount": len(during),
            "windowStart": main_sleep.start.isoformat(),
            "windowEnd": main_sleep.end.isoformat(),
            "note": "Mean heart rate across the main sleep period.",
        },
        provenance=build_provenance(
            rule=RULE_RESTING,
            version="1.0.0",
            raw_record_ids=[sample.raw_record_id for sample in during],
            input_range=(main_sleep.start, main_sleep.end),
            output_timestamp=midpoint,
            notes=["Averaged over the wearable's main sleep interval."],
        ),
    )
