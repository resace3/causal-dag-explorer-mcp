"""Environment lane: light conditions plus a compact room-temperature sub-line.

Light categories are derived from measured illuminance using thresholds that
live in `config.yaml`. Nothing here hardcodes sunrise or sunset.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ...models.raw import NormalizedSample
from ...models.timeline import Lane, SeriesGap, SeriesPoint, TimelineEvent, TimelineSeries
from ..context import RuleContext, sort_events
from ..provenance import build_provenance, detect_gaps

RULE_LIGHT = "environment.light_category"
RULE_GAP = "environment.missing_data"

LANE = {
    "id": "environment",
    "phenotype": "environment",
    "label": "Environment",
    "description": "Home conditions",
    "accent": "sky",
}

CATEGORY_TITLES = {
    "dark": "Dark",
    "dim": "Dim",
    "moderate": "Moderate",
    "bright": "Bright",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)
    events: list[TimelineEvent] = []
    series: list[TimelineSeries] = []
    sources: list[str] = []

    illuminance = _preferred_entity_samples(context, "illuminance")
    if illuminance:
        light_events, light_source = _light_intervals(context, illuminance)
        events.extend(light_events)
        if light_source:
            sources.append(light_source)

    room_series = _room_temperature_series(context)
    if room_series is not None:
        series.append(room_series)
        if room_series.source not in sources:
            sources.append(room_series.source)

    lane.events = sort_events(events)
    lane.series = series
    lane.available = bool(events or series)
    lane.sources = sources
    lane.units = sorted({unit for unit in [s.unit for s in series] if unit})

    if not lane.available:
        if not context.home_assistant_available:
            lane.unavailable_reason = (
                "Home Assistant could not be reached, so no environmental data is available."
            )
        elif context.normalized.raw_for("illuminance") or context.normalized.raw_for(
            "room_temperature"
        ):
            lane.unavailable_reason = (
                "The mapped environmental sensors reported no reading during this day. "
                "Home Assistant records changes only, so a sensor that never updated "
                "leaves no value inside the window."
            )
        else:
            lane.unavailable_reason = (
                "No illuminance or room-temperature entities produced data yesterday. "
                "Check home_assistant.entities in config.yaml."
            )
    return lane


def _preferred_entity_samples(context: RuleContext, stream: str) -> list[NormalizedSample]:
    """Pick one entity per stream so the lane stays readable."""
    samples = [
        sample
        for sample in context.normalized.samples_for(stream)
        if context.window.contains(sample.timestamp)
    ]
    if not samples:
        return []

    by_entity: dict[str | None, list[NormalizedSample]] = {}
    for sample in samples:
        by_entity.setdefault(sample.entity_id, []).append(sample)

    priority = context.config.light_category.entity_priority if stream == "illuminance" else []
    for entity_id in priority:
        if entity_id in by_entity:
            return sorted(by_entity[entity_id], key=lambda s: s.timestamp)

    best = max(by_entity.values(), key=len)
    return sorted(best, key=lambda sample: sample.timestamp)


def _light_intervals(
    context: RuleContext, samples: list[NormalizedSample]
) -> tuple[list[TimelineEvent], str | None]:
    rule = context.config.light_category
    minimum = timedelta(minutes=rule.min_duration_minutes)
    entity_id = samples[0].entity_id
    source = samples[0].source

    classified = [
        (sample, rule.classify(sample.value))
        for sample in samples
    ]
    classified = [(sample, name) for sample, name in classified if name is not None]
    if not classified:
        return [], None

    runs: list[list[tuple[NormalizedSample, str]]] = []
    for item in classified:
        if runs and runs[-1][0][1] == item[1]:
            runs[-1].append(item)
        else:
            runs.append([item])

    runs = _merge_short_runs(runs, minimum)

    gaps = detect_gaps(
        samples,
        context.window.start,
        context.window.end,
        # Home Assistant records changes, not samples: a steady sensor is not
        # a missing one. Only a long silence counts as unknown.
        context.stale_gap,
        reason="The illuminance sensor reported no value for longer than the staleness limit.",
        explicit=[
            (period.start_time, period.end_time)
            for period in context.normalized.unavailable_for("illuminance")
            if period.entity_id == entity_id
        ],
    )

    spans: list[tuple[datetime, datetime, str, list[tuple[NormalizedSample, str]]]] = []
    for index, run in enumerate(runs):
        start = run[0][0].timestamp if index else context.window.start
        end = runs[index + 1][0][0].timestamp if index + 1 < len(runs) else context.window.end
        spans.append((start, end, run[0][1], run))

    events: list[TimelineEvent] = []
    for start, end, category, run in spans:
        for piece_start, piece_end in _subtract(start, end, gaps):
            if piece_end - piece_start < minimum:
                continue
            lux_values = [
                sample.value
                for sample, _name in run
                if piece_start <= sample.timestamp <= piece_end
            ] or [sample.value for sample, _name in run]
            mean_lux = sum(lux_values) / len(lux_values)
            band = rule.thresholds[category]
            events.append(
                TimelineEvent(
                    id=f"light_{category}_{int(piece_start.timestamp())}",
                    phenotype="environment",
                    label=f"{CATEGORY_TITLES.get(category, category.title())} light",
                    event_type="interval",
                    start_time=piece_start,
                    end_time=piece_end,
                    value=round(mean_lux, 1),
                    unit="lx",
                    source=source,
                    entity_id=entity_id,
                    device=run[0][0].device,
                    measured_or_derived="derived",
                    confidence=0.85,
                    data_quality="high",
                    category=f"light_{category}",
                    metadata={
                        "lightCategory": category,
                        "meanIlluminance": round(mean_lux, 1),
                        "maxIlluminance": round(max(lux_values), 1),
                        "minIlluminance": round(min(lux_values), 1),
                        "sampleCount": len(lux_values),
                        "durationMinutes": round((piece_end - piece_start).total_seconds() / 60, 1),
                        "classificationRule": _describe_band(category, band),
                    },
                    provenance=build_provenance(
                        rule=RULE_LIGHT,
                        version=rule.rule_version,
                        raw_record_ids=[sample.raw_record_id for sample, _ in run],
                        entity_ids=[entity_id] if entity_id else [],
                        thresholds={
                            name: {"min_lux": value.min_lux, "max_lux": value.max_lux}
                            for name, value in rule.thresholds.items()
                        }
                        | {"min_duration_minutes": rule.min_duration_minutes},
                        input_range=(piece_start, piece_end),
                        notes=[
                            "Categories come from measured illuminance, not from fixed "
                            "sunrise/sunset times."
                        ],
                    ),
                )
            )

    events.extend(_gap_events(context, gaps, entity_id, source))
    return events, source


def _describe_band(category: str, band) -> str:
    title = CATEGORY_TITLES.get(category, category.title())
    if band.min_lux is not None and band.max_lux is not None:
        return f"{title} when illuminance is between {band.min_lux:g} and {band.max_lux:g} lux"
    if band.min_lux is not None:
        return f"{title} when illuminance exceeds {band.min_lux:g} lux"
    return f"{title} when illuminance is below {band.max_lux:g} lux"


def _merge_short_runs(runs: list[list], minimum: timedelta) -> list[list]:
    """Absorb runs too short to be meaningful into their longer neighbour."""
    if len(runs) <= 1:
        return runs

    changed = True
    while changed and len(runs) > 1:
        changed = False
        for index, run in enumerate(runs):
            span = run[-1][0].timestamp - run[0][0].timestamp
            if span >= minimum:
                continue
            previous = runs[index - 1] if index > 0 else None
            following = runs[index + 1] if index + 1 < len(runs) else None
            target = previous
            if previous is None:
                target = following
            elif following is not None:
                previous_span = previous[-1][0].timestamp - previous[0][0].timestamp
                following_span = following[-1][0].timestamp - following[0][0].timestamp
                target = previous if previous_span >= following_span else following
            if target is None:
                continue
            target.extend(run)
            target.sort(key=lambda item: item[0].timestamp)
            runs.pop(index)
            changed = True
            break
    return runs


def _subtract(
    start: datetime, end: datetime, gaps: list[SeriesGap]
) -> list[tuple[datetime, datetime]]:
    """Remove gap intervals from [start, end)."""
    pieces = [(start, end)]
    for gap in gaps:
        next_pieces: list[tuple[datetime, datetime]] = []
        for piece_start, piece_end in pieces:
            if gap.end_time <= piece_start or gap.start_time >= piece_end:
                next_pieces.append((piece_start, piece_end))
                continue
            if gap.start_time > piece_start:
                next_pieces.append((piece_start, gap.start_time))
            if gap.end_time < piece_end:
                next_pieces.append((gap.end_time, piece_end))
        pieces = next_pieces
    return [(a, b) for a, b in pieces if b > a]


def _gap_events(
    context: RuleContext, gaps: list[SeriesGap], entity_id: str | None, source: str
) -> list[TimelineEvent]:
    events = []
    for gap in gaps:
        events.append(
            TimelineEvent(
                id=f"env_gap_{int(gap.start_time.timestamp())}",
                phenotype="environment",
                label="No illuminance data",
                event_type="interval",
                start_time=gap.start_time,
                end_time=gap.end_time,
                source=source,
                entity_id=entity_id,
                measured_or_derived="derived",
                confidence=1.0,
                data_quality="unknown",
                category="missing_data",
                metadata={
                    "durationMinutes": round(
                        (gap.end_time - gap.start_time).total_seconds() / 60, 1
                    ),
                    "reason": gap.reason,
                    "note": (
                        "Light conditions during this period are unknown. Nothing is "
                        "assumed or interpolated."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_GAP,
                    version=context.config.data_gap.rule_version,
                    entity_ids=[entity_id] if entity_id else [],
                    thresholds={"max_gap_minutes": context.config.data_gap.max_gap_minutes},
                    input_range=(gap.start_time, gap.end_time),
                    assumptions=["No value is carried forward across the gap."],
                ),
            )
        )
    return events


def _room_temperature_series(context: RuleContext) -> TimelineSeries | None:
    samples = _preferred_entity_samples(context, "room_temperature")
    if not samples:
        return None
    values = [sample.value for sample in samples]
    unit = samples[0].unit or "°F"
    entity_id = samples[0].entity_id
    name = (samples[0].device or entity_id or "Room").replace("_", " ").strip()
    # Sensor friendly names often already end in "temperature".
    if name.lower().endswith("temperature"):
        label = name[0].upper() + name[1:]
    else:
        label = f"{name} temperature"
    gaps = detect_gaps(
        samples,
        context.window.start,
        context.window.end,
        context.stale_gap,
        reason="The temperature sensor reported no value for longer than the staleness limit.",
        explicit=[
            (period.start_time, period.end_time)
            for period in context.normalized.unavailable_for("room_temperature")
            if period.entity_id == entity_id
        ],
    )
    return TimelineSeries(
        id=f"series_room_temperature_{entity_id or 'default'}",
        phenotype="environment",
        label=label,
        unit=unit,
        source=samples[0].source,
        device=samples[0].device,
        entity_id=entity_id,
        measured_or_derived="measured",
        points=[SeriesPoint(timestamp=s.timestamp, value=s.value) for s in samples],
        gaps=gaps,
        min_value=min(values),
        max_value=max(values),
        style="secondary",
        metadata={
            "measurement": "room_temperature",
            "sampleCount": len(samples),
            "note": "Room temperature from Home Assistant, not a body temperature.",
        },
        provenance=build_provenance(
            rule="environment.room_temperature_series",
            version="1.0.0",
            raw_record_ids=[sample.raw_record_id for sample in samples],
            entity_ids=[entity_id] if entity_id else [],
            input_range=(samples[0].timestamp, samples[-1].timestamp),
        ),
    )
