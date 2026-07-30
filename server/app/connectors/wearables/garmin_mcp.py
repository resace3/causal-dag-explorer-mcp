"""Wearable data read from the Garmin MCP server.

Garmin Connect exposes a genuinely rich day — a stage-by-stage hypnogram,
two-minute heart rate, Body Battery, and real activity records — so this is the
one provider that can fill every lane.

Only read-only `get_*` tools are called, and the allow-list below is enforced by
`McpStdioSession`. The same server also exposes tools that create workouts and
delete courses; this application must never reach them.

Garmin returns `null`-filled envelopes for a day it has no data for. That is a
real answer — "the watch wasn't worn" — and is reported as an empty result, not
an error, so the lanes hide themselves with an honest reason.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ...config.schema import GarminMcpConfig, McpServerConfig
from ..mcp_client import McpClientError, McpStdioSession, open_session
from .base import (
    CAPABILITY_ACTIVITY,
    CAPABILITY_HEART_RATE,
    CAPABILITY_HRV,
    CAPABILITY_READINESS,
    CAPABILITY_SLEEP,
    ActivityRecord,
    BaseWearableProvider,
    HeartRatePoint,
    HRVPoint,
    ReadinessRecord,
    SleepStage,
    WearableCapabilities,
    WearableProviderError,
    WearableSleepRecord,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "garmin_mcp"

#: Every tool this provider may call. Nothing that writes is listed.
ALLOWED_TOOLS = frozenset(
    {
        "get_sleep_data",
        "get_heart_rates",
        "get_activities_by_date",
        "get_body_battery",
        "get_training_readiness",
        "get_rhr_day",
        "get_hrv_data",
        "get_stats",
        "get_user_summary",
    }
)

# Garmin sleep-level codes -> the vocabulary the timeline uses.
SLEEP_LEVELS = {0: "deep", 1: "light", 2: "rem", 3: "awake"}

ACTIVITY_LABELS = {
    "running": "Run",
    "treadmill_running": "Treadmill run",
    "cycling": "Ride",
    "indoor_cycling": "Indoor ride",
    "walking": "Walk",
    "hiking": "Hike",
    "lap_swimming": "Swim",
    "strength_training": "Strength training",
    "yoga": "Yoga",
    "e_sport": "Gaming session",
}


def _parse_stamp(value: Any, tz: ZoneInfo) -> datetime | None:
    """Garmin mixes epoch milliseconds and `YYYY-MM-DD HH:MM:SS` local strings."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).astimezone(tz)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        for candidate in (text, text.replace(" ", "T")):
            try:
                parsed = datetime.fromisoformat(candidate)
            except ValueError:
                continue
            # Garmin's `...Local` fields are wall-clock with no offset.
            return parsed.astimezone(tz) if parsed.tzinfo else parsed.replace(tzinfo=tz)
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


class GarminMcpProvider(BaseWearableProvider):
    """Implements `WearableProvider` by calling the Garmin MCP server."""

    name = PROVIDER_NAME

    def __init__(
        self, config: GarminMcpConfig, server: McpServerConfig, tz: ZoneInfo
    ) -> None:
        self.config = config
        self.server = server
        self.tz = tz
        self._cache: dict[str, Any] = {}
        self._capabilities: WearableCapabilities | None = None
        self._loaded_for: tuple[date, date] | None = None

    # -- session ---------------------------------------------------------

    async def _load(self, start: datetime, end: datetime) -> dict[str, Any]:
        """Fetch every metric for the covered dates inside one MCP session."""
        first = start.astimezone(self.tz).date()
        last = end.astimezone(self.tz).date()
        if self._loaded_for == (first, last):
            return self._cache

        days: list[date] = []
        cursor = first
        while cursor <= last:
            days.append(cursor)
            cursor += timedelta(days=1)

        payload: dict[str, Any] = {
            "sleep": {},
            "heart_rate": {},
            "body_battery": [],
            "readiness": {},
            "activities": [],
            "tools": [],
        }

        try:
            async with open_session(
                self.config.mcp_server,
                self.server,
                ALLOWED_TOOLS,
                startup_timeout=self.server.startup_timeout_seconds,
            ) as session:
                payload["tools"] = await session.list_tools()

                for day in days:
                    iso = day.isoformat()
                    payload["sleep"][iso] = await session.call_json(
                        "get_sleep_data", {"date": iso}
                    )
                    payload["heart_rate"][iso] = await session.call_json(
                        "get_heart_rates", {"date": iso}
                    )
                    payload["readiness"][iso] = await session.call_json(
                        "get_training_readiness", {"date": iso}
                    )

                payload["body_battery"] = (
                    await session.call_json(
                        "get_body_battery",
                        {"start_date": first.isoformat(), "end_date": last.isoformat()},
                    )
                    or []
                )
                payload["activities"] = (
                    await session.call_json(
                        "get_activities_by_date",
                        {"start_date": first.isoformat(), "end_date": last.isoformat()},
                    )
                    or {}
                )
        except McpClientError as exc:
            raise WearableProviderError(str(exc)) from exc

        self._cache = payload
        self._loaded_for = (first, last)
        return payload

    # -- capabilities ----------------------------------------------------

    async def get_capabilities(self) -> WearableCapabilities:
        if self._capabilities is not None:
            return self._capabilities

        if not self.server.enabled:
            raise WearableProviderError(
                f"The '{self.config.mcp_server}' MCP server is disabled in config.yaml."
            )

        # Probing capabilities is a session in itself, so ask for today's window
        # and reuse whatever it loads.
        now = datetime.now(self.tz)
        payload = await self._load(now - timedelta(days=1), now)
        tools = set(payload.get("tools") or [])

        capabilities: list[str] = []
        if "get_sleep_data" in tools:
            capabilities.extend([CAPABILITY_SLEEP, CAPABILITY_HRV])
        if "get_heart_rates" in tools:
            capabilities.append(CAPABILITY_HEART_RATE)
        if "get_activities_by_date" in tools:
            capabilities.append(CAPABILITY_ACTIVITY)
        if "get_body_battery" in tools or "get_training_readiness" in tools:
            capabilities.append(CAPABILITY_READINESS)

        self._capabilities = WearableCapabilities(
            provider=PROVIDER_NAME,
            device=self.config.device_name,
            capabilities=capabilities,
            status="connected",
            detail=(
                f"Connected to the '{self.config.mcp_server}' MCP server "
                f"({len(tools)} tools). Only read-only get_* tools are called."
            ),
        )
        return self._capabilities

    # -- sleep -----------------------------------------------------------

    async def get_sleep(self, start: datetime, end: datetime) -> list[WearableSleepRecord]:
        payload = await self._load(start, end)
        records: list[WearableSleepRecord] = []

        for iso, blob in (payload.get("sleep") or {}).items():
            if not isinstance(blob, dict):
                continue
            daily = blob.get("dailySleepDTO") or {}
            begin = _parse_stamp(
                daily.get("sleepStartTimestampLocal") or daily.get("autoSleepStartTimestampGMT"),
                self.tz,
            )
            finish = _parse_stamp(
                daily.get("sleepEndTimestampLocal") or daily.get("autoSleepEndTimestampGMT"),
                self.tz,
            )
            if begin is None or finish is None or finish <= begin:
                continue  # Garmin returns a null envelope when nothing was recorded.
            if finish <= start or begin >= end:
                continue

            stages: list[SleepStage] = []
            for level in blob.get("sleepLevels") or []:
                stage_start = _parse_stamp(level.get("startGMT"), self.tz)
                stage_end = _parse_stamp(level.get("endGMT"), self.tz)
                name = SLEEP_LEVELS.get(int(level.get("activityLevel", -1) or -1))
                if stage_start and stage_end and name and stage_end > stage_start:
                    stages.append(SleepStage(stage=name, start=stage_start, end=stage_end))

            total = _number(daily.get("sleepTimeSeconds"))
            awake = _number(daily.get("awakeSleepSeconds"))
            in_bed = (finish - begin).total_seconds() / 60

            records.append(
                WearableSleepRecord(
                    id=f"garmin-sleep-{iso}",
                    start=begin,
                    end=finish,
                    is_main_sleep=True,
                    efficiency=(
                        round(total / (total + awake), 3)
                        if total and awake is not None and (total + awake) > 0
                        else None
                    ),
                    score=_number((blob.get("sleepScores") or {}).get("overall", {}).get("value"))
                    if isinstance(blob.get("sleepScores"), dict)
                    else None,
                    time_in_bed_minutes=round(in_bed, 1),
                    awake_minutes=round(awake / 60, 1) if awake is not None else None,
                    stages=stages,
                    device=self.config.device_name,
                    metadata={
                        "source": "Garmin Connect sleep record",
                        "deepMinutes": _minutes(daily.get("deepSleepSeconds")),
                        "lightMinutes": _minutes(daily.get("lightSleepSeconds")),
                        "remMinutes": _minutes(daily.get("remSleepSeconds")),
                        "awakeMinutes": _minutes(daily.get("awakeSleepSeconds")),
                        "napMinutes": _minutes(daily.get("napTimeSeconds")),
                        "stageCount": len(stages),
                    },
                )
            )

        records.sort(key=lambda record: record.start)
        return records

    # -- heart rate ------------------------------------------------------

    async def get_heart_rate(self, start: datetime, end: datetime) -> list[HeartRatePoint]:
        payload = await self._load(start, end)
        points: list[HeartRatePoint] = []

        for blob in (payload.get("heart_rate") or {}).values():
            if not isinstance(blob, dict):
                continue
            for row in blob.get("heartRateValues") or []:
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                moment = _parse_stamp(row[0], self.tz)
                bpm = _number(row[1])
                if moment is None or bpm is None or bpm <= 0:
                    continue
                if start <= moment < end:
                    points.append(HeartRatePoint(timestamp=moment, bpm=bpm))

        points.sort(key=lambda point: point.timestamp)
        return points

    # -- HRV -------------------------------------------------------------

    async def get_hrv(self, start: datetime, end: datetime) -> list[HRVPoint]:
        """Garmin reports overnight HRV as one figure attached to the sleep record."""
        payload = await self._load(start, end)
        points: list[HRVPoint] = []

        for blob in (payload.get("sleep") or {}).values():
            if not isinstance(blob, dict):
                continue
            summary = blob.get("hrvSummary") or {}
            value = _number(summary.get("lastNightAvg") or summary.get("weeklyAvg"))
            if value is None:
                continue
            daily = blob.get("dailySleepDTO") or {}
            begin = _parse_stamp(daily.get("sleepStartTimestampLocal"), self.tz)
            finish = _parse_stamp(daily.get("sleepEndTimestampLocal"), self.tz)
            if begin is None or finish is None:
                continue
            midpoint = begin + (finish - begin) / 2
            if not (start <= midpoint < end):
                continue
            points.append(
                HRVPoint(
                    timestamp=midpoint,
                    value=value,
                    metric="rmssd",
                    unit="ms",
                    window_start=begin,
                    window_end=finish,
                    baseline=_number(summary.get("baseline", {}).get("balancedLow"))
                    if isinstance(summary.get("baseline"), dict)
                    else None,
                )
            )
        return points

    # -- activity --------------------------------------------------------

    async def get_activity(self, start: datetime, end: datetime) -> list[ActivityRecord]:
        payload = await self._load(start, end)
        blob = payload.get("activities") or {}
        rows = blob.get("activities") if isinstance(blob, dict) else blob
        records: list[ActivityRecord] = []

        for row in rows or []:
            if not isinstance(row, dict):
                continue
            begin = _parse_stamp(row.get("start_time") or row.get("startTimeLocal"), self.tz)
            duration = _number(row.get("duration_seconds") or row.get("duration"))
            if begin is None or not duration:
                continue
            finish = begin + timedelta(seconds=duration)
            if finish <= start or begin >= end:
                continue

            kind = str(row.get("type") or row.get("activityType") or "activity")
            records.append(
                ActivityRecord(
                    id=f"garmin-activity-{row.get('id') or int(begin.timestamp())}",
                    activity_type=kind,
                    label=str(row.get("name") or ACTIVITY_LABELS.get(kind, kind.replace("_", " ").title())),
                    start=begin,
                    end=finish,
                    steps=int(_number(row.get("steps")) or 0) or None,
                    distance_meters=_number(row.get("distance_meters")),
                    average_heart_rate=_number(row.get("avg_hr_bpm")),
                    max_heart_rate=_number(row.get("max_hr_bpm")),
                    active_calories=_number(row.get("calories")),
                    device=self.config.device_name,
                    detection="workout_record",
                    metadata={
                        "garminActivityId": row.get("id"),
                        "eventType": row.get("event_type"),
                        "elevationGainMeters": _number(row.get("elevation_gain_meters")),
                        "movingDurationSeconds": _number(row.get("moving_duration_seconds")),
                    },
                )
            )

        records.sort(key=lambda record: record.start)
        return records

    # -- readiness -------------------------------------------------------

    async def get_readiness(self, start: datetime, end: datetime) -> list[ReadinessRecord]:
        payload = await self._load(start, end)
        records: list[ReadinessRecord] = []

        # Body Battery is a within-day curve, so it is the better readiness line.
        for entry in payload.get("body_battery") or []:
            if not isinstance(entry, dict):
                continue
            for event in entry.get("bodyBatteryValuesArray") or entry.get("events") or []:
                if isinstance(event, (list, tuple)) and len(event) >= 3:
                    moment = _parse_stamp(event[0], self.tz)
                    level = _number(event[2])
                elif isinstance(event, dict):
                    moment = _parse_stamp(event.get("timestamp") or event.get("startTimestampGMT"), self.tz)
                    level = _number(event.get("level") or event.get("bodyBatteryLevel"))
                else:
                    continue
                if moment is None or level is None or not (start <= moment < end):
                    continue
                records.append(
                    ReadinessRecord(
                        timestamp=moment,
                        score=level,
                        metric="body_battery",
                        scale_min=0,
                        scale_max=100,
                        contributors={"source": "Garmin Body Battery"},
                        origin="derived",
                    )
                )

        if records:
            records.sort(key=lambda record: record.timestamp)
            return records

        # Fall back to the once-a-day training-readiness score.
        for iso, blob in (payload.get("readiness") or {}).items():
            rows = blob if isinstance(blob, list) else [blob]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                score = _number(row.get("score"))
                moment = _parse_stamp(row.get("timestampLocal") or row.get("timestamp"), self.tz)
                if score is None or moment is None or not (start <= moment < end):
                    continue
                records.append(
                    ReadinessRecord(
                        timestamp=moment,
                        score=score,
                        metric="training_readiness",
                        scale_min=0,
                        scale_max=100,
                        contributors={
                            key: row.get(key)
                            for key in ("sleepScore", "hrvFactorPercent", "recoveryTime")
                            if row.get(key) is not None
                        },
                        origin="derived",
                    )
                )
        records.sort(key=lambda record: record.timestamp)
        return records


def _minutes(seconds: Any) -> float | None:
    value = _number(seconds)
    return round(value / 60, 1) if value else None
