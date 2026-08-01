"""Heart-rate variability.

Most wearables report a single nightly HRV value. That value is rendered as one
point attached to the sleep period it summarises — an hourly curve is never
fabricated from it.
"""

from __future__ import annotations

from ...models.timeline import Lane, TimelineEvent
from ..context import RuleContext, sort_events
from ..provenance import build_provenance

RULE_ID = "hrv.nightly_value"

LANE = {
    "id": "hrv",
    "phenotype": "hrv",
    "label": "Heart Rate Variability",
    "description": "Nightly beat-to-beat variation",
    "accent": "indigo",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)
    payload = context.wearable

    if not payload.supports("hrv"):
        lane.unavailable_reason = "The configured wearable provider does not expose HRV."
        return lane
    if not payload.hrv:
        lane.unavailable_reason = "No HRV data was available for this day."
        return lane

    events: list[TimelineEvent] = []
    for point in payload.hrv:
        if not context.window.contains(point.timestamp):
            continue

        deviation = None
        if point.baseline:
            deviation = round(point.value - point.baseline, 1)

        window_note = None
        if point.window_start and point.window_end:
            window_note = (
                f"Summarises {point.window_start.isoformat()} to {point.window_end.isoformat()}"
            )

        metric_label = {"rmssd": "RMSSD", "sdnn": "SDNN"}.get(
            point.metric.lower(), point.metric.upper()
        )

        events.append(
            TimelineEvent(
                id=f"hrv_{int(point.timestamp.timestamp())}",
                phenotype="hrv",
                label=f"Nightly HRV ({metric_label})",
                event_type="point",
                start_time=point.timestamp,
                value=point.value,
                unit=point.unit,
                source=payload.source_id,
                device=payload.device,
                measured_or_derived="measured",
                confidence=0.9,
                data_quality="high",
                category="nightly_hrv",
                metadata={
                    "metric": metric_label,
                    "coversSleepStart": point.window_start.isoformat()
                    if point.window_start
                    else None,
                    "coversSleepEnd": point.window_end.isoformat()
                    if point.window_end
                    else None,
                    "personalBaseline": point.baseline,
                    "baselineWindowDays": point.baseline_window_days,
                    "deviationFromBaseline": deviation,
                    "note": (
                        "One value per night. The point is placed at the midpoint of the "
                        "sleep period it summarises; it is not an hourly measurement."
                    ),
                },
                provenance=build_provenance(
                    rule=RULE_ID,
                    version="1.0.0",
                    raw_record_ids=[
                        raw.id
                        for raw in payload.raw_records
                        if raw.stream == "hrv" and raw.timestamp == point.timestamp
                    ],
                    input_range=(
                        (point.window_start, point.window_end)
                        if point.window_start and point.window_end
                        else None
                    ),
                    output_timestamp=point.timestamp,
                    assumptions=[
                        "A single nightly value is not expanded into a time series."
                    ],
                    notes=[note for note in [window_note] if note],
                ),
            )
        )

    lane.events = sort_events(events)
    lane.available = bool(events)
    lane.sources = [payload.source_id]
    lane.units = [payload.hrv[0].unit] if payload.hrv else []
    if not events:
        lane.unavailable_reason = (
            "HRV was recorded outside the displayed day, so nothing falls in this window."
        )
    return lane
