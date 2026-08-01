"""Wearable temperature.

The lane label always reflects what the sensor actually measures. A wrist sensor
reports skin temperature; it is never relabelled as core body temperature.
Room temperature lives in the Environment lane, not here.
"""

from __future__ import annotations

from datetime import timedelta

from ...models.timeline import Lane, SeriesPoint, TimelineEvent, TimelineSeries
from ..context import RuleContext, sort_events
from ..provenance import build_provenance, detect_gaps, mean_and_sd

RULE_DEVIATION = "temperature.deviation_from_baseline"

MEASUREMENT_LABELS = {
    "skin_temperature": ("Skin Temperature", "Wearable wrist sensor", "Skin temperature"),
    "wrist_temperature_deviation": (
        "Wrist Temperature Deviation",
        "Deviation from personal baseline",
        "Wrist temperature deviation",
    ),
    "core_body_temperature": (
        "Core Body Temperature",
        "Ingestible or clinical sensor",
        "Core body temperature",
    ),
}

LANE_ID = "temperature"


def build_lane(context: RuleContext) -> Lane:
    payload = context.wearable
    measurement = payload.temperature[0].measurement if payload.temperature else "skin_temperature"
    lane_label, lane_description, series_label = MEASUREMENT_LABELS.get(
        measurement, ("Temperature", "Wearable temperature sensor", "Temperature")
    )

    lane = Lane(
        id=LANE_ID,
        phenotype="temperature",
        label=lane_label,
        description=lane_description,
        accent="teal",
        available=False,
    )

    if not payload.supports("temperature"):
        lane.unavailable_reason = (
            "The configured wearable provider does not expose temperature data."
        )
        return lane

    samples = [
        sample
        for sample in context.normalized.samples_for("skin_temperature")
        if context.window.contains(sample.timestamp)
    ]
    if not samples:
        lane.unavailable_reason = "No wearable temperature samples were recorded on this day."
        return lane

    samples.sort(key=lambda sample: sample.timestamp)
    unit = payload.temperature[0].unit if payload.temperature else "°F"
    values = [sample.value for sample in samples]
    gaps = detect_gaps(
        samples,
        context.window.start,
        context.window.end,
        context.max_gap * 2,
        reason="The wearable recorded no temperature here (for example while charging).",
    )

    series = TimelineSeries(
        id="series_skin_temperature",
        phenotype="temperature",
        label=series_label,
        unit=unit,
        source=payload.source_id,
        device=payload.device,
        measured_or_derived="measured",
        points=[SeriesPoint(timestamp=s.timestamp, value=s.value) for s in samples],
        gaps=gaps,
        min_value=min(values),
        max_value=max(values),
        metadata={"measurement": measurement, "sampleCount": len(samples)},
        provenance=build_provenance(
            rule="temperature.series",
            version="1.0.0",
            raw_record_ids=[sample.raw_record_id for sample in samples],
            input_range=(samples[0].timestamp, samples[-1].timestamp),
            notes=[f"Sensor measurement type reported by the provider: {measurement}."],
        ),
    )

    lane.series = [series]
    lane.events = sort_events(_deviation_events(context, samples, unit, series_label))
    lane.available = True
    lane.sources = [payload.source_id]
    lane.units = [unit]
    return lane


def _deviation_events(context, samples, unit, series_label) -> list[TimelineEvent]:
    """Stretches that sit well above or below the user's own observed range."""
    rule = context.config.temperature_deviation
    baseline = context.baselines.get("skin_temperature")
    if baseline is None:
        mean, sd = mean_and_sd([sample.value for sample in samples])
        from ..context import Baseline  # local import avoids a cycle at module load

        baseline = Baseline(
            stream="skin_temperature",
            mean=mean,
            sd=sd,
            sample_count=len(samples),
            days=1,
            source="current_day",
        )
    if baseline.sd <= 0:
        return []

    minimum = timedelta(minutes=rule.min_duration_minutes)
    events: list[TimelineEvent] = []

    for direction, comparator in (("above", 1.0), ("below", -1.0)):
        threshold = baseline.mean + comparator * rule.sd_threshold * baseline.sd
        run: list = []
        runs: list[list] = []
        for sample in samples:
            beyond = (
                sample.value >= threshold if comparator > 0 else sample.value <= threshold
            )
            if beyond:
                run.append(sample)
            else:
                if run:
                    runs.append(run)
                run = []
        if run:
            runs.append(run)

        for index, group in enumerate(runs):
            start, end = group[0].timestamp, group[-1].timestamp
            if end - start < minimum:
                continue
            extreme = (max if comparator > 0 else min)(sample.value for sample in group)
            z_score = baseline.z_score(extreme)
            events.append(
                TimelineEvent(
                    id=f"temp_dev_{direction}_{index}_{int(start.timestamp())}",
                    phenotype="temperature",
                    label=f"{series_label} {direction} personal baseline",
                    event_type="interval",
                    start_time=start,
                    end_time=end,
                    value=round(extreme, 2),
                    unit=unit,
                    source=context.wearable.source_id,
                    device=context.wearable.device,
                    measured_or_derived="derived",
                    confidence=0.7,
                    data_quality="medium",
                    category=f"deviation_{direction}",
                    metadata={
                        "baselineMean": round(baseline.mean, 2),
                        "baselineSd": round(baseline.sd, 3),
                        "baselineDescription": baseline.describe(),
                        "extremeValue": round(extreme, 2),
                        "zScore": round(z_score, 2) if z_score is not None else None,
                        "durationMinutes": round((end - start).total_seconds() / 60, 1),
                        "note": (
                            "Described relative to this user's own observed range. "
                            "No clinical interpretation is implied."
                        ),
                    },
                    provenance=build_provenance(
                        rule=RULE_DEVIATION,
                        version=rule.rule_version,
                        raw_record_ids=[sample.raw_record_id for sample in group],
                        thresholds={
                            "sd_threshold": rule.sd_threshold,
                            "min_duration_minutes": rule.min_duration_minutes,
                            "computed_threshold": round(threshold, 2),
                        },
                        input_range=(start, end),
                        notes=[f"Baseline: {baseline.describe()}."],
                    ),
                )
            )
    return events
