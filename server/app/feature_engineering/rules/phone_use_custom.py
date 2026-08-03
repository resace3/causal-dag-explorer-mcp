"""Phone use, from the usage-stats collector add-on.

The same phone as the Phone Use row above, read through a different instrument,
and the two will not agree. This one holds Android's own foreground event
stream: real segments with start and end times, resolved to the second. The
other holds the companion app's "last used app" sensor, which reports a change
and then holds that value, and therefore has to be clipped against a screen
sensor before it means anything. Where they differ, this row is the finer
measurement — but it is measuring by a different definition, not correcting the
other one, and neither is presented as the truth about the other.

**Two numbers about the same app, and only one of them is a total.** Segments
are package-level: Android's public `UsageEvents` API does not expose
`taskRootPackage`, so a link opened inside TikTok is credited to the browser.
The add-on's `/v1/apps` reads the system's own daily buckets, which do carry
task-root attribution, and those are the authoritative totals — measured
fivefold larger for in-app-browser-heavy apps. So the bars here are drawn from
segments, because only segments know *when*, and every named spell carries the
authoritative daily figure beside it rather than inviting the reader to add the
bars up.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ...connectors.phone_usage.connector import (
    STREAM_APP_DAILY,
    STREAM_DAY_SUMMARY,
    STREAM_SEGMENT,
)
from ...models.raw import RawRecord
from ...models.timeline import Lane, TimelineEvent
from ..context import RuleContext, sort_events
from ..provenance import build_provenance
from .phone_use import app_label

RULE_SESSION = "phone_use_custom.pickup"
RULE_APP = "phone_use_custom.app_spell"

LANE = {
    "id": "phone_use_custom",
    "phenotype": "phone_use_custom",
    "label": "Phone Use custom",
    "description": "Foreground segments from Android's usage stats",
    "accent": "violet",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)

    segments = [
        record
        for record in context.normalized.raw_for(STREAM_SEGMENT)
        if record.end_timestamp is not None
    ]
    # Scoped to the day, not to the fetch window. The window opens fourteen
    # hours early, so yesterday evening's segments are always in hand — and
    # judging "did anything happen?" by those would tell someone whose phone
    # stopped syncing that their thresholds were too strict, sending them to
    # config.yaml instead of to the collector.
    in_day = [
        record
        for record in segments
        if record.end_timestamp > context.window.start
        and record.timestamp < context.window.end
    ]
    if not in_day:
        lane.unavailable_reason = _nothing_reason(context)
        return lane

    rule = context.config.phone_use_custom
    totals = _daily_totals(context)
    summary = _day_summary(context)

    events: list[TimelineEvent] = []
    events.extend(_pickups(context, segments, summary))
    events.extend(_app_spells(context, segments, totals))

    lane.events = sort_events(events)
    lane.available = bool(events)
    lane.sources = ["phone_usage"]
    lane.units = ["minutes"]

    if not lane.available:
        lane.unavailable_reason = (
            f"The collector recorded foreground activity on {context.window.iso_date}, "
            f"but no stretch reached the {rule.min_session_minutes:g} minutes a pickup "
            "needs (feature_engineering.phone_use_custom.min_session_minutes)."
        )
    return lane


def _nothing_reason(context: RuleContext) -> str:
    return (
        f"The phone-usage add-on reported no foreground activity on "
        f"{context.window.iso_date}. The collector app syncs hourly and its history "
        "only reaches back about eight days, so older days are empty rather than "
        "quiet — and a phone that lost its tunnel to Home Assistant stops reporting "
        "without the add-on looking unhealthy."
    )


def _daily_totals(context: RuleContext) -> dict[str, float]:
    """Authoritative per-app minutes for the displayed day, by package."""
    wanted = context.window.iso_date
    totals: dict[str, float] = {}
    for record in context.normalized.raw_for(STREAM_APP_DAILY):
        if record.attributes.get("date") != wanted:
            continue
        package = record.attributes.get("package")
        if isinstance(package, str) and isinstance(record.value, (int, float)):
            totals[package] = float(record.value)
    return totals


def _day_summary(context: RuleContext) -> dict:
    wanted = context.window.iso_date
    for record in context.normalized.raw_for(STREAM_DAY_SUMMARY):
        if record.attributes.get("date") == wanted:
            return dict(record.attributes)
    return {}


# --------------------------------------------------------------------------
# Pickups
# --------------------------------------------------------------------------


def _pickups(
    context: RuleContext, segments: list[RawRecord], summary: dict
) -> list[TimelineEvent]:
    rule = context.config.phone_use_custom
    merge_within = timedelta(minutes=rule.merge_within_minutes)
    minimum = timedelta(minutes=rule.min_session_minutes)

    spans = _merge(segments, merge_within)
    events: list[TimelineEvent] = []

    for index, (span_start, span_end, members) in enumerate(spans):
        clipped = context.clip_to_day(span_start, span_end)
        if clipped is None:
            continue
        start, end, before, after = clipped
        if end - start < minimum:
            continue

        minutes = (end - start).total_seconds() / 60
        foreground = _foreground_minutes(members, start, end)
        idle = max(minutes - foreground, 0.0)
        metadata = {
            "durationMinutes": round(minutes, 1),
            "foregroundMinutes": round(foreground, 1),
            "bridgedIdleMinutes": round(idle, 1),
            "fullStart": span_start.isoformat(),
            "fullEnd": span_end.isoformat(),
            "segmentCount": len(members),
            "note": (
                "One pickup, from Android's usage-stats stream, with gaps shorter than "
                f"{rule.merge_within_minutes:g} minutes bridged rather than ending it. "
                f"The bar spans {minutes:.0f} minutes; an app was actually in front for "
                f"{foreground:.0f} of them, and the other {idle:.0f} are bridged gaps "
                "with the phone down. Measured by a different instrument from the "
                "Phone Use row above, so the two will not match."
            ),
        }
        # The day's counts ride on the first pickup: they describe the day, not
        # this stretch, and saying so beats repeating them on every bar. Keyed
        # on the first *drawn* pickup, not the first span — the fetch window
        # opens fourteen hours early, so span zero is usually last night and is
        # clipped away, taking the counts with it.
        if summary and not any("dayCounts" in event.metadata for event in events):
            metadata["dayCounts"] = {
                "unlocks": summary.get("unlocks"),
                "glancesWithoutUnlock": summary.get("glances_without_unlock"),
                "notificationInterruptions": summary.get("notification_interruptions"),
                "appSwitches": summary.get("app_switches"),
                "screenOnMinutes": summary.get("screen_on_minutes"),
                "note": "Counts for the whole day, not for this pickup.",
            }

        events.append(
            TimelineEvent(
                id=f"phone_custom_pickup_{index}_{int(start.timestamp())}",
                phenotype="phone_use_custom",
                label=f"Phone in use · {_duration(minutes)}",
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round(minutes, 1),
                unit="min",
                source="phone_usage",
                device="phone",
                measured_or_derived="derived",
                confidence=0.85,
                data_quality="high",
                category="phone_custom_on",
                continues_before=before,
                continues_after=after,
                metadata=metadata,
                provenance=build_provenance(
                    rule=RULE_SESSION,
                    version=rule.rule_version,
                    raw_record_ids=[record.id for record in members],
                    thresholds={
                        "merge_within_minutes": rule.merge_within_minutes,
                        "min_session_minutes": rule.min_session_minutes,
                    },
                    input_range=(span_start, span_end),
                    notes=[
                        "Foreground segments carry real end times, so nothing is "
                        "clipped against a screen sensor here.",
                        "The bar is the span of the pickup; foregroundMinutes is the "
                        "time inside it an app was really in front. Summing the bars "
                        "counts the bridged gaps too.",
                    ],
                ),
            )
        )
    return events


# --------------------------------------------------------------------------
# Application spells
# --------------------------------------------------------------------------


def _app_spells(
    context: RuleContext, segments: list[RawRecord], totals: dict[str, float]
) -> list[TimelineEvent]:
    rule = context.config.phone_use_custom
    merge_within = timedelta(minutes=rule.app_merge_within_minutes)
    minimum = timedelta(minutes=rule.min_app_minutes)

    runs: list[tuple[str, datetime, datetime, list[str]]] = []
    for record in sorted(segments, key=lambda item: item.timestamp):
        package = str(record.value)
        end = record.end_timestamp
        if end is None:
            continue
        if runs and runs[-1][0] == package and record.timestamp - runs[-1][2] <= merge_within:
            value, begin, previous_end, ids = runs[-1]
            runs[-1] = (value, begin, max(previous_end, end), [*ids, record.id])
            continue
        runs.append((package, record.timestamp, end, [record.id]))

    events: list[TimelineEvent] = []
    for package, span_start, span_end, ids in runs:
        if span_end - span_start < minimum:
            continue
        clipped = context.clip_to_day(span_start, span_end)
        if clipped is None:
            continue
        start, end, before, after = clipped

        minutes = (end - start).total_seconds() / 60
        authoritative = totals.get(package)
        events.append(
            TimelineEvent(
                id=f"phone_custom_app_{int(start.timestamp())}",
                phenotype="phone_use_custom",
                label=app_label(package),
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round(minutes, 1),
                unit="min",
                source="phone_usage",
                device="phone",
                measured_or_derived="measured",
                confidence=0.9,
                data_quality="high",
                category="phone_custom_app",
                continues_before=before,
                continues_after=after,
                metadata={
                    "package": package,
                    "durationMinutes": round(minutes, 1),
                    "fullStart": span_start.isoformat(),
                    "fullEnd": span_end.isoformat(),
                    "attribution": "package",
                    "authoritativeDailyMinutes": authoritative,
                    "note": (
                        "This bar is package-level: a link opened inside an app is "
                        "credited to the browser, because Android's public event API "
                        "does not expose the task root. "
                        + (
                            f"The system's own daily total for this app is "
                            f"{authoritative:g} minutes, which does carry task-root "
                            "attribution — adding these bars up will not reach it."
                            if isinstance(authoritative, (int, float))
                            else "No authoritative daily total was available for this app."
                        )
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_APP,
                    version=rule.rule_version,
                    raw_record_ids=ids,
                    thresholds={
                        "min_app_minutes": rule.min_app_minutes,
                        "app_merge_within_minutes": rule.app_merge_within_minutes,
                    },
                    input_range=(span_start, span_end),
                    assumptions=[
                        "The app in the foreground is what was being used, which a "
                        "video left playing behind a lock screen is not.",
                    ],
                    notes=[
                        "Timing from the event stream; magnitude for the day from "
                        "/v1/apps. The two are never mixed.",
                    ],
                ),
            )
        )
    return events


def _merge(
    records: list[RawRecord], tolerance: timedelta
) -> list[tuple[datetime, datetime, list[RawRecord]]]:
    """Spans of use, bridging gaps up to `tolerance`.

    The member records travel with each span rather than just their ids,
    because the span and the time actually spent in an app are two different
    numbers once gaps are bridged, and the row reports both.
    """
    spans: list[tuple[datetime, datetime, list[RawRecord]]] = []
    for record in sorted(records, key=lambda item: item.timestamp):
        end = record.end_timestamp
        if end is None:
            continue
        if spans and record.timestamp - spans[-1][1] <= tolerance:
            start, previous_end, members = spans[-1]
            spans[-1] = (start, max(previous_end, end), [*members, record])
            continue
        spans.append((record.timestamp, end, [record]))
    return spans


def _foreground_minutes(
    members: list[RawRecord], start: datetime, end: datetime
) -> float:
    """Minutes actually spent with an app in front, inside [start, end).

    Not the span. A bridged gap is a phone in a pocket, and counting it as
    foreground time would be the row asserting exactly what the segments say
    did not happen.
    """
    total = 0.0
    for record in members:
        finish = record.end_timestamp
        if finish is None:
            continue
        overlap = (min(finish, end) - max(record.timestamp, start)).total_seconds()
        if overlap > 0:
            total += overlap
    return total / 60


def _duration(minutes: float) -> str:
    hours, rest = divmod(int(round(minutes)), 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    if hours:
        return f"{hours}h"
    return f"{rest}m"
