"""The television, from Home Assistant.

Two tiers, the same shape the phone and computer rows have:

* **TV on** — stretches with the set powered on. Brief gaps are bridged, since
  switching off to answer the door is not the end of the evening.
* **Playing** — what was on, for spells long enough to name.

The two tiers make different claims and the row is careful not to blur them.
The band underneath says the television was *on*, which a paused episode, a
menu and a screensaver all satisfy equally. Only the spells drawn inside it say
something was playing, and only for as long as a title sensor named it.

The title tier needs the band to be truthful, for the reason set out in
`spells.py`: a media-title sensor holds the last thing it saw after playback
stops, so the run following the last episode of the night reaches to whenever
the set is next switched on. Every run is intersected with the on-windows
before anything is drawn, and with no `tv_use` sensor the tier is withheld and
the reason said out loud rather than drawing a dark living room as nine hours
of King of the Hill.

What this row does not do is judge what was watched. No title is called
educational or a binge, and no total is compared against a recommendation —
the same restraint the phone and computer rows keep.
"""

from __future__ import annotations

from datetime import timedelta

from ...models.raw import NormalizedState
from ...models.timeline import Lane, TimelineEvent
from ..context import RuleContext, sort_events
from ..provenance import build_provenance
from .spells import clipped_spells, on_windows, value_at

RULE_SESSION = "tv.on_session"
RULE_PROGRAMME = "tv.programme"

STREAM_ON = "tv_use"
STREAM_APP = "tv_app"
STREAM_TITLE = "tv_title"

LANE = {
    "id": "tv",
    "phenotype": "tv",
    "label": "TV",
    "description": "When the TV was on, and what was playing",
    "accent": "purple",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)

    # Whether the sensor *reported* and whether it reported *on* are two
    # different questions, and only the first one is about the configuration. A
    # set that was off all evening reported all evening; answering that with
    # "add a tv_use sensor" would send someone to fix what is already working.
    reported = context.normalized.states_for(STREAM_ON)
    on_states = [state for state in reported if state.state == "on"]
    titles = context.normalized.states_for(STREAM_TITLE)
    apps = context.normalized.states_for(STREAM_APP)

    if not reported and not titles and not apps:
        lane.unavailable_reason = _nothing_reason(context)
        return lane

    events: list[TimelineEvent] = []
    sources: list[str] = []

    sessions, session_source = _sessions(context, on_states)
    events.extend(sessions)
    if session_source:
        sources.append(session_source)

    programmes, programme_source = _programmes(context, titles, apps, on_states)
    events.extend(programmes)
    if programme_source and programme_source not in sources:
        sources.append(programme_source)

    # Warned before the availability check, not after. The case where this
    # matters most is the one where the row ends up empty, and a warning that
    # only fired when something was drawn would stay silent exactly then.
    blind = bool(titles or apps) and not reported
    if blind:
        context.warnings.append(
            "Home Assistant reported what the television was showing but not whether "
            "it was on, so nothing is drawn for it. A media-title sensor holds its "
            "last value after playback stops, and drawing it unclipped would count a "
            "dark living room as hours of whatever finished last."
        )
    elif sessions and not titles and not apps:
        # An on-band with no programmes on it reads as "nothing was playing",
        # which is a claim about the evening. This one is about the recorder.
        context.warnings.append(
            "The television was on, but no sensor recorded what was playing, so the "
            "row shows when the set was on and nothing about what was on it. Add a "
            "media-title sensor under home_assistant.entities.tv_title in config.yaml "
            "— and note that Home Assistant's recorder is an allowlist, so a sensor "
            "that exists still records nothing until it is listed in "
            "configuration.yaml and Home Assistant is restarted."
        )

    lane.events = sort_events(events)
    lane.available = bool(events)
    lane.sources = sources
    lane.units = ["minutes"]

    if not lane.available:
        lane.unavailable_reason = _empty_reason(context, on_states, blind)

    return lane


def _nothing_reason(context: RuleContext) -> str:
    if not context.home_assistant_available:
        return "Home Assistant could not be reached, so television use is unknown."
    # Two causes, and the row cannot tell them apart from here, so it does not
    # pretend to. Naming only the first would send someone to add configuration
    # they already have — which is the likelier case for a day that predates a
    # newly added sensor, and the likeliest of all for one that predates its
    # place on the recorder allowlist.
    return (
        f"No television entity reported anything on {context.window.iso_date}. Either "
        "no sensor is configured under home_assistant.entities.tv_use, or the one "
        "that is did not exist yet or was not being recorded that day — Home "
        "Assistant's recorder is an allowlist, and an entity stores nothing until it "
        "is named in configuration.yaml and Home Assistant is restarted."
    )


def _empty_reason(
    context: RuleContext, on_states: list[NormalizedState], blind: bool
) -> str:
    if blind:
        return (
            "Home Assistant reported what the television was showing but never "
            "whether it was on, and a programme cannot be told apart from a title "
            "left on screen after the set was switched off. Add a sensor that is on "
            "while the set is on under home_assistant.entities.tv_use in config.yaml."
        )
    if on_states:
        # It did report — just never for long enough. Saying "the TV was off"
        # would send someone to check a sensor that is working correctly.
        minimum = context.config.tv.min_session_minutes
        return (
            f"The television came on during {context.window.iso_date}, but no stretch "
            f"reached the {minimum:g} minutes a session needs "
            "(feature_engineering.tv.min_session_minutes)."
        )
    return f"The television was not reported on at any point on {context.window.iso_date}."


# --------------------------------------------------------------------------
# On-stretches
# --------------------------------------------------------------------------


def _sessions(
    context: RuleContext, states: list[NormalizedState]
) -> tuple[list[TimelineEvent], str | None]:
    if not states:
        return [], None

    rule = context.config.tv
    merge_within = timedelta(minutes=rule.merge_within_minutes)
    minimum = timedelta(minutes=rule.min_session_minutes)

    merged: list[list[NormalizedState]] = []
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

        minutes = (end - start).total_seconds() / 60
        events.append(
            TimelineEvent(
                id=f"tv_session_{index}_{int(start.timestamp())}",
                phenotype="tv",
                label=f"TV on · {_duration(minutes)}",
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round(minutes, 1),
                unit="min",
                source=group[0].source,
                entity_id=group[0].entity_id,
                device=group[0].device,
                measured_or_derived="derived",
                confidence=0.7,
                data_quality="medium",
                category="tv_on",
                continues_before=before,
                continues_after=after,
                metadata={
                    "durationMinutes": round(minutes, 1),
                    "fullStart": group[0].start_time.isoformat(),
                    "fullEnd": group[-1].end_time.isoformat(),
                    "switchOnCount": len(group),
                    "note": (
                        "The television was powered on, with gaps shorter than "
                        f"{rule.merge_within_minutes:.0f} minutes treated as part of "
                        "the same sitting. Powered on is not the same as watched: a "
                        "paused episode and a menu left open both count here. Who was "
                        "in the room is not recorded."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_SESSION,
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
                    assumptions=[
                        "A powered-on television was being watched by someone, which "
                        "a set left running in an empty room is not.",
                    ],
                ),
            )
        )
    return events, states[0].source


# --------------------------------------------------------------------------
# What was playing
# --------------------------------------------------------------------------


def _programmes(
    context: RuleContext,
    titles: list[NormalizedState],
    apps: list[NormalizedState],
    on_states: list[NormalizedState],
) -> tuple[list[TimelineEvent], str | None]:
    """Spells on one title, clipped to the on-windows.

    Titles are preferred over apps because they are the more specific claim.
    With only an app sensor configured the row still works, one band per app,
    and the event says which of the two it was built from rather than letting
    "Disney+" pass for the name of a programme.
    """
    rule = context.config.tv
    windows = on_windows(on_states)
    # A title sensor that existed but was unavailable all day is not a title
    # sensor for this day's purposes: preferring it on the strength of having
    # rows would withhold the app names that are sitting right there.
    named = [
        state for state in titles if state.state and not state.state.startswith("__")
    ]
    states = titles if named else apps
    naming = "title" if named else "app"
    if not states or not windows:
        return [], None
    minimum = timedelta(minutes=rule.min_programme_minutes)
    events: list[TimelineEvent] = []

    for value, span_start, span_end, record_ids, sample in clipped_spells(
        states, windows, timedelta(minutes=rule.programme_merge_within_minutes)
    ):
        if span_end - span_start < minimum:
            continue
        clipped = context.clip_to_day(span_start, span_end)
        if clipped is None:
            continue
        start, end, before, after = clipped

        # The app is read at the spell's start, not assumed to hold across it.
        app_state = value_at(apps, span_start) if naming == "title" else None
        app = app_state.state if app_state else None

        minutes = (end - start).total_seconds() / 60
        events.append(
            TimelineEvent(
                id=f"tv_programme_{int(start.timestamp())}",
                phenotype="tv",
                label=value,
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round(minutes, 1),
                unit="min",
                source=sample.source,
                entity_id=sample.entity_id,
                device=sample.device,
                measured_or_derived="derived",
                confidence=0.75,
                data_quality="medium",
                category="tv_playing",
                continues_before=before,
                continues_after=after,
                metadata={
                    "title": value if naming == "title" else None,
                    "app": app if naming == "title" else value,
                    "namedBy": naming,
                    "durationMinutes": round(minutes, 1),
                    "fullStart": span_start.isoformat(),
                    "fullEnd": span_end.isoformat(),
                    "note": (
                        "What the television reported showing, for as long as it was "
                        "also on. The sensor keeps reporting the last title after "
                        "playback stops, so the run was cut to the on-window."
                        + (
                            ""
                            if naming == "title"
                            else " No title sensor is configured, so this names the "
                            "app rather than the programme."
                        )
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_PROGRAMME,
                    version=rule.rule_version,
                    raw_record_ids=record_ids,
                    entity_ids=[sample.entity_id] if sample.entity_id else [],
                    thresholds={
                        "min_programme_minutes": rule.min_programme_minutes,
                        "programme_merge_within_minutes": (
                            rule.programme_merge_within_minutes
                        ),
                    },
                    input_range=(span_start, span_end),
                    assumptions=[
                        "What the media player reported is what was on screen, which "
                        "an episode paused on a title card is not.",
                        "Time in front of the television is not the same as attention "
                        "paid to it, and nothing here distinguishes the two.",
                    ],
                    notes=[
                        "Clipped to the on-signal: the title sensor reports the last "
                        "thing it saw indefinitely, including all night."
                    ],
                ),
            )
        )
    return events, states[0].source


def _duration(minutes: float) -> str:
    hours, rest = divmod(int(round(minutes)), 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    if hours:
        return f"{hours}h"
    return f"{rest}m"
