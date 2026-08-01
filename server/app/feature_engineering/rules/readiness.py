"""Physiological readiness.

This lane carries whatever composite score the provider itself publishes
(readiness, Body Battery, recovery, ...). It is deliberately *not* called
"energy": that would imply a subjective report no connected source supplies.
The lane hides itself when the provider has no such metric.
"""

from __future__ import annotations

from ...models.timeline import Lane, SeriesPoint, TimelineSeries
from ..context import RuleContext
from ..provenance import build_provenance, detect_gaps

RULE_ID = "readiness.provider_score"

LANE = {
    "id": "readiness",
    "phenotype": "readiness",
    "label": "Physiological Readiness",
    "description": "Provider composite score",
    "accent": "purple",
}


def build_lane(context: RuleContext) -> Lane:
    lane = Lane(**LANE, available=False)
    payload = context.wearable

    if not payload.supports("readiness"):
        lane.unavailable_reason = (
            "The configured wearable provider does not publish a readiness, recovery "
            "or body-battery score."
        )
        return lane

    records = [
        record for record in payload.readiness if context.window.contains(record.timestamp)
    ]
    if not records:
        lane.unavailable_reason = "No readiness scores were available for this day."
        return lane

    records.sort(key=lambda record: record.timestamp)
    samples = context.normalized.samples_for("readiness")

    # Some providers publish a curve (Body Battery), others a single figure each
    # morning (training readiness). Gap-detecting a lone daily value would
    # hatch out the whole day and imply a broken sensor, so sparse series are
    # drawn as the points they are.
    sparse = len(records) < 3
    gaps = (
        []
        if sparse
        else detect_gaps(
            [sample for sample in samples if context.window.contains(sample.timestamp)],
            context.window.start,
            context.window.end,
            context.max_gap * 12,
            reason="The provider published no readiness score in this period.",
        )
    )

    first = records[0]
    series = TimelineSeries(
        id="series_readiness",
        phenotype="readiness",
        label=first.metric.replace("_", " ").title(),
        unit=f"{first.scale_min:.0f}–{first.scale_max:.0f}",
        source=payload.source_id,
        device=payload.device,
        measured_or_derived="derived",
        points=[
            SeriesPoint(timestamp=record.timestamp, value=record.score) for record in records
        ],
        gaps=gaps,
        min_value=first.scale_min,
        max_value=first.scale_max,
        metadata={
            "metric": first.metric,
            "scaleMin": first.scale_min,
            "scaleMax": first.scale_max,
            "contributors": first.contributors,
            "note": (
                "This is the provider's own composite score. It is a derived quantity, "
                "not a direct measurement, and not a self-reported energy level."
                + (
                    " The provider published it once for the day rather than as a "
                    "curve, so it is drawn as individual points."
                    if sparse
                    else ""
                )
            ),
            "sparse": sparse,
            "pointDetails": [
                {
                    "timestamp": record.timestamp.isoformat(),
                    "score": record.score,
                    "contributors": record.contributors,
                }
                for record in records
            ],
        },
        provenance=build_provenance(
            rule=RULE_ID,
            version="1.0.0",
            raw_record_ids=[
                raw.id
                for raw in payload.raw_records
                if raw.stream == "readiness"
            ],
            input_range=(records[0].timestamp, records[-1].timestamp),
            thresholds={"scale_min": first.scale_min, "scale_max": first.scale_max},
            notes=[
                f"Provider metric '{first.metric}' passed through without rescaling.",
                "Marked as derived because the vendor computes it from other signals.",
            ],
        ),
    )

    lane.series = [series]
    lane.available = True
    lane.sources = [payload.source_id]
    lane.units = [series.unit]
    return lane
