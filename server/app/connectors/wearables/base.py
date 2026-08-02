"""Wearable provider interface.

Adding a vendor means implementing `WearableProvider` and registering it in
`registry.py`. Nothing else in the application knows about specific vendors.

A provider must be honest about what it supports: `get_capabilities()` drives
which lanes the frontend offers, and a provider that cannot supply a metric
should return an empty list rather than fabricated values.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from ...models.timeline import CamelModel

# Capability tokens understood by the timeline builder.
CAPABILITY_SLEEP = "sleep"
CAPABILITY_HEART_RATE = "heart_rate"
CAPABILITY_HRV = "hrv"
CAPABILITY_ACTIVITY = "activity"
CAPABILITY_TEMPERATURE = "temperature"
CAPABILITY_READINESS = "readiness"
CAPABILITY_STEPS = "steps"

ALL_CAPABILITIES = (
    CAPABILITY_SLEEP,
    CAPABILITY_HEART_RATE,
    CAPABILITY_HRV,
    CAPABILITY_ACTIVITY,
    CAPABILITY_TEMPERATURE,
    CAPABILITY_READINESS,
    CAPABILITY_STEPS,
)


class WearableCapabilities(CamelModel):
    provider: str
    device: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    status: str = "connected"
    detail: str | None = None

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


class SleepStage(CamelModel):
    stage: str
    """`deep`, `light`, `rem`, `awake` — provider vocabulary is normalised upstream."""
    start: datetime
    end: datetime


class WearableSleepRecord(CamelModel):
    id: str
    start: datetime
    end: datetime
    is_main_sleep: bool = True
    efficiency: float | None = None
    score: float | None = None
    time_in_bed_minutes: float | None = None
    awake_minutes: float | None = None
    stages: list[SleepStage] = Field(default_factory=list)
    device: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HeartRatePoint(CamelModel):
    timestamp: datetime
    bpm: float
    context: str | None = None
    """e.g. `resting`, `workout` when the provider labels it."""


class HRVPoint(CamelModel):
    timestamp: datetime
    value: float
    metric: str = "rmssd"
    unit: str = "ms"
    window_start: datetime | None = None
    window_end: datetime | None = None
    baseline: float | None = None
    baseline_window_days: int | None = None


class ActivityRecord(CamelModel):
    id: str
    activity_type: str
    label: str
    start: datetime
    end: datetime
    steps: int | None = None
    distance_meters: float | None = None
    average_heart_rate: float | None = None
    max_heart_rate: float | None = None
    active_calories: float | None = None
    device: str | None = None
    detection: str = "workout_record"
    metadata: dict[str, Any] = Field(default_factory=dict)


class StepBucket(CamelModel):
    """Steps counted in one interval — a delta, not a running total.

    This is the shape a step *source* has natively: "37 steps between 18:24 and
    18:25". The daily counters that reach Home Assistant are the same data
    accumulated and resampled, which loses when the steps happened. A provider
    exposing this capability must send deltas; feeding a cumulative total in
    here would be differenced a second time and produce nonsense.
    """

    start: datetime
    end: datetime
    count: float
    device: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TemperaturePoint(CamelModel):
    timestamp: datetime
    value: float
    unit: str = "°F"
    measurement: str = "skin_temperature"
    """`skin_temperature`, `wrist_temperature_deviation`, `core_body_temperature`."""


class ReadinessRecord(CamelModel):
    timestamp: datetime
    score: float
    metric: str = "readiness_score"
    scale_min: float = 0
    scale_max: float = 100
    contributors: dict[str, Any] = Field(default_factory=dict)
    origin: str = "derived"
    """Vendor readiness scores are themselves derived quantities."""


@runtime_checkable
class WearableProvider(Protocol):
    """Every method receives timezone-aware datetimes and returns [start, end)."""

    name: str

    async def get_capabilities(self) -> WearableCapabilities: ...

    async def get_sleep(self, start: datetime, end: datetime) -> list[WearableSleepRecord]: ...

    async def get_heart_rate(self, start: datetime, end: datetime) -> list[HeartRatePoint]: ...

    async def get_hrv(self, start: datetime, end: datetime) -> list[HRVPoint]: ...

    async def get_activity(self, start: datetime, end: datetime) -> list[ActivityRecord]: ...

    async def get_temperature(self, start: datetime, end: datetime) -> list[TemperaturePoint]: ...

    async def get_readiness(self, start: datetime, end: datetime) -> list[ReadinessRecord]: ...

    async def get_steps(self, start: datetime, end: datetime) -> list[StepBucket]: ...


class BaseWearableProvider:
    """Convenience base returning empty results for unsupported metrics."""

    name = "base"

    async def get_capabilities(self) -> WearableCapabilities:  # pragma: no cover - abstract
        raise NotImplementedError

    async def get_sleep(self, start: datetime, end: datetime) -> list[WearableSleepRecord]:
        return []

    async def get_heart_rate(self, start: datetime, end: datetime) -> list[HeartRatePoint]:
        return []

    async def get_hrv(self, start: datetime, end: datetime) -> list[HRVPoint]:
        return []

    async def get_activity(self, start: datetime, end: datetime) -> list[ActivityRecord]:
        return []

    async def get_temperature(self, start: datetime, end: datetime) -> list[TemperaturePoint]:
        return []

    async def get_readiness(self, start: datetime, end: datetime) -> list[ReadinessRecord]:
        return []

    async def get_steps(self, start: datetime, end: datetime) -> list[StepBucket]:
        return []


class WearableProviderError(RuntimeError):
    """Raised when a provider cannot serve data; surfaced as a source error."""
