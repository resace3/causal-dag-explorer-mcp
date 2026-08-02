"""Adapter between a `WearableProvider` and the rest of the pipeline.

Provider records are kept in their typed form for feature engineering, and are
*also* mirrored into `RawRecord`s so every timeline event can point at the
evidence it came from.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from ...models.raw import RawRecord
from ...models.sources import SourceStatus
from .base import (
    ActivityRecord,
    HeartRatePoint,
    HRVPoint,
    ReadinessRecord,
    StepBucket,
    TemperaturePoint,
    WearableCapabilities,
    WearableProvider,
    WearableProviderError,
    WearableSleepRecord,
)

logger = logging.getLogger(__name__)

SOURCE_PREFIX = "wearable"


@dataclass
class WearablePayload:
    sleep: list[WearableSleepRecord] = field(default_factory=list)
    heart_rate: list[HeartRatePoint] = field(default_factory=list)
    hrv: list[HRVPoint] = field(default_factory=list)
    activity: list[ActivityRecord] = field(default_factory=list)
    temperature: list[TemperaturePoint] = field(default_factory=list)
    readiness: list[ReadinessRecord] = field(default_factory=list)
    steps: list[StepBucket] = field(default_factory=list)
    raw_records: list[RawRecord] = field(default_factory=list)
    capabilities: WearableCapabilities | None = None
    status: SourceStatus = "disconnected"
    detail: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def source_id(self) -> str:
        provider = self.capabilities.provider if self.capabilities else "unknown"
        return f"{SOURCE_PREFIX}:{provider}"

    @property
    def device(self) -> str | None:
        return self.capabilities.device if self.capabilities else None

    def supports(self, capability: str) -> bool:
        return bool(self.capabilities and self.capabilities.supports(capability))


class WearableConnector:
    def __init__(self, provider: WearableProvider) -> None:
        self.provider = provider

    async def fetch(self, start: datetime, end: datetime) -> WearablePayload:
        payload = WearablePayload()

        try:
            capabilities = await self.provider.get_capabilities()
        except WearableProviderError as exc:
            payload.status = "error"
            payload.detail = str(exc)
            payload.errors.append(str(exc))
            return payload
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never crashes sync
            message = (
                f"The '{getattr(self.provider, 'name', 'wearable')}' provider failed while "
                f"reporting capabilities: {exc}"
            )
            payload.status = "error"
            payload.detail = message
            payload.errors.append(message)
            return payload

        payload.capabilities = capabilities
        payload.status = "mock_data" if capabilities.status == "mock_data" else "connected"
        payload.detail = capabilities.detail

        fetchers = (
            ("sleep", self.provider.get_sleep, "sleep"),
            ("heart_rate", self.provider.get_heart_rate, "heart_rate"),
            ("hrv", self.provider.get_hrv, "hrv"),
            ("activity", self.provider.get_activity, "activity"),
            ("temperature", self.provider.get_temperature, "temperature"),
            ("readiness", self.provider.get_readiness, "readiness"),
            ("steps", self.provider.get_steps, "steps"),
        )

        for capability, fetch, attribute in fetchers:
            if not capabilities.supports(capability):
                continue
            try:
                setattr(payload, attribute, await fetch(start, end))
            except WearableProviderError as exc:
                payload.warnings.append(f"{capability}: {exc}")
            except Exception as exc:  # noqa: BLE001
                payload.warnings.append(
                    f"The wearable provider failed to return {capability} data: {exc}"
                )

        payload.raw_records = self._mirror_raw_records(payload)
        return payload

    def _mirror_raw_records(self, payload: WearablePayload) -> list[RawRecord]:
        source = payload.source_id
        device = payload.device
        records: list[RawRecord] = []

        for record in payload.sleep:
            records.append(
                RawRecord(
                    id=RawRecord.make_id(source, "sleep", record.id),
                    source=source,
                    stream="sleep",
                    device=record.device or device,
                    timestamp=record.start,
                    end_timestamp=record.end,
                    value="main_sleep" if record.is_main_sleep else "nap",
                    attributes=record.model_dump(mode="json"),
                )
            )
        for point in payload.heart_rate:
            records.append(
                RawRecord(
                    id=RawRecord.make_id(source, "heart_rate", point.timestamp.isoformat()),
                    source=source,
                    stream="heart_rate",
                    device=device,
                    timestamp=point.timestamp,
                    value=point.bpm,
                    unit="bpm",
                    attributes={"context": point.context},
                )
            )
        for point in payload.hrv:
            records.append(
                RawRecord(
                    id=RawRecord.make_id(source, "hrv", point.timestamp.isoformat()),
                    source=source,
                    stream="hrv",
                    device=device,
                    timestamp=point.timestamp,
                    value=point.value,
                    unit=point.unit,
                    attributes=point.model_dump(mode="json"),
                )
            )
        for record in payload.activity:
            records.append(
                RawRecord(
                    id=RawRecord.make_id(source, "activity", record.id),
                    source=source,
                    stream="activity",
                    device=record.device or device,
                    timestamp=record.start,
                    end_timestamp=record.end,
                    value=record.activity_type,
                    attributes=record.model_dump(mode="json"),
                )
            )
        for point in payload.temperature:
            records.append(
                RawRecord(
                    id=RawRecord.make_id(source, "skin_temperature", point.timestamp.isoformat()),
                    source=source,
                    stream="skin_temperature",
                    device=device,
                    timestamp=point.timestamp,
                    value=point.value,
                    unit=point.unit,
                    attributes={"measurement": point.measurement},
                )
            )
        for bucket in payload.steps:
            records.append(
                RawRecord(
                    id=RawRecord.make_id(source, "step_bucket", bucket.start.isoformat()),
                    source=source,
                    stream="step_bucket",
                    device=bucket.device or device,
                    timestamp=bucket.start,
                    end_timestamp=bucket.end,
                    value=bucket.count,
                    unit="steps",
                    attributes=bucket.model_dump(mode="json"),
                )
            )
        for record in payload.readiness:
            records.append(
                RawRecord(
                    id=RawRecord.make_id(source, "readiness", record.timestamp.isoformat()),
                    source=source,
                    stream="readiness",
                    device=device,
                    timestamp=record.timestamp,
                    value=record.score,
                    unit="score",
                    attributes=record.model_dump(mode="json"),
                )
            )

        records.sort(key=lambda record: (record.stream, record.timestamp))
        return records
