"""TikTok, on its own row.

One application followed separately, because a row that is a hundredth of the
phone's screen time is invisible inside the Phone Use lane and is exactly the
thing worth lining up against sleep onset and evening light.

Everything here also appears one row up, as an application spell. That is the
same time seen at two grains, not a second measurement, and the details panel
says so — treating the two as independent evidence would double-count.

The spells come from the same clipped runs the Phone Use lane draws, so this
row inherits its honesty about the screen sensor: Android reports the last app
used indefinitely, and without a screen signal to cut the run against, a phone
put down at eleven would read as a night in TikTok. It is not drawn instead.
"""

from __future__ import annotations

from datetime import timedelta

from ...models.timeline import Lane, TimelineEvent
from ..context import RuleContext, sort_events
from ..provenance import build_provenance
from .phone_use import STREAM_APP, _screen_states, app_label
from .spells import clipped_spells, on_windows

RULE_TRACKED_APP = "tiktok.app_session"

LANE = {
    "id": "tiktok",
    "phenotype": "tiktok",
    "label": "TikTok",
    "description": "Spells in the app, on the phone",
    "accent": "rose",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)

    rule = context.config.tiktok
    app_states = context.normalized.states_for(STREAM_APP)
    screen = _screen_states(context)
    windows = on_windows(screen)

    if not app_states:
        lane.unavailable_reason = _nothing_reason(context)
        return lane

    if not windows:
        lane.unavailable_reason = (
            "The phone reported which app was in front but not whether the screen "
            "was on. Android holds the last app indefinitely, so without the "
            "screen signal a phone left face-down would be drawn as hours in the "
            "app. Add the companion app's interactive sensor under "
            "home_assistant.entities.device_use in config.yaml."
        )
        return lane

    minimum = timedelta(minutes=rule.min_minutes)
    packages = {package for package in rule.packages if package}
    events: list[TimelineEvent] = []

    for package, span_start, span_end, record_ids, sample in clipped_spells(
        app_states,
        windows,
        timedelta(minutes=rule.merge_within_minutes),
        values=packages,
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
                id=f"tiktok_{int(start.timestamp())}",
                phenotype="tiktok",
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
                category="tiktok",
                continues_before=before,
                continues_after=after,
                metadata={
                    "package": package,
                    "durationMinutes": round(minutes, 1),
                    "fullStart": span_start.isoformat(),
                    "fullEnd": span_end.isoformat(),
                    "note": (
                        "The app was in front while the screen was on. This spell is "
                        "also drawn in the Phone Use lane above — one stretch of time "
                        "at two grains, not two separate observations."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_TRACKED_APP,
                    version=rule.rule_version,
                    raw_record_ids=record_ids,
                    entity_ids=[sample.entity_id] if sample.entity_id else [],
                    thresholds={
                        "packages": sorted(packages),
                        "min_minutes": rule.min_minutes,
                        "merge_within_minutes": rule.merge_within_minutes,
                    },
                    input_range=(span_start, span_end),
                    assumptions=[
                        "The app in front is what was being watched; a video left "
                        "playing under a lock screen is not counted.",
                    ],
                    notes=[
                        "Clipped to the screen-on signal, then matched against the "
                        "package names in feature_engineering.tiktok.packages."
                    ],
                ),
            )
        )

    lane.events = sort_events(events)
    lane.available = bool(events)
    lane.sources = [app_states[0].source] if lane.available else []
    lane.units = ["minutes"]

    if not lane.available:
        lane.unavailable_reason = (
            f"None of the tracked packages ({', '.join(sorted(packages)) or 'none configured'}) "
            f"was in front while the screen was on during {context.window.iso_date}."
        )
    return lane


def _nothing_reason(context: RuleContext) -> str:
    if not context.home_assistant_available:
        return "Home Assistant could not be reached, so app use is unknown."
    return (
        "No sensor reported which app was in front. Add the companion app's "
        "last-used-app sensor under home_assistant.entities.app_usage in config.yaml."
    )
