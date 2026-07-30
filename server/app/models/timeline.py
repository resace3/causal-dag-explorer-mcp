"""The shared internal event schema.

Everything downstream of the connectors speaks these types: normalization emits
them, feature engineering annotates them, the API serialises them, and the
frontend mirrors them in `frontend/src/types/timeline.ts`.

All timestamps are timezone-aware and serialised as ISO 8601. Conversion to a
human-readable local time happens only in the presentation layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal["point", "interval", "continuous"]
Origin = Literal["measured", "derived"]

Phenotype = Literal[
    "activity",
    "heart_rate",
    "hrv",
    "readiness",
    "sleep",
    "temperature",
    "environment",
    "presence",
    "location",
]


class CamelModel(BaseModel):
    """Serialises to camelCase for the TypeScript client, accepts either form."""

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=lambda field: "".join(
            part if index == 0 else part.capitalize()
            for index, part in enumerate(field.split("_"))
        ),
    )


class Provenance(CamelModel):
    """Why a derived feature exists, and what it was derived from."""

    raw_record_ids: list[str] = Field(default_factory=list)
    source_entity_ids: list[str] = Field(default_factory=list)
    transformation_rule: str | None = None
    rule_version: str | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)
    input_time_range: list[str] | None = None
    output_timestamp: str | None = None
    missing_data_assumptions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TimelineEvent(CamelModel):
    """A point or interval that occupies a lane."""

    id: str
    phenotype: str
    label: str
    event_type: EventType
    start_time: datetime
    end_time: datetime | None = None
    value: float | str | None = None
    unit: str | None = None
    source: str
    device: str | None = None
    entity_id: str | None = None
    measured_or_derived: Origin
    confidence: float | None = None
    data_quality: Literal["high", "medium", "low", "unknown"] = "unknown"
    category: str | None = None
    """Sub-kind used by the renderer, e.g. `workout`, `nap`, `light_bright`."""
    continues_before: bool = False
    continues_after: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()


class SeriesPoint(CamelModel):
    timestamp: datetime
    value: float
    quality: float | None = None


class SeriesGap(CamelModel):
    """An interval where a continuous stream had no samples."""

    start_time: datetime
    end_time: datetime
    reason: str | None = None


class TimelineSeries(CamelModel):
    """A continuous measurement rendered as a line."""

    id: str
    phenotype: str
    label: str
    unit: str
    source: str
    device: str | None = None
    entity_id: str | None = None
    measured_or_derived: Origin = "measured"
    points: list[SeriesPoint] = Field(default_factory=list)
    gaps: list[SeriesGap] = Field(default_factory=list)
    min_value: float | None = None
    max_value: float | None = None
    style: Literal["primary", "secondary"] = "primary"
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None


class Lane(CamelModel):
    """One horizontal swimlane."""

    id: str
    phenotype: str
    label: str
    description: str
    accent: str
    """Semantic colour token resolved by the frontend, e.g. `green`."""
    available: bool = True
    unavailable_reason: str | None = None
    units: list[str] = Field(default_factory=list)
    events: list[TimelineEvent] = Field(default_factory=list)
    series: list[TimelineSeries] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class CoverageWindow(CamelModel):
    start_time: datetime
    end_time: datetime
    label: str


class DayCoverage(CamelModel):
    """How much of the day each stream actually observed."""

    overall_fraction: float = 0.0
    per_lane: dict[str, float] = Field(default_factory=dict)
    missing_periods: list[CoverageWindow] = Field(default_factory=list)


class SyncSummary(CamelModel):
    date_processed: str
    local_timezone: str
    day_start: datetime
    day_end: datetime
    day_length_hours: float
    sources_checked: list[str] = Field(default_factory=list)
    raw_record_count: int = 0
    normalized_event_count: int = 0
    derived_feature_count: int = 0
    series_point_count: int = 0
    coverage: DayCoverage = Field(default_factory=DayCoverage)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DayTimeline(CamelModel):
    """The payload the Yesterday page renders."""

    date: str
    local_timezone: str
    day_start: datetime
    day_end: datetime
    day_length_hours: float
    generated_at: datetime
    lanes: list[Lane] = Field(default_factory=list)
    summary: SyncSummary
    highlights: list[str] = Field(default_factory=list)
    """Neutral temporal descriptions. Never causal claims."""
    mock_data: bool = False
