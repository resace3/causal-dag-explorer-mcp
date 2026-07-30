"""Wearable data that reaches the timeline through Home Assistant.

Fitbit, Withings and Google Fit integrations publish the night's sleep as a
handful of once-a-day summary sensors rather than a stage-by-stage record:

    sensor.<user>_sleep_start_time      "02:11"   (local wall clock)
    sensor.<user>_sleep_time_in_bed     405       (minutes)
    sensor.<user>_sleep_minutes_asleep  344
    sensor.<user>_sleep_efficiency      85        (%)

This provider reconstructs one sleep interval from those values and reports it
as `derived`, because the interval is inferred from a clock string plus a
duration rather than read from a stage record.

It deliberately declares *only* the capabilities it can honestly serve. A daily
resting heart rate is not a heart-rate series, so `get_heart_rate` returns
nothing here; the resting value is handled as its own Home Assistant stream.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ...config.schema import HomeAssistantWearableConfig
from ..home_assistant.client import HomeAssistantClient, HomeAssistantError
from .base import (
    CAPABILITY_SLEEP,
    BaseWearableProvider,
    WearableCapabilities,
    WearableProviderError,
    WearableSleepRecord,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "home_assistant"

EMPTY_STATES = {"", "unknown", "unavailable", "none", "0"}


def _parse_clock(value: str) -> time | None:
    """Parse an `HH:MM` (or `HH:MM:SS`) wall-clock sensor state."""
    text = value.strip()
    if not text or ":" not in text:
        return None
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (ValueError, IndexError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def _parse_number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


class HomeAssistantWearableProvider(BaseWearableProvider):
    name = PROVIDER_NAME

    def __init__(
        self,
        config: HomeAssistantWearableConfig,
        client: HomeAssistantClient | None,
        tz: ZoneInfo,
    ) -> None:
        self.config = config
        self.client = client
        self.tz = tz

    # -- capabilities ----------------------------------------------------

    async def get_capabilities(self) -> WearableCapabilities:
        entity_ids = self.config.entity_ids()
        if self.client is None:
            raise WearableProviderError(
                "The 'home_assistant' wearable provider needs HOME_ASSISTANT_URL and "
                "HOME_ASSISTANT_TOKEN to be set in .env."
            )
        if not self.config.sleep.start_time:
            return WearableCapabilities(
                provider=PROVIDER_NAME,
                device=self.config.device_name,
                capabilities=[],
                status="connected",
                detail=(
                    "No wearable summary entities are mapped. Set "
                    "wearable.home_assistant.sleep.start_time in config.yaml."
                ),
            )
        return WearableCapabilities(
            provider=PROVIDER_NAME,
            device=self.config.device_name,
            capabilities=[CAPABILITY_SLEEP],
            status="connected",
            detail=(
                f"Reading {len(entity_ids)} wearable summary entities from Home Assistant. "
                "Only sleep is exposed this way; heart rate, HRV, temperature and "
                "readiness are not published as time series by this integration."
            ),
        )

    # -- sleep -----------------------------------------------------------

    async def get_sleep(self, start: datetime, end: datetime) -> list[WearableSleepRecord]:
        if self.client is None or not self.config.sleep.start_time:
            return []

        entity_ids = self.config.entity_ids()
        try:
            history = await self.client.get_history(entity_ids, start, end)
        except HomeAssistantError as exc:
            raise WearableProviderError(str(exc)) from exc

        by_entity: dict[str, list[tuple[datetime, str]]] = {}
        for group in history:
            # Only the first row of each group carries `entity_id`; later rows
            # are minimal. Carry it forward or every change after the first is
            # dropped.
            group_entity_id: str | None = None
            for row in group:
                entity_id = row.get("entity_id") or group_entity_id
                if row.get("entity_id"):
                    group_entity_id = entity_id
                stamp = row.get("last_changed") or row.get("last_updated")
                if not entity_id or not isinstance(stamp, str):
                    continue
                try:
                    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if moment.tzinfo is None:
                    continue
                by_entity.setdefault(entity_id, []).append(
                    (moment.astimezone(self.tz), str(row.get("state", "")))
                )

        for rows in by_entity.values():
            rows.sort(key=lambda item: item[0])

        reports = self._sleep_reports(by_entity)
        records: list[WearableSleepRecord] = []
        for report_time, clock in reports:
            record = self._build_record(report_time, clock, by_entity)
            if record is not None and record.end > start and record.start < end:
                records.append(record)

        # One integration can publish the same night more than once.
        unique: dict[str, WearableSleepRecord] = {}
        for record in sorted(records, key=lambda item: item.start):
            unique[record.start.isoformat()] = record
        return list(unique.values())

    def _sleep_reports(
        self, by_entity: dict[str, list[tuple[datetime, str]]]
    ) -> list[tuple[datetime, time]]:
        """Moments where the start-time sensor published a real clock value."""
        rows = by_entity.get(self.config.sleep.start_time or "", [])
        reports: list[tuple[datetime, time]] = []
        seen: set[str] = set()
        for moment, state in rows:
            clock = _parse_clock(state)
            if clock is None:
                continue
            key = clock.isoformat()
            if key in seen:
                continue
            seen.add(key)
            reports.append((moment, clock))
        return reports

    def _value_at(
        self,
        by_entity: dict[str, list[tuple[datetime, str]]],
        entity_id: str | None,
        moment: datetime,
    ) -> float | None:
        """The sensor's value as of `moment` (the last change at or before it)."""
        if not entity_id:
            return None
        best: float | None = None
        for stamp, state in by_entity.get(entity_id, []):
            if stamp > moment + timedelta(minutes=5):
                break
            if str(state).strip().lower() in EMPTY_STATES:
                continue
            number = _parse_number(state)
            if number is not None:
                best = number
        return best

    def _build_record(
        self,
        report_time: datetime,
        clock: time,
        by_entity: dict[str, list[tuple[datetime, str]]],
    ) -> WearableSleepRecord | None:
        sleep = self.config.sleep
        time_in_bed = self._value_at(by_entity, sleep.time_in_bed_minutes, report_time)
        minutes_asleep = self._value_at(by_entity, sleep.minutes_asleep, report_time)
        duration_minutes = time_in_bed or minutes_asleep
        if not duration_minutes or duration_minutes <= 0:
            return None

        # The clock time belongs to whichever date makes the night end at or
        # before the moment the integration published it.
        candidate = datetime.combine(report_time.date(), clock, tzinfo=self.tz)
        if candidate + timedelta(minutes=duration_minutes) > report_time + timedelta(minutes=5):
            candidate -= timedelta(days=1)

        end = candidate + timedelta(minutes=duration_minutes)
        efficiency = self._value_at(by_entity, sleep.efficiency, report_time)
        minutes_awake = self._value_at(by_entity, sleep.minutes_awake, report_time)
        awakenings = self._value_at(by_entity, sleep.awakenings, report_time)
        to_fall_asleep = self._value_at(by_entity, sleep.minutes_to_fall_asleep, report_time)

        return WearableSleepRecord(
            id=f"ha-sleep-{candidate.date().isoformat()}-{clock.strftime('%H%M')}",
            start=candidate,
            end=end,
            is_main_sleep=duration_minutes >= 120,
            efficiency=round(efficiency / 100, 3) if efficiency and efficiency > 1 else efficiency,
            score=None,
            time_in_bed_minutes=time_in_bed,
            awake_minutes=minutes_awake,
            stages=[],
            device=self.config.device_name,
            metadata={
                "reconstructedFrom": "daily sleep summary sensors",
                "reportedAt": report_time.isoformat(),
                "reportedStartClock": clock.strftime("%H:%M"),
                "minutesAsleep": minutes_asleep,
                "awakeningsCount": awakenings,
                "minutesToFallAsleep": to_fall_asleep,
                "sourceEntities": self.config.entity_ids(),
                "note": (
                    "Start and end are reconstructed from a clock-time sensor plus a "
                    "duration, so they are accurate to the minute the integration "
                    "reported. Sleep stages are not published by this integration."
                ),
            },
        )
