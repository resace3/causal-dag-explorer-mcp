"""Computer use, from ActivityWatch.

Three tiers, because they answer three different questions:

* **At the computer** — stretches where the keyboard and mouse were being
  touched. Short idle spells are bridged; a pause to read a page is not leaving
  the desk.
* **Applications** — which program had focus, for runs long enough to be worth
  naming.
* **Browsing** — which site a browser tab was on, present only when the detail
  level permits it and the browser extension is reporting.

Two things this rule deliberately does not do. It does not categorise
applications as work, leisure or distraction — that judgement is not in the
data, and the rest of this application does not pass judgement either. And it
does not treat a computer that is off as missing data: no lane series is
produced, so a day spent away from the desk lowers no coverage figure.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ...models.raw import RawRecord
from ...models.timeline import Lane, TimelineEvent
from ..context import RuleContext, sort_events
from ..provenance import build_provenance

RULE_SESSION = "computer_use.at_computer"
RULE_APP = "computer_use.app_session"
RULE_SITE = "computer_use.browsing"

STREAM_AFK = "computer_afk"
STREAM_WINDOW = "computer_window"
STREAM_WEB = "computer_web"

LANE = {
    "id": "computer_use",
    "phenotype": "computer_use",
    "label": "Computer Use",
    "description": "Time at this machine, and in what",
    "accent": "amber",
}

#: Runs of the same application separated by less than this are one spell —
#: a glance at another window and back is not two sessions of work.
SAME_LABEL_GAP = timedelta(seconds=90)


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)

    afk = context.normalized.raw_for(STREAM_AFK)
    windows = context.normalized.raw_for(STREAM_WINDOW)
    sites = context.normalized.raw_for(STREAM_WEB)

    if not windows and not afk:
        lane.unavailable_reason = _nothing_reason(context)
        return lane

    rule = context.config.computer_use
    events: list[TimelineEvent] = []

    sessions, inferred = _sessions(context, afk, windows)
    events.extend(sessions)

    app_events, _short_apps = _spells(
        context,
        windows,
        rule_id=RULE_APP,
        category="app_session",
        minimum=timedelta(minutes=rule.min_app_minutes),
        label_of=_app_label,
        assumptions=[
            "Focus is attention: the window in front is taken to be what was "
            "being used, which a video left playing in another window is not.",
        ],
    )
    events.extend(app_events)

    site_events, _short_sites = _spells(
        context,
        sites,
        rule_id=RULE_SITE,
        category="browsing",
        minimum=timedelta(minutes=rule.min_site_minutes),
        label_of=_site_label,
        assumptions=[
            "One tab at a time: ActivityWatch reports the tab in front, so a "
            "site open in a background tab contributes nothing.",
        ],
    )
    events.extend(site_events)

    lane.events = sort_events(events)
    lane.available = bool(events)
    lane.sources = ["activitywatch"] if lane.available else []
    lane.units = ["minutes"]

    if not lane.available:
        lane.unavailable_reason = (
            "ActivityWatch holds events near this day, but none of them fall inside "
            f"{context.window.iso_date} itself."
        )
        return lane

    # Short application spells are deliberately not warned about. Alt-tabbing
    # means a normal working day has a hundred of them, the time is already
    # inside the session bars, and a warning that fires every single day
    # teaches people to stop reading warnings. The idle watcher missing is a
    # different matter: rare, actionable, and it changes what the lane means.
    if inferred:
        context.warnings.append(
            "ActivityWatch has no idle watcher on this machine, so time at the "
            "computer was inferred from focus changes alone."
        )

    return lane


def _nothing_reason(context: RuleContext) -> str:
    if not context.activitywatch_available:
        return context.activitywatch_note or (
            "ActivityWatch was not read for this day, so there is no record of "
            "what this computer was used for."
        )
    return (
        f"ActivityWatch recorded nothing on {context.window.iso_date}. It only holds "
        "days since it was installed, and it records nothing while the machine is off."
    )


# --------------------------------------------------------------------------
# At the computer
# --------------------------------------------------------------------------


def _sessions(
    context: RuleContext, afk: list[RawRecord], windows: list[RawRecord]
) -> tuple[list[TimelineEvent], bool]:
    """Stretches at the machine, and whether they had to be inferred.

    The idle watcher is the honest source: it knows the difference between a
    window left open and a person at the desk. Without it the focus events are
    all there is, and the caller says so rather than presenting the same shape
    as though it were measured the same way.
    """
    rule = context.config.computer_use
    inferred = not afk

    if afk:
        active = [record for record in afk if str(record.value) == "not-afk"]
    else:
        active = windows

    spans = _merge_spans(active, timedelta(minutes=rule.merge_within_minutes))
    minimum = timedelta(minutes=rule.min_session_minutes)
    events: list[TimelineEvent] = []

    for span_start, span_end, record_ids in spans:
        # Short stretches are drawn, not discarded. A dropped application spell
        # is still inside a session total, so nothing is lost by leaving it
        # unnamed; a dropped *session* is inside nothing, and the lane would
        # quietly show an empty evening the day has focus events for. Real idle
        # data fragments heavily — four-minute stretches split by six-minute
        # breaks — so this is the common case, not the edge.
        brief = span_end - span_start < minimum
        clipped = context.clip_to_day(span_start, span_end)
        if clipped is None:
            continue
        start, end, before, after = clipped

        minutes = (end - start).total_seconds() / 60
        events.append(
            TimelineEvent(
                id=f"computer_use_session_{int(start.timestamp())}",
                phenotype="computer_use",
                label=f"At the computer · {_duration(minutes)}",
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round(minutes, 1),
                unit="minutes",
                source="activitywatch",
                device=active[0].device if active else None,
                entity_id=active[0].entity_id if active else None,
                measured_or_derived="derived",
                confidence=0.75 if inferred else 0.9,
                data_quality="medium" if inferred else "high",
                category="at_computer",
                continues_before=before,
                continues_after=after,
                metadata={
                    "durationMinutes": round(minutes, 1),
                    "fullStart": span_start.isoformat(),
                    "fullEnd": span_end.isoformat(),
                    "brief": brief,
                    "source": "idle watcher" if not inferred else "focus events only",
                    "note": (
                        "Keyboard and mouse activity, with idle spells shorter than "
                        f"{rule.merge_within_minutes:.0f} minutes treated as part of the "
                        "session."
                        if not inferred
                        else "Inferred from focus changes: this machine has no idle "
                        "watcher, so a window left open counts as use."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_SESSION,
                    version=rule.rule_version,
                    raw_record_ids=record_ids,
                    entity_ids=[active[0].entity_id] if active and active[0].entity_id else [],
                    thresholds={
                        "min_session_minutes": rule.min_session_minutes,
                        "merge_within_minutes": rule.merge_within_minutes,
                        "below_session_minimum": brief,
                    },
                    input_range=(span_start, span_end),
                    assumptions=(
                        []
                        if not inferred
                        else [
                            "No idle watcher was running, so time at the computer is "
                            "an upper bound rather than a measurement."
                        ]
                    ),
                ),
            )
        )
    return events, inferred


# --------------------------------------------------------------------------
# Applications and sites
# --------------------------------------------------------------------------


def _spells(
    context: RuleContext,
    records: list[RawRecord],
    *,
    rule_id: str,
    category: str,
    minimum: timedelta,
    label_of,
    assumptions: list[str],
) -> tuple[list[TimelineEvent], int]:
    """Merge adjacent records carrying the same value into named spells."""
    if not records:
        return [], 0

    rule = context.config.computer_use
    events: list[TimelineEvent] = []
    dropped = 0
    by_id = {record.id: record for record in records}

    for value, span_start, span_end, record_ids in _runs(records):
        if span_end - span_start < minimum:
            dropped += 1
            continue
        clipped = context.clip_to_day(span_start, span_end)
        if clipped is None:
            continue
        start, end, before, after = clipped

        minutes = (end - start).total_seconds() / 60
        sample = by_id[record_ids[0]]
        metadata = {
            "durationMinutes": round(minutes, 1),
            "fullStart": span_start.isoformat(),
            "fullEnd": span_end.isoformat(),
            "recorded": value,
            "detail": sample.attributes.get("detail"),
        }
        if category == "browsing":
            metadata["precision"] = (
                "full URL" if sample.attributes.get("detail") == "full" else "domain only"
            )
        if sample.attributes.get("title"):
            metadata["windowTitle"] = sample.attributes["title"]

        events.append(
            TimelineEvent(
                id=f"computer_use_{category}_{int(start.timestamp())}",
                phenotype="computer_use",
                label=label_of(value),
                event_type="interval",
                start_time=start,
                end_time=end,
                value=round(minutes, 1),
                unit="minutes",
                source="activitywatch",
                device=sample.device,
                entity_id=sample.entity_id,
                measured_or_derived="derived",
                confidence=0.85,
                data_quality="high",
                category=category,
                continues_before=before,
                continues_after=after,
                metadata=metadata,
                provenance=build_provenance(
                    rule=rule_id,
                    version=rule.rule_version,
                    raw_record_ids=record_ids,
                    entity_ids=[sample.entity_id] if sample.entity_id else [],
                    thresholds={
                        "min_app_minutes": rule.min_app_minutes,
                        "min_site_minutes": rule.min_site_minutes,
                        "same_label_gap_seconds": SAME_LABEL_GAP.total_seconds(),
                    },
                    input_range=(span_start, span_end),
                    assumptions=assumptions,
                    notes=[
                        "Reduced at the connector: detail beyond the configured level "
                        "is never stored, so it cannot appear here."
                    ],
                ),
            )
        )
    return events, dropped


def _runs(
    records: list[RawRecord],
) -> list[tuple[str, datetime, datetime, list[str]]]:
    """Consecutive records with the same value, as one span each."""
    ordered = sorted(records, key=lambda record: record.timestamp)
    runs: list[tuple[str, datetime, datetime, list[str]]] = []

    for record in ordered:
        value = str(record.value)
        end = record.end_timestamp or record.timestamp
        if runs and runs[-1][0] == value and record.timestamp - runs[-1][2] <= SAME_LABEL_GAP:
            label, start, previous_end, ids = runs[-1]
            runs[-1] = (label, start, max(previous_end, end), [*ids, record.id])
            continue
        runs.append((value, record.timestamp, end, [record.id]))
    return runs


def _merge_spans(
    records: list[RawRecord], tolerance: timedelta
) -> list[tuple[datetime, datetime, list[str]]]:
    """Collapse records into spans, bridging gaps up to `tolerance`."""
    ordered = sorted(records, key=lambda record: record.timestamp)
    spans: list[tuple[datetime, datetime, list[str]]] = []

    for record in ordered:
        end = record.end_timestamp or record.timestamp
        if spans and record.timestamp - spans[-1][1] <= tolerance:
            start, previous_end, ids = spans[-1]
            spans[-1] = (start, max(previous_end, end), [*ids, record.id])
            continue
        spans.append((record.timestamp, end, [record.id]))
    return spans


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------


def _app_label(value: str) -> str:
    """`chrome.exe` -> `Chrome`. Presentation only; the raw name is kept."""
    name = value[:-4] if value.lower().endswith(".exe") else value
    name = name.strip() or value
    return name[0].upper() + name[1:] if name.islower() else name


def _site_label(value: str) -> str:
    return value


def _duration(minutes: float) -> str:
    hours, rest = divmod(int(round(minutes)), 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    if hours:
        return f"{hours}h"
    return f"{rest}m"
