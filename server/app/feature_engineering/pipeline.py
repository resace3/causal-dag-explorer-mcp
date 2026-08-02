"""Runs every feature-engineering rule and assembles the day's lanes.

A failure in one rule degrades that lane only: the lane is marked unavailable
with the error text, and the rest of the timeline still renders.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta

from ..models.timeline import CoverageWindow, DayCoverage, Lane
from .context import RuleContext
from .provenance import coverage_fraction
from .rules import (
    activity,
    computer_use,
    heart_rate,
    hrv,
    light,
    location,
    phone_use,
    presence,
    readiness,
    sleep,
    temperature,
    tiktok,
)

logger = logging.getLogger(__name__)

# Lane order on screen, top to bottom.
RULES = (
    ("activity", activity.build_lane),
    ("heart_rate", heart_rate.build_lane),
    ("hrv", hrv.build_lane),
    ("readiness", readiness.build_lane),
    ("sleep", sleep.build_lane),
    ("temperature", temperature.build_lane),
    ("environment", light.build_lane),
    ("presence", presence.build_lane),
    ("computer_use", computer_use.build_lane),
    # The two screen rows sit together, and TikTok directly under the phone row
    # it is a subset of, so the whole and the part read as one block.
    ("phone_use", phone_use.build_lane),
    ("tiktok", tiktok.build_lane),
    ("location", location.build_lane),
)

FALLBACK_LANE_META = {
    "activity": ("Activity", "Exercise and movement", "green"),
    "heart_rate": ("Heart Rate", "Wearable cardiovascular signal", "blue"),
    "hrv": ("Heart Rate Variability", "Nightly beat-to-beat variation", "indigo"),
    "readiness": ("Physiological Readiness", "Provider composite score", "purple"),
    "sleep": ("Sleep", "Sleep periods and stages", "orange"),
    "temperature": ("Temperature", "Wearable temperature sensor", "teal"),
    "environment": ("Environment", "Home conditions", "sky"),
    "presence": ("Presence & Motion", "Home occupancy signals", "cyan"),
    "computer_use": ("Computer Use", "Time at this machine, and in what", "amber"),
    "phone_use": ("Phone Use", "Screen-on stretches, and what was open", "fuchsia"),
    "tiktok": ("TikTok", "Spells in the app, on the phone", "rose"),
    "location": ("Phone Location", "Zone and place name", "indigo"),
}


def run(context: RuleContext) -> tuple[list[Lane], DayCoverage, list[str]]:
    lanes: list[Lane] = []

    for lane_id, build in RULES:
        try:
            lanes.append(build(context))
        except Exception as exc:  # noqa: BLE001 - one bad rule must not lose the day
            logger.error("Feature rule '%s' failed: %s", lane_id, traceback.format_exc())
            label, description, accent = FALLBACK_LANE_META[lane_id]
            lanes.append(
                Lane(
                    id=lane_id,
                    phenotype=lane_id,
                    label=label,
                    description=description,
                    accent=accent,
                    available=False,
                    unavailable_reason=(
                        f"Feature engineering failed for this lane ({type(exc).__name__}: {exc}). "
                        "Other lanes are unaffected."
                    ),
                )
            )
            context.warnings.append(f"Feature engineering failed for the {label} lane: {exc}")

    coverage = _coverage(context, lanes)
    highlights = _highlights(context, lanes)
    return lanes, coverage, highlights


def _coverage(context: RuleContext, lanes: list[Lane]) -> DayCoverage:
    """How much of the day each stream actually observed.

    For continuous lanes this is the fraction of the day outside a declared gap.
    Discrete lanes have no sampling rate to be missing from, so a lane that
    reported at all counts as fully observed — and the overall figure is
    averaged over continuous lanes only, where the number means something.
    """
    per_lane: dict[str, float] = {}
    missing: list[CoverageWindow] = []
    continuous_fractions: list[float] = []

    for lane in lanes:
        if not lane.available:
            per_lane[lane.id] = 0.0
            continue

        if lane.series:
            fractions = [
                coverage_fraction(series.gaps, context.window.start, context.window.end)
                for series in lane.series
            ]
            value = round(sum(fractions) / len(fractions), 4)
            per_lane[lane.id] = value
            continuous_fractions.append(value)
            for series in lane.series:
                for gap in series.gaps:
                    if gap.end_time - gap.start_time >= timedelta(minutes=30):
                        missing.append(
                            CoverageWindow(
                                start_time=gap.start_time,
                                end_time=gap.end_time,
                                label=f"{lane.label}: {gap.reason or 'no samples'}",
                            )
                        )
        else:
            per_lane[lane.id] = 1.0

    if continuous_fractions:
        overall = round(sum(continuous_fractions) / len(continuous_fractions), 4)
    else:
        available = [lane for lane in lanes if lane.available]
        overall = round(len(available) / len(lanes), 4) if lanes else 0.0

    missing.sort(key=lambda window: window.start_time)
    return DayCoverage(overall_fraction=overall, per_lane=per_lane, missing_periods=missing[:12])


def _highlights(context: RuleContext, lanes: list[Lane]) -> list[str]:
    """Neutral temporal descriptions. No causal language, ever."""
    highlights: list[str] = []
    lane_by_id = {lane.id: lane for lane in lanes}

    activity_events = [
        event
        for event in lane_by_id.get("activity", Lane(
            id="activity", phenotype="activity", label="", description="", accent="green"
        )).events
    ]
    sleep_events = [
        event
        for event in lane_by_id.get("sleep", Lane(
            id="sleep", phenotype="sleep", label="", description="", accent="orange"
        )).events
        if event.category == "main_sleep"
    ]

    # Gap between the last activity and the next sleep onset.
    later_sleep = [
        event
        for event in sleep_events
        if activity_events and event.start_time > activity_events[-1].start_time
    ]
    if activity_events and later_sleep:
        last_activity = activity_events[-1]
        onset = later_sleep[-1].start_time
        reference = last_activity.end_time or last_activity.start_time
        hours = (onset - reference).total_seconds() / 3600
        if hours > 0:
            highlights.append(
                f"{last_activity.label} ended {hours:.1f} hours before the recorded sleep onset."
            )

    # Heart rate during vs outside recorded activity.
    hr_lane = lane_by_id.get("heart_rate")
    if hr_lane and hr_lane.series and activity_events:
        points = hr_lane.series[0].points
        windows = [
            (event.start_time, event.end_time or event.start_time) for event in activity_events
        ]
        inside = [
            point.value
            for point in points
            if any(start <= point.timestamp < end for start, end in windows)
        ]
        outside = [
            point.value
            for point in points
            if not any(start <= point.timestamp < end for start, end in windows)
        ]
        if inside and outside:
            highlights.append(
                f"Mean heart rate was {sum(inside) / len(inside):.0f} bpm during recorded "
                f"activity and {sum(outside) / len(outside):.0f} bpm outside it."
            )

    # Illuminance in the hour before sleep onset.
    environment = lane_by_id.get("environment")
    if environment and sleep_events:
        onset = sleep_events[-1].start_time
        samples = [
            sample
            for sample in context.normalized.samples_for("illuminance")
            if onset - timedelta(hours=1) <= sample.timestamp < onset
        ]
        earlier = [
            sample
            for sample in context.normalized.samples_for("illuminance")
            if onset - timedelta(hours=3) <= sample.timestamp < onset - timedelta(hours=1)
        ]
        if samples and earlier:
            recent_mean = sum(s.value for s in samples) / len(samples)
            earlier_mean = sum(s.value for s in earlier) / len(earlier)
            direction = "lower" if recent_mean < earlier_mean else "higher"
            highlights.append(
                f"Measured illuminance in the hour before sleep onset was {recent_mean:.0f} lux, "
                f"{direction} than the {earlier_mean:.0f} lux recorded in the two hours before that."
            )

    # Plain facts that hold whatever shape the data arrived in.
    for event in sleep_events:
        minutes = event.metadata.get("durationMinutes")
        if not isinstance(minutes, (int, float)) or minutes < 60:
            continue
        # Quote the unclipped times: pairing a clipped end with the full
        # duration would describe a 3-hour window as 8.8 hours.
        start = _parse_iso(event.metadata.get("fullStart")) or event.start_time
        end = _parse_iso(event.metadata.get("fullEnd")) or event.end_time or event.start_time
        spans = event.continues_before or event.continues_after
        # The hours quoted here have to be the ones the two clock times span.
        # The row's own number is time *asleep*, which is shorter, and reading
        # it against this period's endpoints would be a sum that does not add up.
        period = event.metadata.get("sleepPeriodMinutes")
        if not isinstance(period, (int, float)) or period <= 0:
            period = (end - start).total_seconds() / 60
        asleep = event.metadata.get("minutesAsleep")
        highlights.append(
            f"Recorded sleep ran from {_format_clock(start, context)} to "
            f"{_format_clock(end, context)}, {period / 60:.1f} hours"
            + (
                f", {asleep / 60:.1f} of them asleep"
                if isinstance(asleep, (int, float)) and asleep > 0
                else ""
            )
            + (" (crossing midnight)." if spans else ".")
        )
        break

    for lane in lanes:
        for series in lane.series:
            total = series.metadata.get("totalStepsForDay")
            if isinstance(total, (int, float)) and total > 0:
                highlights.append(
                    f"The step counter recorded {int(total):,} steps across the day."
                )

    # Missing periods are a fact about the day worth stating plainly.
    coverage_gaps = [
        gap
        for lane in lanes
        for series in lane.series
        for gap in series.gaps
        if gap.end_time - gap.start_time >= timedelta(minutes=45)
    ]
    if coverage_gaps:
        longest = max(coverage_gaps, key=lambda gap: gap.end_time - gap.start_time)
        minutes = (longest.end_time - longest.start_time).total_seconds() / 60
        highlights.append(
            f"The longest recording gap lasted {minutes:.0f} minutes, starting at "
            f"{_format_clock(longest.start_time, context)}."
        )

    return [item for item in highlights if item]


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_clock(moment, context: RuleContext) -> str:
    """12-hour local time without a leading zero (portable across platforms)."""
    local = moment.astimezone(context.tz)
    return f"{(local.hour % 12) or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
