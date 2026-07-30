"""Shape a stored `DayTimeline` for a particular consumer.

The MCP tools use this to keep responses small — a language model rarely needs
288 heart-rate samples and every provenance record. The frontend fetches the
full payload straight from the local API instead.
"""

from __future__ import annotations

from datetime import timedelta

from ..models.timeline import DayTimeline, SeriesPoint, TimelineSeries


def project(
    timeline: DayTimeline,
    *,
    lanes: list[str] | None = None,
    sampling_interval_minutes: float | None = None,
    include_raw_metadata: bool = True,
    include_provenance: bool = True,
) -> DayTimeline:
    result = timeline.model_copy(deep=True)

    if lanes:
        wanted = {lane_id.strip() for lane_id in lanes}
        result.lanes = [lane for lane in result.lanes if lane.id in wanted]

    for lane in result.lanes:
        if sampling_interval_minutes:
            lane.series = [
                _downsample(series, sampling_interval_minutes) for series in lane.series
            ]
        if not include_provenance:
            for event in lane.events:
                event.provenance = None
            for series in lane.series:
                series.provenance = None
        if not include_raw_metadata:
            for event in lane.events:
                event.metadata = {}
            for series in lane.series:
                series.metadata = {}

    return result


def _downsample(series: TimelineSeries, interval_minutes: float) -> TimelineSeries:
    """Keep the first sample in each bucket; never bridge a declared gap."""
    if interval_minutes <= 0 or not series.points:
        return series

    step = timedelta(minutes=interval_minutes)
    kept: list[SeriesPoint] = [series.points[0]]
    for point in series.points[1:]:
        if point.timestamp - kept[-1].timestamp >= step:
            kept.append(point)
    if kept[-1] is not series.points[-1]:
        kept.append(series.points[-1])

    reduced = series.model_copy(deep=True)
    reduced.points = kept
    reduced.metadata = dict(reduced.metadata)
    reduced.metadata["downsampledToMinutes"] = interval_minutes
    reduced.metadata["originalPointCount"] = len(series.points)
    return reduced


def available_lane_ids(timeline: DayTimeline) -> list[str]:
    return [lane.id for lane in timeline.lanes if lane.available]
