"""Sleep duration.

**This row is about how long, not about what happened inside.** One bar per
sleep period, labelled with the time actually asleep. Stage-by-stage hypnograms
are not drawn and not stored — the Google Health connector discards them where
they arrive, and no other provider's stages reach this row either, so the row
means the same thing whichever source filled it.

Rule: prefer explicit wearable sleep records. Bed-occupancy from Home Assistant
is only used as a fallback when the wearable supplies nothing, and the resulting
event says so in its provenance.

The bar spans the sleep *period* while its value is the time *asleep*, and the
two differ by the minutes spent awake in bed. Both are in the details panel:
drawing one and labelling it with the other, silently, would make a 484-minute
bar read as 477 minutes with nothing to explain the gap.

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
    "label": "Sleep Duration",
    "description": "How long each sleep period lasted",
    "accent": "orange",
}


def _asleep_minutes(record, period_minutes: float) -> float | None:
    """Minutes actually asleep, when the provider is in a position to say.

    Google Health reports it outright. A provider that only reports minutes
    awake still implies it. One that reports neither gets None rather than the
    period relabelled as sleep — time in bed is not time asleep, and this row
    is read as a number.
    """
    stated = record.metadata.get("minutesAsleep")
    if isinstance(stated, (int, float)):
        return round(float(stated), 1)
    if isinstance(record.awake_minutes, (int, float)):
        return round(max(period_minutes - float(record.awake_minutes), 0.0), 1)
    return None


def _duration(minutes: float) -> str:
    hours, rest = divmod(int(round(minutes)), 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    if hours:
        return f"{hours}h"
    return f"{rest}m"


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

            # Time asleep when it is known, the whole period otherwise. Which
            # of the two a number is gets recorded rather than left to be
            # guessed from how close it is to the bar's width.
            period_minutes = round(duration.total_seconds() / 60, 1)
            asleep_minutes = _asleep_minutes(record, period_minutes)
            reported = asleep_minutes if asleep_minutes is not None else period_minutes
            basis = "time asleep" if asleep_minutes is not None else "whole sleep period"

            events.append(
                TimelineEvent(
                    id=f"sleep_{record.id}",
                    phenotype="sleep",
                    label=f"{'Main sleep' if is_main else 'Nap'} · {_duration(reported)}",
                    event_type="interval",
                    start_time=start,
                    end_time=end,
                    value=reported,
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
                        # Provider extras first: what this rule computes wins
                        # over a same-named key carried up from the connector.
                        **record.metadata,
                        "fullStart": record.start.isoformat(),
                        "fullEnd": record.end.isoformat(),
                        # The bar's own length, so the drawn width and the
                        # reported number are never confused for each other.
                        "durationMinutes": reported,
                        "durationBasis": basis,
                        "sleepPeriodMinutes": period_minutes,
                        "minutesAsleep": asleep_minutes,
                        "timeInBedMinutes": record.time_in_bed_minutes,
                        "awakeMinutes": record.awake_minutes,
                        "efficiency": record.efficiency,
                        "sleepScore": record.score,
                        # No `stages` key: this row reports duration, and the
                        # hypnogram is dropped at the connector rather than
                        # carried to something that will not draw it.
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
                        notes=[
                            "Taken from the provider's sleep record.",
                            "Duration only: sleep stages are not stored by this "
                            "application, so none can be shown here.",
                        ],
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
                label=(
                    f"{'Time in bed' if is_main else 'Short time in bed'} · "
                    f"{_duration(duration.total_seconds() / 60)}"
                ),
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
