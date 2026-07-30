"""Helpers for building `Provenance` records and detecting data gaps.

Every derived feature must be able to answer: which raw records produced this,
which rule and version ran, what thresholds applied, and what was assumed about
missing data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..models.raw import NormalizedSample
from ..models.timeline import Provenance, SeriesGap


def build_provenance(
    *,
    rule: str,
    version: str,
    raw_record_ids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    thresholds: dict[str, Any] | None = None,
    input_range: tuple[datetime, datetime] | None = None,
    output_timestamp: datetime | None = None,
    assumptions: list[str] | None = None,
    notes: list[str] | None = None,
) -> Provenance:
    return Provenance(
        raw_record_ids=list(dict.fromkeys(raw_record_ids or []))[:400],
        source_entity_ids=list(dict.fromkeys(entity_ids or [])),
        transformation_rule=rule,
        rule_version=version,
        thresholds=thresholds or {},
        input_time_range=(
            [input_range[0].isoformat(), input_range[1].isoformat()] if input_range else None
        ),
        output_timestamp=(output_timestamp or datetime.now().astimezone()).isoformat(),
        missing_data_assumptions=assumptions or [],
        notes=notes or [],
    )


def detect_gaps(
    samples: list[NormalizedSample],
    window_start: datetime,
    window_end: datetime,
    max_gap: timedelta,
    *,
    reason: str = "No samples were recorded in this period.",
    explicit: list[tuple[datetime, datetime]] | None = None,
) -> list[SeriesGap]:
    """Missing-data intervals in a stream.

    Two different things count as missing, and both are reported:

    * `explicit` — the sensor said `unavailable`. Known missing, any duration.
    * silence longer than `max_gap` — nothing arrived for suspiciously long.
    """
    gaps = _silence_gaps(samples, window_start, window_end, max_gap, reason)
    for start, end in explicit or []:
        gaps.append(
            SeriesGap(
                start_time=max(start, window_start),
                end_time=min(end, window_end),
                reason="The sensor reported itself unavailable during this period.",
            )
        )
    return _merge_gaps(
        [gap for gap in gaps if gap.end_time > gap.start_time], window_start, window_end
    )


def _merge_gaps(
    gaps: list[SeriesGap], window_start: datetime, window_end: datetime
) -> list[SeriesGap]:
    ordered = sorted(gaps, key=lambda gap: gap.start_time)
    merged: list[SeriesGap] = []
    for gap in ordered:
        if merged and gap.start_time <= merged[-1].end_time:
            if gap.end_time > merged[-1].end_time:
                merged[-1] = SeriesGap(
                    start_time=merged[-1].start_time,
                    end_time=gap.end_time,
                    reason=merged[-1].reason,
                )
            continue
        merged.append(gap)
    return merged


def _silence_gaps(
    samples: list[NormalizedSample],
    window_start: datetime,
    window_end: datetime,
    max_gap: timedelta,
    reason: str,
) -> list[SeriesGap]:
    if not samples:
        return [
            SeriesGap(
                start_time=window_start,
                end_time=window_end,
                reason="No samples were recorded for this stream.",
            )
        ]

    ordered = sorted(samples, key=lambda sample: sample.timestamp)
    gaps: list[SeriesGap] = []

    if ordered[0].timestamp - window_start > max_gap:
        gaps.append(
            SeriesGap(start_time=window_start, end_time=ordered[0].timestamp, reason=reason)
        )

    for previous, current in zip(ordered, ordered[1:]):
        if current.timestamp - previous.timestamp > max_gap:
            gaps.append(
                SeriesGap(
                    start_time=previous.timestamp, end_time=current.timestamp, reason=reason
                )
            )

    if window_end - ordered[-1].timestamp > max_gap:
        gaps.append(
            SeriesGap(start_time=ordered[-1].timestamp, end_time=window_end, reason=reason)
        )

    return gaps


def coverage_fraction(gaps: list[SeriesGap], window_start: datetime, window_end: datetime) -> float:
    """Fraction of the window that is *not* covered by a gap."""
    total = (window_end - window_start).total_seconds()
    if total <= 0:
        return 0.0
    missing = 0.0
    for gap in gaps:
        start = max(gap.start_time, window_start)
        end = min(gap.end_time, window_end)
        if end > start:
            missing += (end - start).total_seconds()
    return max(0.0, min(1.0, 1.0 - missing / total))


def mean_and_sd(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, 0.0
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return mean, variance**0.5
