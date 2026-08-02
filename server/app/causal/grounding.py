"""Anchor the causal graph to the hours a day actually recorded.

The abstract DAG in `dag.py` answers *what could cause what*. This module asks a
narrower and much more checkable question: on the day being viewed, when was
each of those variables actually happening? A node appears only for a time the
data says the event or state was active, so the drawing cannot imply anything
the day did not record.

The arrows are still assumptions — grounding does not test them. What it adds is
one piece of discipline: an assumed effect is only drawn when it is *ordered
correctly in time*, linking each cause to the first occurrence of its effect
that does not precede it. Causes that the day never recorded, and effects that
never followed, are reported rather than quietly dropped, because an arrow that
silently fails to draw would read as evidence of absence.

Two things deliberately do **not** become arrows:

* **Whole-day states** (the town you were in, an all-day away period). They are
  true at every hour, so there is no single hour for an arrow to attach to.
* **Continuously sampled signals** with no discrete events (a heart-rate trace).
  Picking a moment out of a continuous line would be inventing salience.

Both still get a row and a band, because they *were* active — they just cannot
carry a timed arrow honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..models.timeline import DayTimeline, Lane, TimelineEvent
from .dag import Dag
from .knowledge import variable

#: An effect within this long of its cause is drawn as an immediate link; past
#: it, as a delayed one. Two hours is a presentational threshold, not a claim
#: about physiology — the exact lag is always shown on the link itself.
IMMEDIATE_MAX_MINUTES = 120.0

#: An occurrence covering at least this much of the day is a background state
#: rather than a moment, and gets a band instead of a node.
SPAN_FRACTION = 0.9

#: More points than this and a series is a continuous trace, not a reading.
MAX_READING_POINTS = 3

#: Per variable, so one busy lane cannot bury the graph.
MAX_OCCURRENCES = 6


@dataclass(frozen=True)
class Grounding:
    """How to find one variable's occurrences in a processed day."""

    lane: str
    #: Category prefixes to include. Empty means every event in the lane.
    categories: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    #: Restrict to events starting within this local hour window, [start, end).
    hours: tuple[int, int] | None = None
    #: Require this metadata key, and use it as the occurrence's value.
    metric: str | None = None
    #: Only accept intervals whose start is real rather than clipped at midnight.
    true_start_only: bool = False
    #: Collapse the interval to its start instant.
    as_point: bool = False


#: How each variable in the knowledge base is recognised on the timeline.
#: A variable absent from this map has no timeline representation at all, which
#: is the correct answer for the unmeasured ones.
GROUNDINGS: dict[str, tuple[Grounding, ...]] = {
    # "Recorded workout sessions and sustained activity" — a long walk at pace
    # is sustained activity even when no wearable filed it as a workout.
    "exercise": (Grounding(lane="activity"),),
    # Step periods carry the step total as their value.
    "step_count": (Grounding(lane="activity", categories=("walking_period",)),),
    "sleep_duration": (Grounding(lane="sleep", categories=("main_sleep", "nap")),),
    # `sleep_onset` and `sleep_efficiency` are deliberately ungrounded. The
    # Sleep Duration row reports how long, and a row named for one quantity
    # standing in for three would let a claim about bedtime be read off a
    # drawing that never measured it. Both remain in the knowledge base as
    # unmeasured variables, so the arrows into them still say what they assume.
    "resting_heart_rate": (Grounding(lane="heart_rate", categories=("resting",)),),
    "hrv": (Grounding(lane="hrv"),),
    "readiness": (Grounding(lane="readiness"),),
    "light_evening": (
        Grounding(lane="environment", categories=("light_",), hours=(17, 24)),
    ),
    "light_morning": (
        Grounding(lane="environment", categories=("light_",), hours=(4, 11)),
    ),
    "room_temperature": (Grounding(lane="environment", categories=("temperature",)),),
    "skin_temperature": (Grounding(lane="temperature"),),
    "device_use": (Grounding(lane="phone_use", categories=("phone_on",)),),
    # The screen-on stretches, not the individual application spells inside
    # them — the same choice the computer lane makes one line down.
    "tiktok": (Grounding(lane="tiktok", categories=("tiktok",)),),
    # The on-stretches, not the individual programmes inside them — the same
    # whole-not-part choice the phone makes two lines up.
    "tv_use": (Grounding(lane="tv", categories=("tv_on",)),),
    # Stretches at the machine, not the individual application spells: one row
    # per browser tab would bury the graph and says nothing a session does not.
    "computer_use": (Grounding(lane="computer_use", categories=("at_computer",)),),
    "time_away": (Grounding(lane="presence", categories=("presence_away",)),),
    "location": (Grounding(lane="location", categories=("place",)),),
}

#: Known from the calendar, true for every hour of the day.
WHOLE_DAY_CONSTANTS = {"day_of_week"}


@dataclass
class Occurrence:
    """One time-anchored appearance of a variable."""

    id: str
    variable: str
    label: str
    detail: str
    start: datetime
    end: datetime | None
    kind: str  # "event" | "reading" | "span" | "constant"
    value: float | str | None = None
    unit: str | None = None
    event_id: str | None = None

    @property
    def anchor(self) -> datetime:
        """When an outgoing effect may begin: once the cause is under way."""
        return self.start

    @property
    def finish(self) -> datetime:
        """When the cause is complete, used to measure how delayed an effect is."""
        return self.end or self.start

    @property
    def placeable(self) -> bool:
        """Whether an arrow can honestly attach to a single hour here."""
        return self.kind in {"event", "reading"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "variable": self.variable,
            "label": self.label,
            "detail": self.detail,
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "kind": self.kind,
            "value": self.value,
            "unit": self.unit,
            "eventId": self.event_id,
        }


@dataclass
class Link:
    """A hypothesised edge, placed between two things the day recorded."""

    source: str
    target: str
    source_variable: str
    target_variable: str
    kind: str  # "immediate" | "delayed"
    lag_minutes: float
    strength: str
    rationale: str
    on_path: bool
    origin: str = "knowledge_base"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "sourceVariable": self.source_variable,
            "targetVariable": self.target_variable,
            "kind": self.kind,
            "lagMinutes": round(self.lag_minutes, 1),
            "strength": self.strength,
            "rationale": self.rationale,
            "onPath": self.on_path,
            "origin": self.origin,
        }


@dataclass
class Row:
    """One swimlane: a variable, and what the day has to say about it."""

    variable: str
    label: str
    role: str
    measured: bool
    status: str  # "events" | "continuous" | "whole_day" | "absent" | "unmeasured"
    note: str
    lane: str | None = None
    unit: str | None = None
    band_start: datetime | None = None
    band_end: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable": self.variable,
            "label": self.label,
            "role": self.role,
            "measured": self.measured,
            "status": self.status,
            "note": self.note,
            "lane": self.lane,
            "unit": self.unit,
            "bandStart": self.band_start.isoformat() if self.band_start else None,
            "bandEnd": self.band_end.isoformat() if self.band_end else None,
        }


@dataclass
class GroundedDag:
    day_start: datetime
    day_end: datetime
    local_timezone: str
    rows: list[Row] = field(default_factory=list)
    occurrences: list[Occurrence] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    unplaced: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dayStart": self.day_start.isoformat(),
            "dayEnd": self.day_end.isoformat(),
            "localTimezone": self.local_timezone,
            "rows": [row.to_dict() for row in self.rows],
            "occurrences": [item.to_dict() for item in self.occurrences],
            "links": [link.to_dict() for link in self.links],
            "unplacedEdges": self.unplaced,
        }


def _matches(event: TimelineEvent, rule: Grounding, timeline: DayTimeline) -> bool:
    category = event.category or ""
    if rule.categories and not any(category.startswith(prefix) for prefix in rule.categories):
        return False
    if any(category.startswith(prefix) for prefix in rule.exclude):
        return False
    if rule.metric and rule.metric not in event.metadata:
        return False
    if rule.true_start_only and event.continues_before:
        return False
    if rule.hours:
        # Convert explicitly rather than trusting the stored offset: "evening"
        # has to mean the user's evening, whatever tzinfo survived storage.
        try:
            local = event.start_time.astimezone(ZoneInfo(timeline.local_timezone))
        except Exception:  # pragma: no cover - unknown zone name
            local = event.start_time
        start, end = rule.hours
        if not start <= local.hour < end:
            return False
    return True


def _describe(event: TimelineEvent, rule: Grounding, unit: str | None) -> str:
    """A short, factual caption. Never an interpretation of the value.

    A variable collapsed to an instant gets no caption: its own clock label
    already says everything the day recorded, and repeating the parent event's
    duration there would describe a different quantity.
    """
    if rule.as_point:
        return ""

    bits: list[str] = []
    if rule.metric is not None:
        value = event.metadata.get(rule.metric)
        if isinstance(value, float) and unit == "%" and 0.0 <= value <= 1.0:
            bits.append(f"{value * 100:.1f}%")  # stored as a ratio, read as a percentage
        elif value is not None:
            bits.append(f"{value}{unit or ''}")
    duration = event.metadata.get("durationMinutes")
    duplicate_of_duration = (
        event.unit == "min"
        and isinstance(event.value, (int, float))
        and isinstance(duration, (int, float))
        and abs(event.value - duration) < 1
    )
    if rule.metric is None and event.value is not None and not duplicate_of_duration:
        suffix = f" {event.unit}" if event.unit else ""
        value = round(event.value, 1) if isinstance(event.value, float) else event.value
        bits.append(f"{value}{suffix}")

    if isinstance(duration, (int, float)) and duration:
        hours, minutes = divmod(int(round(duration)), 60)
        if not hours:
            bits.append(f"{minutes} min")
        else:
            bits.append(f"{hours} h {minutes} min" if minutes else f"{hours} h")
    return " · ".join(str(bit) for bit in bits)


def _occurrences_for(
    variable_id: str, rules: tuple[Grounding, ...], timeline: DayTimeline
) -> tuple[list[Occurrence], str, str]:
    """Occurrences for one variable, plus a row status and an explanation."""
    lanes = {lane.id: lane for lane in timeline.lanes}
    day_span = (timeline.day_end - timeline.day_start).total_seconds()
    found: list[Occurrence] = []
    saw_lane = False
    dense_series: Lane | None = None

    for rule in rules:
        lane = lanes.get(rule.lane)
        if lane is None or not lane.available:
            continue
        saw_lane = True

        for event in lane.events:
            if not _matches(event, rule, timeline):
                continue
            end = None if rule.as_point else event.end_time
            covered = ((end or event.start_time) - event.start_time).total_seconds()
            kind = "span" if day_span and covered / day_span >= SPAN_FRACTION else "event"
            found.append(
                Occurrence(
                    id=f"{variable_id}::{event.id}",
                    variable=variable_id,
                    label=event.label,
                    detail=_describe(event, rule, variable(variable_id).unit),
                    start=event.start_time,
                    end=end,
                    kind=kind,
                    value=event.metadata.get(rule.metric) if rule.metric else event.value,
                    unit=event.unit,
                    event_id=event.id,
                )
            )

        # A source that publishes one value a day (readiness, HRV) exposes it as
        # a one-point series rather than an event. That is still a moment.
        for series in lane.series:
            if len(series.points) == 0 or rule.categories or rule.metric:
                continue
            if len(series.points) > MAX_READING_POINTS:
                dense_series = lane
                continue
            for point in series.points:
                found.append(
                    Occurrence(
                        id=f"{variable_id}::{series.id}@{point.timestamp.isoformat()}",
                        variable=variable_id,
                        label=series.label,
                        detail=f"{round(point.value, 1)} {series.unit}".strip(),
                        start=point.timestamp,
                        end=None,
                        kind="reading",
                        value=point.value,
                        unit=series.unit,
                    )
                )

    found.sort(key=lambda item: item.start)
    if len(found) > MAX_OCCURRENCES:
        # Keep the longest, which are the ones the day actually turned on.
        by_length = sorted(
            found,
            key=lambda item: (item.finish - item.start, item.start),
            reverse=True,
        )
        found = sorted(by_length[:MAX_OCCURRENCES], key=lambda item: item.start)

    if found:
        if all(item.kind == "span" for item in found):
            return found, "whole_day", "Recorded as a state that held all day."
        return found, "events", ""
    if dense_series is not None:
        return (
            [],
            "continuous",
            "Sampled continuously, with no discrete events to attach an arrow to.",
        )
    if saw_lane:
        return [], "absent", "The lane reported data, but nothing matching this variable."
    return [], "absent", "Not recorded on this day."


def ground(dag: Dag, timeline: DayTimeline) -> GroundedDag:
    """Place `dag` on `timeline`'s clock. Never estimates, only orders."""
    grounded = GroundedDag(
        day_start=timeline.day_start,
        day_end=timeline.day_end,
        local_timezone=timeline.local_timezone,
    )
    lane_labels = {lane.id: lane for lane in timeline.lanes}
    by_variable: dict[str, list[Occurrence]] = {}

    # Order the swimlanes cause-first, so the arrows cascade downwards.
    ordered = sorted(dag.nodes, key=lambda node: (node.layer, node.label))

    for node in ordered:
        if node.id in WHOLE_DAY_CONSTANTS:
            occurrence = Occurrence(
                id=f"{node.id}::day",
                variable=node.id,
                label=timeline.day_start.strftime("%A"),
                detail="Known from the calendar",
                start=timeline.day_start,
                end=timeline.day_end,
                kind="constant",
            )
            by_variable[node.id] = [occurrence]
            grounded.occurrences.append(occurrence)
            grounded.rows.append(
                Row(
                    variable=node.id,
                    label=node.label,
                    role=node.role,
                    measured=True,
                    status="whole_day",
                    note="True for every hour of the day.",
                    band_start=timeline.day_start,
                    band_end=timeline.day_end,
                )
            )
            continue

        if not node.measured:
            by_variable[node.id] = []
            grounded.rows.append(
                Row(
                    variable=node.id,
                    label=node.label,
                    role=node.role,
                    measured=False,
                    status="unmeasured",
                    note="No connected source records this, so it has no place on the clock.",
                )
            )
            continue

        rules = GROUNDINGS.get(node.id, ())
        occurrences, status, note = _occurrences_for(node.id, rules, timeline)
        by_variable[node.id] = occurrences
        grounded.occurrences.extend(occurrences)

        band_start = band_end = None
        if status == "whole_day" and occurrences:
            band_start = min(item.start for item in occurrences)
            band_end = max(item.finish for item in occurrences)
        elif status == "continuous":
            band_start, band_end = timeline.day_start, timeline.day_end

        lane = lane_labels.get(node.lane or "")
        grounded.rows.append(
            Row(
                variable=node.id,
                label=node.label,
                role=node.role,
                measured=True,
                status=status,
                note=note,
                lane=node.lane,
                unit=node.unit or (lane.units[0] if lane and lane.units else None),
                band_start=band_start,
                band_end=band_end,
            )
        )

    _link(dag, grounded, by_variable)
    return grounded


def _link(dag: Dag, grounded: GroundedDag, by_variable: dict[str, list[Occurrence]]) -> None:
    """Connect each cause to the first effect that does not precede it."""
    for edge in dag.edges:
        sources = [item for item in by_variable.get(edge.source, []) if item.placeable]
        targets = [item for item in by_variable.get(edge.target, []) if item.placeable]

        reason = _unplaceable_reason(edge.source, edge.target, by_variable, sources, targets)
        if reason:
            grounded.unplaced.append(
                {
                    "source": edge.source,
                    "target": edge.target,
                    "sourceLabel": variable(edge.source).label,
                    "targetLabel": variable(edge.target).label,
                    "reason": reason,
                }
            )
            continue

        linked = False
        for source in sources:
            # An effect cannot start before its cause does.
            following = [item for item in targets if item.start >= source.anchor]
            if not following:
                continue
            target = min(following, key=lambda item: item.start)
            lag = max(0.0, (target.start - source.finish).total_seconds() / 60.0)
            grounded.links.append(
                Link(
                    source=source.id,
                    target=target.id,
                    source_variable=edge.source,
                    target_variable=edge.target,
                    kind="immediate" if lag <= IMMEDIATE_MAX_MINUTES else "delayed",
                    lag_minutes=lag,
                    strength=edge.strength,
                    rationale=edge.rationale,
                    on_path=edge.on_path,
                    origin=edge.origin,
                )
            )
            linked = True

        if not linked:
            grounded.unplaced.append(
                {
                    "source": edge.source,
                    "target": edge.target,
                    "sourceLabel": variable(edge.source).label,
                    "targetLabel": variable(edge.target).label,
                    "reason": (
                        f"{variable(edge.target).label} was only recorded before "
                        f"{variable(edge.source).label} on this day, so no arrow "
                        "would point forwards in time."
                    ),
                }
            )


def _unplaceable_reason(
    source: str,
    target: str,
    by_variable: dict[str, list[Occurrence]],
    sources: list[Occurrence],
    targets: list[Occurrence],
) -> str | None:
    """Why an assumed edge could not be drawn, in the user's terms."""
    for node, placeable in ((source, sources), (target, targets)):
        if placeable:
            continue
        info = variable(node)
        if not info.measured:
            return f"{info.label} is not measured by any connected source."
        occurrences = by_variable.get(node, [])
        if occurrences and all(item.kind in {"span", "constant"} for item in occurrences):
            return (
                f"{info.label} held all day, so there is no single hour for an "
                "arrow to attach to."
            )
        return f"{info.label} was not recorded on this day."
    return None
