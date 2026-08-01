"""Phone use, from the Home Assistant companion app.

Two tiers, the same shape the Computer Use lane has:

* **Phone in use** — stretches where the screen was interactive. Short locks
  are bridged: putting the phone down for a moment is not ending a session.
* **Applications** — which app was in front, for runs long enough to name.

The second tier needs the first to be truthful. Android's "last used app"
sensor reports a change and then holds that value indefinitely, screen on or
off, so the run following the last app of the evening covers the whole night.
Every run is therefore intersected with the screen-on windows before anything
is drawn, and when no screen sensor reported, the tier is withheld and the
reason said out loud rather than drawing a phone that was face-down all night
as eight hours in one app.

Two things this rule does not do. It does not judge applications — no app is
labelled social, productive or a distraction, the same restraint the computer
lane keeps. And it does not treat a quiet phone as missing data: no series is
produced, so a day spent away from the phone lowers no coverage figure.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ...models.raw import NormalizedState
from ...models.timeline import Lane, TimelineEvent
from ..context import RuleContext, sort_events
from ..provenance import build_provenance

RULE_SESSION = "phone_use.screen_session"
RULE_APP = "phone_use.app_session"

STREAM_SCREEN = "device_use"
STREAM_APP = "app_usage"

LANE = {
    "id": "phone_use",
    "phenotype": "phone_use",
    "label": "Phone Use",
    "description": "Screen-on stretches, and what was open",
    "accent": "fuchsia",
}

#: Package name -> what to call it on screen. Presentation only: the package is
#: kept in the event metadata and in provenance, so nothing here can hide what
#: was actually recorded. Anything unlisted falls back to its last segment.
APP_NAMES = {
    "com.zhiliaoapp.musically": "TikTok",
    "com.ss.android.ugc.trill": "TikTok",
    "com.android.launcher3": "Home screen",
    "com.android.deskclock": "Clock",
    "com.android.settings": "Settings",
    "com.android.vending": "Play Store",
    "com.android.chrome": "Chrome",
    "com.google.android.dialer": "Phone",
    "com.google.android.apps.messaging": "Messages",
    "com.google.android.gm": "Gmail",
    "com.google.android.apps.maps": "Maps",
    "com.google.android.youtube": "YouTube",
    "com.google.android.apps.youtube.music": "YouTube Music",
    "com.google.android.networkstack.tethering": "Hotspot",
    "com.microsoft.office.outlook": "Outlook",
    "com.whatsapp": "WhatsApp",
    "com.linkedin.android": "LinkedIn",
    "com.instagram.android": "Instagram",
    "com.spotify.music": "Spotify",
    "com.reddit.frontpage": "Reddit",
    "com.netflix.mediaclient": "Netflix",
    "com.hulu.plus": "Hulu",
    "cz.mobilesoft.appblock": "AppBlock",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)

    screen = _screen_states(context)
    app_states = context.normalized.states_for(STREAM_APP)

    if not screen and not app_states:
        lane.unavailable_reason = _nothing_reason(context)
        return lane

    events: list[TimelineEvent] = []
    sources: list[str] = []

    sessions, session_source = _sessions(context, screen)
    events.extend(sessions)
    if session_source:
        sources.append(session_source)

    apps, app_source = _app_events(context, app_states, screen)
    events.extend(apps)
    if app_source and app_source not in sources:
        sources.append(app_source)

    # Said before the availability check, not after: the case where this
    # matters most is the one where the lane ends up empty, and a warning that
    # only fires when something was drawn would stay silent exactly then.
    blind = bool(app_states) and not screen
    if blind:
        context.warnings.append(
            "The phone reported which app was in front but not whether the screen "
            "was on, so application spells are not drawn. The sensor holds its last "
            "value while the phone is asleep, and drawing it unclipped would count "
            "a night face-down as time in an app."
        )

    lane.events = sort_events(events)
    lane.available = bool(events)
    lane.sources = sources
    lane.units = ["minutes"]

    if not lane.available:
        if blind:
            lane.unavailable_reason = (
                "The phone reported which app was in front but never whether the "
                "screen was on, and an app spell cannot be told apart from a phone "
                "left face-down with that app open. Add the companion app's "
                "interactive sensor under home_assistant.entities.device_use in "
                "config.yaml."
            )
        elif screen:
            # It did report — just never for long enough. Saying "no screen"
            # would send someone to check a sensor that is working.
            minimum = context.config.device_use.min_session_minutes
            lane.unavailable_reason = (
                f"The screen came on during {context.window.iso_date}, but no stretch "
                f"reached the {minimum:g} minutes a session needs "
                "(feature_engineering.device_use.min_session_minutes)."
            )
        else:
            lane.unavailable_reason = (
                f"The phone reported no interactive screen on {context.window.iso_date}."
            )

    return lane


def _nothing_reason(context: RuleContext) -> str:
    if not context.home_assistant_available:
        return "Home Assistant could not be reached, so phone use is unknown."
    return (
        "No phone entity produced data on this day. Add the companion app's "
        "interactive sensor under home_assistant.entities.device_use, and its "
        "last-used-app sensor under .app_usage, in config.yaml."
    )


# --------------------------------------------------------------------------
# Screen-on
# --------------------------------------------------------------------------


def _screen_states(context: RuleContext) -> list[NormalizedState]:
    return [
        state
        for state in context.normalized.states_for(STREAM_SCREEN)
        if state.state == "on"
    ]


def screen_windows(states: list[NormalizedState]) -> list[tuple[datetime, datetime]]:
    """The raw screen-on spans, unmerged.

    The session tier bridges short locks so the drawn bars read as sessions;
    clipping an application spell has to use the unbridged windows instead, or
    a five-minute pocket gap would silently become five minutes in an app.
    """
    return sorted(
        (state.start_time, state.end_time)
        for state in states
        if state.end_time > state.start_time
    )


def _sessions(
    context: RuleContext, states: list[NormalizedState]
) -> tuple[list[TimelineEvent], str | None]:
    """Screen-on stretches: evidence the user was awake and interacting."""
    if not states:
        return [], None

    rule = context.config.device_use
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
        name = (group[0].device or group[0].entity_id or "phone").replace("_", " ")
        minutes = (end - start).total_seconds() / 60
        events.append(
            TimelineEvent(
                id=f"phone_use_session_{index}_{int(start.timestamp())}",
                phenotype="phone_use",
                label=f"Phone in use · {_duration(minutes)}",
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
                category="phone_on",
                continues_before=before,
                continues_after=after,
                metadata={
                    "device": name,
                    "durationMinutes": round(minutes, 1),
                    "fullStart": group[0].start_time.isoformat(),
                    "fullEnd": group[-1].end_time.isoformat(),
                    "unlockCount": len(group),
                    "note": (
                        "The phone reported an interactive screen, with locks shorter "
                        f"than {rule.merge_within_minutes:.0f} minutes treated as part "
                        "of the same session. Someone was using it; which person is "
                        "not recorded."
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
                ),
            )
        )
    return events, states[0].source


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------


def app_spells(
    states: list[NormalizedState],
    windows: list[tuple[datetime, datetime]],
    merge_within: timedelta,
    *,
    packages: set[str] | None = None,
) -> list[tuple[str, datetime, datetime, list[str], NormalizedState]]:
    """Runs of one application, clipped to the screen-on windows.

    Returns `(package, start, end, raw_record_ids, sample)` per spell. `packages`
    keeps only the named ones, which is how the TikTok lane reuses this.

    Runs are built from every application first and filtered afterwards, never
    the other way round. Filtering first would let two spells either side of a
    glance at the home screen merge across it, quietly relabelling that glance —
    a row that exists to say how long was spent in one app must not round up.
    """
    if not states or not windows:
        return []

    ordered = sorted(states, key=lambda item: item.start_time)
    runs: list[tuple[str, datetime, datetime, list[str]]] = []
    for state in ordered:
        package = state.state
        if not package or package.startswith("__"):
            continue  # unavailable, or a hole the normalizer marked
        if runs and runs[-1][0] == package and state.start_time - runs[-1][2] <= merge_within:
            value, start, previous_end, ids = runs[-1]
            runs[-1] = (
                value,
                start,
                max(previous_end, state.end_time),
                [*ids, *state.raw_record_ids],
            )
            continue
        runs.append((package, state.start_time, state.end_time, list(state.raw_record_ids)))

    by_start = {state.start_time: state for state in ordered}

    spells: list[tuple[str, datetime, datetime, list[str], NormalizedState]] = []
    for package, run_start, run_end, ids in runs:
        if packages is not None and package not in packages:
            continue
        sample = by_start.get(run_start, ordered[0])
        for window_start, window_end in windows:
            start = max(run_start, window_start)
            end = min(run_end, window_end)
            if end > start:
                spells.append((package, start, end, ids, sample))
    spells.sort(key=lambda spell: spell[1])
    return spells


def _app_events(
    context: RuleContext,
    states: list[NormalizedState],
    screen: list[NormalizedState],
) -> tuple[list[TimelineEvent], str | None]:
    rule = context.config.phone_app
    windows = screen_windows(screen)
    if not states or not windows:
        return [], None

    minimum = timedelta(minutes=rule.min_app_minutes)
    events: list[TimelineEvent] = []

    for package, span_start, span_end, record_ids, sample in app_spells(
        states, windows, timedelta(minutes=rule.merge_within_minutes)
    ):
        if span_end - span_start < minimum:
            continue
        clipped = context.clip_to_day(span_start, span_end)
        if clipped is None:
            continue
        start, end, before, after = clipped

        minutes = (end - start).total_seconds() / 60
        events.append(
            TimelineEvent(
                id=f"phone_use_app_{int(start.timestamp())}",
                phenotype="phone_use",
                label=app_label(package),
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
                category="phone_app",
                continues_before=before,
                continues_after=after,
                metadata={
                    "package": package,
                    "durationMinutes": round(minutes, 1),
                    "fullStart": span_start.isoformat(),
                    "fullEnd": span_end.isoformat(),
                    "note": (
                        "The app that was in front, for as long as the screen was also "
                        "on. The sensor keeps reporting the last app after the screen "
                        "goes off, so the run was cut to the screen-on window."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_APP,
                    version=rule.rule_version,
                    raw_record_ids=record_ids,
                    entity_ids=[sample.entity_id] if sample.entity_id else [],
                    thresholds={
                        "min_app_minutes": rule.min_app_minutes,
                        "merge_within_minutes": rule.merge_within_minutes,
                    },
                    input_range=(span_start, span_end),
                    assumptions=[
                        "The app in front is what was being used, which a video left "
                        "playing behind a lock screen is not.",
                        "Screen-on is the phone's own report, so a screen woken by a "
                        "notification and ignored counts as use.",
                    ],
                    notes=[
                        "Clipped to the screen-on signal: Android reports the last used "
                        "app indefinitely, including all night."
                    ],
                ),
            )
        )
    return events, states[0].source


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------


def app_label(package: str) -> str:
    """`com.zhiliaoapp.musically` -> `TikTok`, unknown packages -> last segment."""
    known = APP_NAMES.get(package)
    if known:
        return known
    tail = package.rsplit(".", 1)[-1].replace("_", " ").strip()
    if not tail:
        return package
    return tail[0].upper() + tail[1:] if tail.islower() else tail


def _duration(minutes: float) -> str:
    hours, rest = divmod(int(round(minutes)), 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    if hours:
        return f"{hours}h"
    return f"{rest}m"
