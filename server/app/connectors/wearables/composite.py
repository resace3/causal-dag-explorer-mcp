"""Use several wearable routes at once, in priority order.

People rarely have exactly one source. A Garmin MCP server and a Fitbit whose
daily summaries already reach Home Assistant can both be configured, and each
covers what the other misses — Garmin has stages and continuous heart rate when
the watch is worn, the Fitbit route has last night's sleep when it was not.

The merge is per-metric and first-non-empty: for each metric the providers are
asked in order, and the first one with data wins. Metrics are never blended, so
a heart-rate line always comes from a single device rather than being stitched
together from two, and every event keeps its own source and device.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .base import (
    ActivityRecord,
    BaseWearableProvider,
    HeartRatePoint,
    HRVPoint,
    ReadinessRecord,
    TemperaturePoint,
    WearableCapabilities,
    WearableProvider,
    WearableProviderError,
    WearableSleepRecord,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "auto"


class CompositeWearableProvider(BaseWearableProvider):
    name = PROVIDER_NAME

    def __init__(self, providers: list[tuple[str, WearableProvider]]) -> None:
        if not providers:
            raise ValueError("A composite wearable provider needs at least one provider")
        self.providers = providers
        self._capabilities: dict[str, WearableCapabilities] = {}
        self._errors: dict[str, str] = {}
        #: Which provider actually supplied each metric, for the source panel.
        self.contributions: dict[str, str] = {}

    async def get_capabilities(self) -> WearableCapabilities:
        merged: list[str] = []
        details: list[str] = []

        for name, provider in self.providers:
            try:
                capabilities = await provider.get_capabilities()
            except Exception as exc:  # noqa: BLE001 - one failure must not sink the rest
                self._errors[name] = str(exc)
                details.append(f"{name}: unavailable ({exc})")
                continue
            self._capabilities[name] = capabilities
            for capability in capabilities.capabilities:
                if capability not in merged:
                    merged.append(capability)
            details.append(f"{name}: {', '.join(capabilities.capabilities) or 'no metrics'}")

        if not self._capabilities:
            raise WearableProviderError(
                "No wearable route is available. " + " ".join(details)
            )

        return WearableCapabilities(
            provider=PROVIDER_NAME,
            device=" + ".join(
                capability.device or name
                for name, capability in self._capabilities.items()
            ),
            capabilities=merged,
            status="connected",
            detail="Routes tried in order — " + "; ".join(details) + ".",
        )

    async def _first(self, capability: str, method: str, start: datetime, end: datetime) -> list[Any]:
        for name, provider in self.providers:
            capabilities = self._capabilities.get(name)
            if capabilities is not None and not capabilities.supports(capability):
                continue
            try:
                result = await getattr(provider, method)(start, end)
            except WearableProviderError as exc:
                self._errors[name] = str(exc)
                continue
            except Exception as exc:  # noqa: BLE001
                self._errors[name] = f"{type(exc).__name__}: {exc}"
                continue
            if result:
                self.contributions[capability] = name
                return result
        return []

    async def get_sleep(self, start: datetime, end: datetime) -> list[WearableSleepRecord]:
        return await self._first("sleep", "get_sleep", start, end)

    async def get_heart_rate(self, start: datetime, end: datetime) -> list[HeartRatePoint]:
        return await self._first("heart_rate", "get_heart_rate", start, end)

    async def get_hrv(self, start: datetime, end: datetime) -> list[HRVPoint]:
        return await self._first("hrv", "get_hrv", start, end)

    async def get_activity(self, start: datetime, end: datetime) -> list[ActivityRecord]:
        return await self._first("activity", "get_activity", start, end)

    async def get_temperature(self, start: datetime, end: datetime) -> list[TemperaturePoint]:
        return await self._first("temperature", "get_temperature", start, end)

    async def get_readiness(self, start: datetime, end: datetime) -> list[ReadinessRecord]:
        return await self._first("readiness", "get_readiness", start, end)

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)
