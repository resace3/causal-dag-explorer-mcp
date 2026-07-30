"""Generic JSON-file wearable provider.

Point `wearable.json_file.path` at an export produced by any tooling that can
emit the schema below. This is the fastest way to get real data into the
timeline without writing a vendor API client.

    {
      "provider": "apple-health-export",
      "device": "Apple Watch Series 9",
      "capabilities": ["sleep", "heart_rate", "activity"],
      "sleep":       [{"id": "...", "start": "...", "end": "...", "stages": [...]}],
      "heart_rate":  [{"timestamp": "...", "bpm": 62}],
      "hrv":         [{"timestamp": "...", "value": 54, "metric": "rmssd"}],
      "activity":    [{"id": "...", "activityType": "running", "label": "Run", ...}],
      "temperature": [{"timestamp": "...", "value": 93.1, "measurement": "skin_temperature"}],
      "readiness":   [{"timestamp": "...", "score": 78}]
    }

Timestamps must be ISO 8601 with an offset. Keys may be snake_case or camelCase.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .base import (
    ActivityRecord,
    BaseWearableProvider,
    HeartRatePoint,
    HRVPoint,
    ReadinessRecord,
    TemperaturePoint,
    WearableCapabilities,
    WearableProviderError,
    WearableSleepRecord,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

PROVIDER_NAME = "json_file"


class JsonFileWearableProvider(BaseWearableProvider):
    name = PROVIDER_NAME

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._payload: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._payload is not None:
            return self._payload
        if not self.path.exists():
            raise WearableProviderError(
                f"Wearable export not found at {self.path}. Set "
                "wearable.json_file.path in config.yaml or switch wearable.provider to 'mock'."
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WearableProviderError(
                f"{self.path.name} is not valid JSON (line {exc.lineno}, column {exc.colno})."
            ) from exc
        if not isinstance(payload, dict):
            raise WearableProviderError(
                f"{self.path.name} must contain a JSON object at the top level."
            )
        self._payload = payload
        return payload

    def _parse(self, key: str, model: type[ModelT]) -> list[ModelT]:
        rows = self._load().get(key) or []
        if not isinstance(rows, list):
            raise WearableProviderError(f"'{key}' in {self.path.name} must be a JSON array.")
        parsed: list[ModelT] = []
        for index, row in enumerate(rows):
            try:
                parsed.append(model.model_validate(row))
            except ValidationError as exc:
                first = exc.errors()[0]
                location = ".".join(str(part) for part in first["loc"])
                raise WearableProviderError(
                    f"{self.path.name}: {key}[{index}].{location} — {first['msg']}"
                ) from exc
        return parsed

    @staticmethod
    def _in_range(moment: datetime, start: datetime, end: datetime) -> bool:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return start <= moment < end

    async def get_capabilities(self) -> WearableCapabilities:
        payload = self._load()
        declared = payload.get("capabilities")
        if not declared:
            declared = [
                key
                for key in ("sleep", "heart_rate", "hrv", "activity", "temperature", "readiness")
                if payload.get(key)
            ]
        return WearableCapabilities(
            provider=str(payload.get("provider") or PROVIDER_NAME),
            device=payload.get("device"),
            capabilities=list(declared),
            status="connected",
            detail=f"Reading {self.path.name}",
        )

    async def get_sleep(self, start: datetime, end: datetime) -> list[WearableSleepRecord]:
        return [
            record
            for record in self._parse("sleep", WearableSleepRecord)
            if record.end > start and record.start < end
        ]

    async def get_heart_rate(self, start: datetime, end: datetime) -> list[HeartRatePoint]:
        return [
            point
            for point in self._parse("heart_rate", HeartRatePoint)
            if self._in_range(point.timestamp, start, end)
        ]

    async def get_hrv(self, start: datetime, end: datetime) -> list[HRVPoint]:
        return [
            point
            for point in self._parse("hrv", HRVPoint)
            if self._in_range(point.timestamp, start, end)
        ]

    async def get_activity(self, start: datetime, end: datetime) -> list[ActivityRecord]:
        return [
            record
            for record in self._parse("activity", ActivityRecord)
            if record.end > start and record.start < end
        ]

    async def get_temperature(self, start: datetime, end: datetime) -> list[TemperaturePoint]:
        return [
            point
            for point in self._parse("temperature", TemperaturePoint)
            if self._in_range(point.timestamp, start, end)
        ]

    async def get_readiness(self, start: datetime, end: datetime) -> list[ReadinessRecord]:
        return [
            record
            for record in self._parse("readiness", ReadinessRecord)
            if self._in_range(record.timestamp, start, end)
        ]
