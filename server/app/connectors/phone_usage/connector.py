"""Turn the phone-usage add-on's API into `RawRecord`s.

The add-on holds two kinds of answer about the same phone, and they are *not*
interchangeable. Both are fetched, on separate streams, because the row needs
one for shape and the other for magnitude:

* **`/v1/timeline`** — foreground segments with real start and end times. This
  is the only thing here with timing, and it is package-level: Android's public
  `UsageEvents` API does not expose `taskRootPackage`, so an in-app browser's
  time is credited to the browser rather than to the app hosting it.
* **`/v1/apps`** — per-app minutes read from the system's own daily buckets,
  which *do* carry task-root attribution. These are the authoritative totals.

Replaying the segments to get a per-app total is the mistake this connector
exists to make impossible: it understates apps that open links in-app, TikTok
by roughly fivefold when this was measured. The two arrive on different streams
so a rule cannot reach for the wrong one by accident.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ...config.schema import PhoneUsageConfig
from ...config.settings import Settings
from ...models.raw import RawRecord
from ..base import ConnectorResult
from .client import PhoneUsageClient, PhoneUsageError
from .mock_segments import generate_segments

logger = logging.getLogger(__name__)

SOURCE_ID = "phone_usage"
SOURCE_NAME = "Phone Usage Collector"

#: Foreground segments — sequence and timing.
STREAM_SEGMENT = "phone_segment"
#: Per-app daily totals — magnitude, task-root attributed.
STREAM_APP_DAILY = "phone_app_daily"
#: One row per day: unlocks, glances, notification interruptions, switches.
STREAM_DAY_SUMMARY = "phone_day_summary"

#: Shorter than this and a segment is a flicker between two apps, not use.
MIN_SEGMENT_SECONDS = 1.0


class PhoneUsageConnector:
    def __init__(
        self,
        config: PhoneUsageConfig,
        settings: Settings,
        tz: ZoneInfo,
        *,
        client: PhoneUsageClient | None = None,
    ) -> None:
        self.config = config
        self.settings = settings
        self.tz = tz
        self._client = client

    # -- status ----------------------------------------------------------

    def _build_client(self) -> PhoneUsageClient | None:
        if self._client is not None:
            return self._client
        url = self.settings.phone_usage_url
        if not url:
            return None
        return PhoneUsageClient(
            url,
            self.settings.phone_usage_token,
            timeout=self.settings.phone_usage_timeout_seconds,
        )

    async def check_status(self) -> tuple[str, str | None]:
        if not self.config.enabled:
            return "disconnected", "The phone-usage add-on is disabled in config.yaml."
        if self.settings.use_mock_data:
            return "mock_data", (
                "USE_MOCK_DATA=true — foreground segments are generated locally, the "
                "add-on is not contacted."
            )
        client = self._build_client()
        if client is None:
            return "disconnected", (
                "Set PHONE_USAGE_URL in .env to the add-on's host and port, e.g. "
                "http://192.168.1.10:8099."
            )
        try:
            await client.health()
            status = await client.status()
        except PhoneUsageError as exc:
            return "error", str(exc)
        events = status.get("events")
        detail = f"Connected to {client.base_url}"
        if isinstance(events, int):
            detail += f" — {events:,} stored events"
        return "connected", detail

    # -- fetching --------------------------------------------------------

    async def fetch(self, start: datetime, end: datetime) -> ConnectorResult:
        result = ConnectorResult(capabilities=["phone_foreground", "phone_app_totals"])

        if not self.config.enabled:
            result.status = "disconnected"
            result.detail = "The phone-usage add-on is disabled in config.yaml."
            return result

        days = _local_days(start, end, self.tz)

        if self.settings.use_mock_data:
            result.status = "mock_data"
            result.detail = f"Mock foreground segments for {len(days)} days."
            result.records = generate_segments(
                days, self.tz, self.settings.mock_data_seed, start, end
            )
            return result

        client = self._build_client()
        if client is None:
            result.status = "disconnected"
            result.detail = (
                "Set PHONE_USAGE_URL in .env to reach the add-on. The rest of the "
                "timeline is still displayed."
            )
            result.warnings.append(result.detail)
            return result

        today = datetime.now(self.tz).date()
        records: list[RawRecord] = []

        for day in days:
            try:
                segments = await client.timeline(day)
            except PhoneUsageError as exc:
                result.status = "error"
                result.detail = f"{exc} The rest of the timeline is still displayed."
                result.errors.append(result.detail)
                return result
            records.extend(self._segment_records(segments, start, end))

            # `?date=` selects buckets that *started* on that date. The open
            # bucket began yesterday morning, so today has to be asked for by
            # name or it comes back empty.
            try:
                apps = await client.apps(day, current_window=day == today)
                summary = await client.summary(day)
            except PhoneUsageError as exc:
                # The totals failing is not the whole row failing: the segments
                # already fetched still draw, they just lose their footnote.
                result.warnings.append(
                    f"Per-app totals for {day.isoformat()} could not be read ({exc}), so "
                    "the row shows segment timing without the authoritative daily figure."
                )
                continue
            records.extend(self._app_records(day, apps))
            records.extend(self._summary_records(day, summary))

        # One query per local day, and a segment that spans midnight comes back
        # in both answers. The ids are deterministic, so the duplicate is exact —
        # and drawn twice it would be counted twice in every total below it.
        unique: dict[str, RawRecord] = {}
        for record in records:
            unique.setdefault(record.id, record)

        result.status = "connected"
        result.detail = f"Read {len(unique)} records from {client.base_url}"
        result.records = list(unique.values())
        result.entity_count = len(days)

        if not records:
            result.warnings.append(
                "The phone-usage add-on answered but held nothing for these days. The "
                "collector app syncs hourly, and its history only reaches back about "
                "eight days."
            )
        return result

    # -- record building -------------------------------------------------

    def _segment_records(
        self, segments: list[dict[str, Any]], start: datetime, end: datetime
    ) -> list[RawRecord]:
        records: list[RawRecord] = []
        for segment in segments:
            package = segment.get("pkg")
            begin = _from_millis(segment.get("start"), self.tz)
            finish = _from_millis(segment.get("end"), self.tz)
            if not package or begin is None or finish is None or finish <= begin:
                continue
            if (finish - begin).total_seconds() < MIN_SEGMENT_SECONDS:
                continue
            if finish <= start or begin >= end:
                continue
            records.append(
                RawRecord(
                    id=RawRecord.make_id(
                        SOURCE_ID, STREAM_SEGMENT, f"{package}|{begin.isoformat()}"
                    ),
                    source=SOURCE_ID,
                    stream=STREAM_SEGMENT,
                    device="phone",
                    timestamp=begin,
                    end_timestamp=finish,
                    value=package,
                    unit="seconds",
                    attributes={
                        "package": package,
                        "seconds": (finish - begin).total_seconds(),
                        "attribution": "package",
                    },
                )
            )
        return records

    def _app_records(self, day: date, apps: list[dict[str, Any]]) -> list[RawRecord]:
        records: list[RawRecord] = []
        stamp = datetime.combine(day, datetime.min.time(), tzinfo=self.tz)
        for entry in apps:
            package = entry.get("pkg")
            minutes = entry.get("minutes")
            if not package or not isinstance(minutes, (int, float)):
                continue
            records.append(
                RawRecord(
                    id=RawRecord.make_id(
                        SOURCE_ID, STREAM_APP_DAILY, f"{day.isoformat()}|{package}"
                    ),
                    source=SOURCE_ID,
                    stream=STREAM_APP_DAILY,
                    device="phone",
                    timestamp=stamp,
                    value=float(minutes),
                    unit="minutes",
                    attributes={
                        "package": package,
                        "date": day.isoformat(),
                        "attribution": "task_root",
                        "lastUsed": entry.get("last_used"),
                    },
                )
            )
        return records

    def _summary_records(self, day: date, summary: dict[str, Any]) -> list[RawRecord]:
        if not summary:
            return []
        stamp = datetime.combine(day, datetime.min.time(), tzinfo=self.tz)
        return [
            RawRecord(
                id=RawRecord.make_id(SOURCE_ID, STREAM_DAY_SUMMARY, day.isoformat()),
                source=SOURCE_ID,
                stream=STREAM_DAY_SUMMARY,
                device="phone",
                timestamp=stamp,
                value=summary.get("screen_on_minutes"),
                unit="minutes",
                attributes={"date": day.isoformat(), **summary},
            )
        ]


def _local_days(start: datetime, end: datetime, tz: ZoneInfo) -> list[date]:
    first = start.astimezone(tz).date()
    last = end.astimezone(tz).date()
    days: list[date] = []
    cursor = first
    while cursor <= last:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _from_millis(value: Any, tz: ZoneInfo) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz)
    except (OverflowError, OSError, ValueError):
        return None
