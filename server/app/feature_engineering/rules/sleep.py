"""Sleep intervals.

Rule: prefer explicit wearable sleep records. Bed-occupancy from Home Assistant
is only used as a fallback when the wearable supplies nothing, and the resulting
event says so in its provenance.

Sleep routinely crosses midnight in both directions. Intervals are clipped to
the visible day for drawing, with `continuesBefore` / `continuesAfter` flags,
while the full timestamps survive in `metadata` for the details panel.
"""

from __future__ import annotations

from datetime import timedelta

from ...models.timeline import Lane, TimelineEvent
from ..context import RuleContext, sort_events
from ..provenance import build_provenance

RULE_ID = "sleep.sleep_interval"
FALLBACK_RULE_ID = "sleep.sleep_interval_from_bed_occupancy"

LANE = {
    "id": "sleep",
    "phenotype": "sleep",
    "label": "Sleep",
    "description": "Sleep periods and stages",
    "accent": "orange",
}


def build_lane(context: RuleContext) -> Lane:
    rule = context.config.sleep_interval
    lane = Lane(**LANE, available=False)
    events: list[TimelineEvent] = []
    payload = context.wearable
    sources: list[str] = []

    if payload.supports("sleep") and payload.sleep:
        sources.append(payload.source_id)
        for record in payload.sleep:
            duration = record.end - record.start
            is_main = record.is_main_sleep and duration >= timedelta(
                minutes=rule.main_sleep_minimum_minutes
            )
            if not is_main and duration < timedelta(minutes=rule.min_nap_minutes):
                continue
            clipped = context.clip_to_day(record.start, record.end)
            if clipped is None:
                continue
            start, end, before, after = clipped

            stage_minutes: dict[str, float] = {}
            for stage in record.stages:
                minutes = (stage.end - stage.start).total_seconds() / 60
                stage_minutes[stage.stage] = round(
                    stage_minutes.get(stage.stage, 0.0) + minutes, 1
                )

            events.append(
                TimelineEvent(
                    id=f"sleep_{record.id}",
                    phenotype="sleep",
                    label="Main sleep" if is_main else "Nap",
                    event_type="interval",
                    start_time=start,
                    end_time=end,
                    value=round(duration.total_seconds() / 60, 1),
                    unit="min",
                    source=payload.source_id,
                    device=record.device or payload.device,
                    measured_or_derived="measured",
                    confidence=0.97,
                    data_quality="high",
                    category="main_sleep" if is_main else "nap",
                    continues_before=before,
                    continues_after=after,
                    metadata={
                        "fullStart": record.start.isoformat(),
                        "fullEnd": record.end.isoformat(),
                        "durationMinutes": round(duration.total_seconds() / 60, 1),
                        "timeInBedMinutes": record.time_in_bed_minutes,
                        "awakeMinutes": record.awake_minutes,
                        "efficiency": record.efficiency,
                        "sleepScore": record.score,
                        "stageMinutes": stage_minutes,
                        "stages": [
                            {
                                "stage": stage.stage,
                                "start": stage.start.isoformat(),
                                "end": stage.end.isoformat(),
                            }
                            for stage in record.stages
                        ],
                        **record.metadata,
                    },
                    provenance=build_provenance(
                        rule=RULE_ID,
                        version=rule.rule_version,
                        raw_record_ids=[
                            raw.id
                            for raw in payload.raw_records
                            if raw.stream == "sleep" and raw.attributes.get("id") == record.id
                        ],
                        thresholds={
                            "prefer_wearable_records": rule.prefer_wearable_records,
                            "main_sleep_minimum_minutes": rule.main_sleep_minimum_minutes,
                            "min_nap_minutes": rule.min_nap_minutes,
                        },
                        input_range=(record.start, record.end),
                        assumptions=(
                            ["The interval extends outside the displayed day and was clipped."]
                            if before or after
                            else []
                        ),
                        notes=["Taken from the provider's sleep record."],
                    ),
                )
            )

    elif rule.environmental_fallback:
        fallback_events, fallback_source = _from_bed_occupancy(context)
        events.extend(fallback_events)
        if fallback_source:
            sources.append(fallback_source)

    lane.events = sort_events(events)
    lane.available = bool(events)
    lane.sources = sources
    lane.units = ["min"]
    if not events:
        lane.unavailable_reason = (
            "No sleep records were available for this day from the wearable provider "
            "or a bed-occupancy sensor."
        )
    return lane


def _from_bed_occupancy(context: RuleContext) -> tuple[list[TimelineEvent], str | None]:
    """Fallback: treat contiguous `on` bed-occupancy as a sleep interval."""
    rule = context.config.sleep_interval
    states = [
        state
        for state in context.normalized.states_for("bed_occupancy")
        if state.state == "on"
    ]
    if not states:
        return [], None

    events: list[TimelineEvent] = []
    for index, state in enumerate(states):
        duration = state.end_time - state.start_time
        is_main = duration >= timedelta(minutes=rule.main_sleep_minimum_minutes)
        if not is_main and duration < timedelta(minutes=rule.min_nap_minutes):
            continue
        clipped = context.clip_to_day(state.start_time, state.end_time)
        if clipped is None:
            continue
        start, end, before, after = clipped
        events.append(
            TimelineEvent(
                id=f"sleep_bed_{index}_{int(state.start_time.timestamp())}",
                phenotype="sleep",
                label="Time in bed" if is_main else "Short time in bed",
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round(duration.total_seconds() / 60, 1),
                unit="min",
                source=state.source,
                device=state.device,
                entity_id=state.entity_id,
                measured_or_derived="derived",
                confidence=0.55,
                data_quality="medium",
                category="time_in_bed",
                continues_before=before,
                continues_after=after,
                metadata={
                    "fullStart": state.start_time.isoformat(),
                    "fullEnd": state.end_time.isoformat(),
                    "durationMinutes": round(duration.total_seconds() / 60, 1),
                    "note": (
                        "Derived from a bed-occupancy sensor because no wearable sleep "
                        "record was available. Time in bed is not the same as sleep."
                    ),
                },
                provenance=build_provenance(
                    rule=FALLBACK_RULE_ID,
                    version=rule.rule_version,
                    raw_record_ids=state.raw_record_ids,
                    entity_ids=[state.entity_id] if state.entity_id else [],
                    thresholds={
                        "main_sleep_minimum_minutes": rule.main_sleep_minimum_minutes,
                        "min_nap_minutes": rule.min_nap_minutes,
                    },
                    input_range=(state.start_time, state.end_time),
                    assumptions=[
                        "Bed occupancy is used as a proxy for sleep; sleep stages are unknown."
                    ],
                    notes=["Fallback rule: no wearable sleep record was available."],
                ),
            )
        )
    return events, states[0].source
