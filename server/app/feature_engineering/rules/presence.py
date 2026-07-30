"""Home presence and motion.

Only home / away / room-level states are exposed. Geographic coordinates are
never read or emitted, and would require an explicit future configuration step.
"""

from __future__ import annotations

from datetime import timedelta

from ...models.timeline import Lane, TimelineEvent
from ..context import RuleContext, sort_events
from ..provenance import build_provenance

RULE_PRESENCE = "presence.home_presence"
RULE_TRANSITION = "presence.arrival_departure"
RULE_MOTION = "presence.motion_event"
RULE_INACTIVITY = "presence.sustained_inactivity"
RULE_DOOR = "presence.door_event"
RULE_DEVICE_USE = "presence.device_use_session"

LANE = {
    "id": "presence",
    "phenotype": "presence",
    "label": "Presence & Motion",
    "description": "Home occupancy signals",
    "accent": "cyan",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)
    events: list[TimelineEvent] = []
    sources: list[str] = []

    presence_events, presence_source = _presence_intervals(context)
    events.extend(presence_events)
    if presence_source:
        sources.append(presence_source)

    motion_events, motion_source = _motion_events(context)
    events.extend(motion_events)
    if motion_source and motion_source not in sources:
        sources.append(motion_source)

    door_events, door_source = _door_events(context)
    events.extend(door_events)
    if door_source and door_source not in sources:
        sources.append(door_source)

    device_events, device_source = _device_use_events(context)
    events.extend(device_events)
    if device_source and device_source not in sources:
        sources.append(device_source)

    events.extend(_inactivity_events(context))

    lane.events = sort_events(events)
    lane.available = bool(events)
    lane.sources = sources
    if not events:
        if not context.home_assistant_available:
            lane.unavailable_reason = (
                "Home Assistant could not be reached, so presence and motion are unknown."
            )
        else:
            lane.unavailable_reason = (
                "No presence or motion entities produced data yesterday. Add entity IDs "
                "under home_assistant.entities.presence and .motion in config.yaml."
            )
    return lane


def _select_presence_entity(context: RuleContext) -> tuple[list, list[str]]:
    """Pick one presence entity; a person and its device tracker are the same fact.

    Returns the chosen entity's states plus the other entity ids, which are kept
    as corroborating sources rather than drawn as duplicate blocks.
    """
    rule = context.config.home_presence
    states = context.normalized.states_for("presence")
    if not states:
        return [], []

    by_entity: dict[str | None, list] = {}
    for state in states:
        by_entity.setdefault(state.entity_id, []).append(state)

    for entity_id in rule.entity_priority:
        if entity_id in by_entity:
            others = [key for key in by_entity if key and key != entity_id]
            return by_entity[entity_id], others

    # No configured preference: the entity that changed most often is the one
    # actually tracking, rather than one stuck on a single stale state.
    chosen = max(by_entity.items(), key=lambda item: (len(item[1]), item[0] or ""))
    others = [key for key in by_entity if key and key != chosen[0]]
    return chosen[1], others


def _presence_intervals(context: RuleContext) -> tuple[list[TimelineEvent], str | None]:
    rule = context.config.home_presence
    states, corroborating = _select_presence_entity(context)
    if not states:
        return [], None

    minimum = timedelta(minutes=rule.min_duration_minutes)
    events: list[TimelineEvent] = []
    kept: list = []

    for state in states:
        clipped = context.clip_to_day(state.start_time, state.end_time)
        if clipped is None:
            continue
        start, end, before, after = clipped
        if end - start < minimum:
            continue

        raw_state = state.state.lower()
        if raw_state in {value.lower() for value in rule.home_states}:
            label, category = "Home", "home"
        elif raw_state in {value.lower() for value in rule.away_states}:
            label, category = "Away", "away"
        else:
            label, category = "Presence unknown", "unknown"

        kept.append((start, end, category, state))
        events.append(
            TimelineEvent(
                id=f"presence_{category}_{int(start.timestamp())}",
                phenotype="presence",
                label=label,
                event_type="interval",
                start_time=start,
                end_time=end,
                value=state.state,
                source=state.source,
                entity_id=state.entity_id,
                device=state.device,
                measured_or_derived="derived",
                confidence=0.9,
                data_quality="high" if category != "unknown" else "unknown",
                category=f"presence_{category}",
                continues_before=before,
                continues_after=after,
                metadata={
                    "presenceState": state.state,
                    "durationMinutes": round((end - start).total_seconds() / 60, 1),
                    "fullStart": state.start_time.isoformat(),
                    "fullEnd": state.end_time.isoformat(),
                    "trackedBy": state.entity_id,
                    "otherPresenceEntities": corroborating,
                    "note": (
                        "Only home/away state is stored. No geographic coordinates are "
                        "read or displayed."
                        + (
                            f" {len(corroborating)} other presence entity/entities also "
                            "report this; one is drawn to avoid duplicate blocks."
                            if corroborating
                            else ""
                        )
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_PRESENCE,
                    version=rule.rule_version,
                    raw_record_ids=state.raw_record_ids,
                    entity_ids=([state.entity_id] if state.entity_id else []) + corroborating,
                    thresholds={
                        "home_states": rule.home_states,
                        "away_states": rule.away_states,
                        "min_duration_minutes": rule.min_duration_minutes,
                        "entity_priority": rule.entity_priority,
                    },
                    input_range=(state.start_time, state.end_time),
                ),
            )
        )

    events.extend(_transition_events(context, kept))
    return events, states[0].source


def _transition_events(context: RuleContext, intervals: list) -> list[TimelineEvent]:
    rule = context.config.home_presence
    events: list[TimelineEvent] = []
    for previous, current in zip(intervals, intervals[1:]):
        _p_start, p_end, previous_category, _p_state = previous
        c_start, _c_end, current_category, state = current
        if previous_category == current_category:
            continue
        if current_category == "away":
            label, category = "Left home", "left_home"
        elif current_category == "home":
            label, category = "Arrived home", "arrived_home"
        else:
            continue
        moment = c_start
        events.append(
            TimelineEvent(
                id=f"presence_{category}_{int(moment.timestamp())}",
                phenotype="presence",
                label=label,
                event_type="point",
                start_time=moment,
                source=state.source,
                entity_id=state.entity_id,
                device=state.device,
                measured_or_derived="derived",
                confidence=0.9,
                data_quality="high",
                category=category,
                metadata={
                    "previousState": previous_category,
                    "newState": current_category,
                    "note": "Transition detected between two presence intervals.",
                },
                provenance=build_provenance(
                    rule=RULE_TRANSITION,
                    version=rule.rule_version,
                    raw_record_ids=state.raw_record_ids,
                    entity_ids=[state.entity_id] if state.entity_id else [],
                    input_range=(p_end, c_start),
                    output_timestamp=moment,
                ),
            )
        )
    return events


def _motion_events(context: RuleContext) -> tuple[list[TimelineEvent], str | None]:
    states = [
        state for state in context.normalized.states_for("motion") if state.state == "on"
    ]
    if not states:
        return [], None

    events: list[TimelineEvent] = []
    for state in states:
        clipped = context.clip_to_day(state.start_time, state.end_time)
        if clipped is None:
            continue
        start, end, _before, _after = clipped
        room = (state.entity_id or "motion").split(".")[-1].replace("_motion", "")
        events.append(
            TimelineEvent(
                id=f"motion_{state.entity_id}_{int(start.timestamp())}",
                phenotype="presence",
                label=f"Motion — {room.replace('_', ' ')}",
                event_type="point",
                start_time=start,
                end_time=end,
                source=state.source,
                entity_id=state.entity_id,
                device=state.device,
                measured_or_derived="measured",
                confidence=1.0,
                data_quality="high",
                category="motion",
                metadata={
                    "room": room,
                    "durationSeconds": round((end - start).total_seconds()),
                    "note": "Binary motion sensor reported occupancy in this room.",
                },
                provenance=build_provenance(
                    rule=RULE_MOTION,
                    version="1.0.0",
                    raw_record_ids=state.raw_record_ids,
                    entity_ids=[state.entity_id] if state.entity_id else [],
                    input_range=(state.start_time, state.end_time),
                ),
            )
        )
    return events, states[0].source


def _door_events(context: RuleContext) -> tuple[list[TimelineEvent], str | None]:
    """Door and window openings — occupancy evidence, not motion."""
    states = [state for state in context.normalized.states_for("door") if state.state == "on"]
    if not states:
        return [], None

    events: list[TimelineEvent] = []
    for state in states:
        clipped = context.clip_to_day(state.start_time, state.end_time)
        if clipped is None:
            continue
        start, end, _before, _after = clipped
        name = (state.device or state.entity_id or "door").replace("_", " ")
        device_class = state.attributes.get("device_class") or "door"
        events.append(
            TimelineEvent(
                id=f"door_{state.entity_id}_{int(start.timestamp())}",
                phenotype="presence",
                label=f"{'Window' if device_class == 'window' else 'Door'} open — {name}",
                event_type="point",
                start_time=start,
                end_time=end,
                source=state.source,
                entity_id=state.entity_id,
                device=state.device,
                measured_or_derived="measured",
                confidence=1.0,
                data_quality="high",
                category="door",
                metadata={
                    "deviceClass": device_class,
                    "durationSeconds": round((end - start).total_seconds()),
                    "note": "A contact sensor reported this opening closed again.",
                },
                provenance=build_provenance(
                    rule=RULE_DOOR,
                    version="1.0.0",
                    raw_record_ids=state.raw_record_ids,
                    entity_ids=[state.entity_id] if state.entity_id else [],
                    input_range=(state.start_time, state.end_time),
                ),
            )
        )
    return events, states[0].source


def _device_use_events(context: RuleContext) -> tuple[list[TimelineEvent], str | None]:
    """Screen-on stretches: evidence the user was awake and interacting."""
    rule = context.config.device_use
    states = [
        state for state in context.normalized.states_for("device_use") if state.state == "on"
    ]
    if not states:
        return [], None

    merge_within = timedelta(minutes=rule.merge_within_minutes)
    minimum = timedelta(minutes=rule.min_session_minutes)

    merged: list[list] = []
    for state in sorted(states, key=lambda item: item.start_time):
        if merged and state.start_time - merged[-1][-1].end_time <= merge_within:
            merged[-1].append(state)
        else:
            merged.append([state])

    events: list[TimelineEvent] = []
    for index, group in enumerate(merged):
        clipped = context.clip_to_day(group[0].start_time, group[-1].end_time)
        if clipped is None:
            continue
        start, end, before, after = clipped
        if end - start < minimum:
            continue
        name = (group[0].device or group[0].entity_id or "device").replace("_", " ")
        events.append(
            TimelineEvent(
                id=f"device_use_{index}_{int(start.timestamp())}",
                phenotype="presence",
                label="Device in use",
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round((end - start).total_seconds() / 60, 1),
                unit="min",
                source=group[0].source,
                entity_id=group[0].entity_id,
                device=group[0].device,
                measured_or_derived="derived",
                confidence=0.7,
                data_quality="medium",
                category="device_use",
                continues_before=before,
                continues_after=after,
                metadata={
                    "device": name,
                    "durationMinutes": round((end - start).total_seconds() / 60, 1),
                    "sessionCount": len(group),
                    "note": (
                        "The device reported an interactive screen. Someone was using "
                        "it; which person is not recorded."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_DEVICE_USE,
                    version=rule.rule_version,
                    raw_record_ids=[
                        record_id for state in group for record_id in state.raw_record_ids
                    ],
                    entity_ids=[group[0].entity_id] if group[0].entity_id else [],
                    thresholds={
                        "merge_within_minutes": rule.merge_within_minutes,
                        "min_session_minutes": rule.min_session_minutes,
                    },
                    input_range=(group[0].start_time, group[-1].end_time),
                ),
            )
        )
    return events, states[0].source


def _inactivity_events(context: RuleContext) -> list[TimelineEvent]:
    """Long stretches at home with no motion reported anywhere."""
    rule = context.config.sustained_inactivity
    motion = sorted(
        (
            state
            for state in context.normalized.states_for("motion")
            if state.state == "on" and context.window.contains(state.start_time)
        ),
        key=lambda state: state.start_time,
    )
    if not motion:
        return []

    home_windows = [
        (state.start_time, state.end_time)
        for state in context.normalized.states_for("presence")
        if state.state.lower() in {value.lower() for value in context.config.home_presence.home_states}
    ]
    if not home_windows:
        return []

    minimum = timedelta(minutes=rule.min_duration_minutes)
    entity_ids = sorted({state.entity_id for state in motion if state.entity_id})
    events: list[TimelineEvent] = []

    boundaries = [context.window.start] + [state.end_time for state in motion]
    starts = [state.start_time for state in motion] + [context.window.end]

    for index, (gap_start, gap_end) in enumerate(zip(boundaries, starts)):
        if gap_end - gap_start < minimum:
            continue
        overlap = _overlap_with_windows(gap_start, gap_end, home_windows)
        if overlap is None or overlap[1] - overlap[0] < minimum:
            continue
        start, end = overlap
        events.append(
            TimelineEvent(
                id=f"inactivity_{index}_{int(start.timestamp())}",
                phenotype="presence",
                label="Sustained inactivity at home",
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round((end - start).total_seconds() / 60, 1),
                unit="min",
                source=motion[0].source,
                measured_or_derived="derived",
                confidence=0.6,
                data_quality="medium",
                category="inactivity",
                metadata={
                    "durationMinutes": round((end - start).total_seconds() / 60, 1),
                    "monitoredEntities": entity_ids,
                    "note": (
                        "No motion sensor reported activity while presence was 'home'. "
                        "Sleep and being in an unmonitored room both look like this."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_INACTIVITY,
                    version=rule.rule_version,
                    entity_ids=entity_ids,
                    thresholds={"min_duration_minutes": rule.min_duration_minutes},
                    input_range=(start, end),
                    assumptions=[
                        "Absence of motion is treated as absence of movement in monitored "
                        "rooms only."
                    ],
                ),
            )
        )
    return events


def _overlap_with_windows(start, end, windows):
    best = None
    for window_start, window_end in windows:
        low = max(start, window_start)
        high = min(end, window_end)
        if high > low and (best is None or (high - low) > (best[1] - best[0])):
            best = (low, high)
    return best
