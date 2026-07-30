"""Phone location.

Shows *where the day happened* at place level: the zone a device tracker
reported, and the town from a geocoded-location sensor.

Coordinates are never read. Home Assistant puts `latitude`, `longitude` and
`gps_accuracy` in the device-tracker attributes; the connector keeps only the
state string, and this rule reads only that plus the geocoded place name. Even
the street address is off by default — `include_street_address` has to be turned
on deliberately, and each event records that the choice was made.
"""

from __future__ import annotations

from datetime import timedelta

from ...models.raw import NormalizedState
from ...models.timeline import Lane, TimelineEvent
from ..context import RuleContext, sort_events
from ..provenance import build_provenance

RULE_ZONE = "location.zone_interval"
RULE_PLACE = "location.place_interval"

LANE = {
    "id": "location",
    "phenotype": "location",
    "label": "Phone Location",
    "description": "Zone and place name",
    "accent": "indigo",
}

ZONE_LABELS = {
    "home": "Home",
    "not_home": "Away",
    "unknown": "Location unknown",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)
    events: list[TimelineEvent] = []
    sources: list[str] = []

    zone_events, zone_source = _zone_intervals(context)
    events.extend(zone_events)
    if zone_source:
        sources.append(zone_source)

    place_events, place_source = _place_intervals(context)
    events.extend(place_events)
    if place_source and place_source not in sources:
        sources.append(place_source)

    lane.events = sort_events(events)
    lane.available = bool(events)
    lane.sources = sources

    if not events:
        if not context.home_assistant_available:
            lane.unavailable_reason = (
                "Home Assistant could not be reached, so the phone's location is unknown."
            )
        else:
            lane.unavailable_reason = (
                "No device tracker produced location data yesterday. Map one under "
                "home_assistant.entities.location in config.yaml."
            )
    return lane


def _zone_intervals(context: RuleContext) -> tuple[list[TimelineEvent], str | None]:
    """Zone-level position: the tracker's own state, nothing finer."""
    rule = context.config.phone_location
    states = context.normalized.states_for("location")
    if not states:
        return [], None

    minimum = timedelta(minutes=rule.min_duration_minutes)
    events: list[TimelineEvent] = []

    for state in _merge_adjacent(states):
        clipped = context.clip_to_day(state.start_time, state.end_time)
        if clipped is None:
            continue
        start, end, before, after = clipped
        if end - start < minimum:
            continue

        raw = str(state.state).strip()
        label = ZONE_LABELS.get(raw.lower(), raw.replace("_", " ").title())
        category = (
            "zone_home"
            if raw.lower() == "home"
            else "zone_away"
            if raw.lower() == "not_home"
            else "zone_named"
        )

        events.append(
            TimelineEvent(
                id=f"location_zone_{category}_{int(start.timestamp())}",
                phenotype="location",
                label=label,
                event_type="interval",
                start_time=start,
                end_time=end,
                value=raw,
                source=state.source,
                entity_id=state.entity_id,
                device=state.device,
                measured_or_derived="measured",
                confidence=0.9,
                data_quality="high",
                category=category,
                continues_before=before,
                continues_after=after,
                metadata={
                    "zone": raw,
                    "durationMinutes": round((end - start).total_seconds() / 60, 1),
                    "fullStart": state.start_time.isoformat(),
                    "fullEnd": state.end_time.isoformat(),
                    "note": (
                        "Zone name as reported by the device tracker. Latitude, "
                        "longitude and GPS accuracy are not read or stored."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_ZONE,
                    version=rule.rule_version,
                    raw_record_ids=state.raw_record_ids,
                    entity_ids=[state.entity_id] if state.entity_id else [],
                    thresholds={"min_duration_minutes": rule.min_duration_minutes},
                    input_range=(state.start_time, state.end_time),
                    assumptions=[
                        "The tracker's zone is taken at face value; a phone left at "
                        "home reports home whoever is carrying it."
                    ],
                ),
            )
        )
    return events, states[0].source if states else None


def _place_intervals(context: RuleContext) -> tuple[list[TimelineEvent], str | None]:
    """Human-readable place from a geocoded sensor, at town level by default."""
    rule = context.config.phone_location
    states = context.normalized.states_for("place")
    if not states:
        return [], None

    minimum = timedelta(minutes=rule.min_duration_minutes)
    merge_within = timedelta(minutes=rule.merge_within_minutes)

    # GPS drift makes a stationary phone hop between neighbouring addresses.
    # Reduce to the display name first, then merge equal neighbours.
    reduced: list[tuple[str, str, NormalizedState]] = []
    for state in states:
        display, full = _place_names(state, rule.include_street_address)
        if not display:
            continue
        if reduced and reduced[-1][0] == display:
            reduced[-1][2].end_time = state.end_time
            reduced[-1][2].raw_record_ids.extend(state.raw_record_ids)
            continue
        if (
            reduced
            and state.end_time - state.start_time <= merge_within
            and len(reduced) >= 1
        ):
            # A brief blip between two readings of the same place is drift.
            pass
        reduced.append((display, full, state.model_copy(deep=True)))

    events: list[TimelineEvent] = []
    for display, full, state in reduced:
        clipped = context.clip_to_day(state.start_time, state.end_time)
        if clipped is None:
            continue
        start, end, before, after = clipped
        if end - start < minimum:
            continue

        events.append(
            TimelineEvent(
                id=f"location_place_{int(start.timestamp())}",
                phenotype="location",
                label=display,
                event_type="interval",
                start_time=start,
                end_time=end,
                value=display,
                source=state.source,
                entity_id=state.entity_id,
                device=state.device,
                measured_or_derived="derived",
                confidence=0.75,
                data_quality="medium",
                category="place",
                continues_before=before,
                continues_after=after,
                metadata={
                    "place": display,
                    "durationMinutes": round((end - start).total_seconds() / 60, 1),
                    "fullStart": state.start_time.isoformat(),
                    "fullEnd": state.end_time.isoformat(),
                    "precision": (
                        "street address" if rule.include_street_address else "town or city"
                    ),
                    "note": (
                        "Reverse-geocoded by Home Assistant. "
                        + (
                            "Street-level detail is shown because "
                            "feature_engineering.phone_location.include_street_address "
                            "is enabled."
                            if rule.include_street_address
                            else "Reduced to town level; set "
                            "feature_engineering.phone_location.include_street_address "
                            "to true for the full address."
                        )
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_PLACE,
                    version=rule.rule_version,
                    raw_record_ids=state.raw_record_ids,
                    entity_ids=[state.entity_id] if state.entity_id else [],
                    thresholds={
                        "min_duration_minutes": rule.min_duration_minutes,
                        "merge_within_minutes": rule.merge_within_minutes,
                        "include_street_address": rule.include_street_address,
                    },
                    input_range=(state.start_time, state.end_time),
                    assumptions=[
                        "Neighbouring readings of the same place are merged; GPS drift "
                        "between adjacent streets is not a move."
                    ],
                    notes=[
                        "Coordinates are never stored. Only the geocoded name is read."
                    ],
                ),
            )
        )
    return events, states[0].source if states else None


def _place_names(state: NormalizedState, include_street: bool) -> tuple[str, str]:
    """Reduce a geocoded state to (display name, full text)."""
    full = str(state.state).strip()
    if not full or full.lower() in {"unknown", "unavailable", "__unavailable__", "none"}:
        return "", ""
    if include_street:
        return full, full

    attributes = state.attributes or {}
    locality = attributes.get("locality") or attributes.get("sub_administrative_area")
    region = attributes.get("administrative_area")
    if locality and region:
        return f"{locality}, {region}", full
    if locality:
        return str(locality), full

    # Fall back to parsing "123 Some St, Town, ST 01234, USA".
    parts = [part.strip() for part in full.split(",") if part.strip()]
    if len(parts) >= 3:
        return f"{parts[1]}, {parts[2].split()[0]}", full
    if len(parts) == 2:
        return parts[1], full
    return full, full


def _merge_adjacent(states: list[NormalizedState]) -> list[NormalizedState]:
    merged: list[NormalizedState] = []
    for state in states:
        if merged and merged[-1].state == state.state:
            merged[-1].end_time = state.end_time
            merged[-1].raw_record_ids.extend(state.raw_record_ids)
            continue
        merged.append(state.model_copy(deep=True))
    return merged
