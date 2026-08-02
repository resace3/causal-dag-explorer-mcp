"""Sleep and steps read from the Google Health MCP server.

Two metrics, not everything on offer. The same API also carries heart rate,
oxygen saturation, VO2 max and a dozen more, all of which either have a source
on this machine already or have no row to appear in; a provider that claimed
capabilities it was not configured to answer for would start winning metrics
nobody pointed it at. Each capability here was added deliberately, one at a
time, because a row was asked to come from it.

Steps arrive as **per-minute deltas** — "37 steps between 18:24 and 18:25" —
which is the shape the source actually records. The daily counter that reaches
Home Assistant is the same data accumulated and then resampled by whenever the
watch happened to sync, so it says the day's total accurately and says *when*
the steps happened only approximately. That is the whole reason for reading
them here instead.

**Everything below the sleep period is discarded here, at the connector.** The
API returns a full hypnogram — every deep/REM/light/awake stretch of the night,
thirty-odd rows per record — and the row this feeds is a duration row. Dropping
the stages where the data arrives, rather than ignoring them at render time,
means they never reach SQLite, the API or the browser. It is the same treatment
`activitywatch.detail` gets, and for the same reason: the most detailed thing a
source offers should not be stored by default just because it was offered.

What survives is the interval, how much of it was asleep, and whether the
provider called it the main sleep or a nap.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ...config.schema import GoogleHealthMcpConfig, McpServerConfig
from ..mcp_client import McpClientError, open_session
from .base import (
    CAPABILITY_SLEEP,
    CAPABILITY_STEPS,
    BaseWearableProvider,
    StepBucket,
    WearableCapabilities,
    WearableProviderError,
    WearableSleepRecord,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "google_health_mcp"

#: Every tool this provider may call. Both are read-only. The same server also
#: exposes token exchange, profile updates and nutrition writes; this
#: application must never reach them.
ALLOWED_TOOLS = frozenset({"google_health_list_data_points", "google_health_connection_status"})

DATA_POINTS_TOOL = "google_health_list_data_points"

#: Records come back newest first, so paging stops as soon as one predates the
#: window. The cap is a guard against a server that never sets `nextPageToken`.
MAX_PAGES = 6
PAGE_SIZE = 100

#: Steps are one bucket per minute, so a 50-hour fetch window is up to 3000 of
#: them where a night of sleep is one. Same paging, an order of magnitude more
#: of it — at the sleep page size this would give up six pages into yesterday
#: morning and silently report a third of a day.
STEPS_PAGE_SIZE = 1000
STEPS_MAX_PAGES = 12


class GoogleHealthMcpProvider(BaseWearableProvider):
    name = PROVIDER_NAME

    def __init__(
        self, config: GoogleHealthMcpConfig, server: McpServerConfig, tz: ZoneInfo
    ) -> None:
        self.config = config
        self.server = server
        self.tz = tz
        self._capabilities: WearableCapabilities | None = None
        self._cache: dict[tuple[datetime, datetime], list[WearableSleepRecord]] = {}
        self._steps_cache: dict[tuple[datetime, datetime], list[StepBucket]] = {}

    # -- capabilities ----------------------------------------------------

    async def get_capabilities(self) -> WearableCapabilities:
        if self._capabilities is not None:
            return self._capabilities

        if not self.server.enabled:
            raise WearableProviderError(
                f"The '{self.config.mcp_server}' MCP server is disabled in config.yaml."
            )

        try:
            async with open_session(
                self.config.mcp_server,
                self.server,
                ALLOWED_TOOLS,
                startup_timeout=self.server.startup_timeout_seconds,
            ) as session:
                tools = set(await session.list_tools())
                status = await session.call_json("google_health_connection_status", {})
        except McpClientError as exc:
            raise WearableProviderError(str(exc)) from exc

        if DATA_POINTS_TOOL not in tools:
            raise WearableProviderError(
                f"The '{self.config.mcp_server}' MCP server does not expose "
                f"{DATA_POINTS_TOOL}, so no sleep can be read from it."
            )

        detail = f"Sleep and steps from {self.config.device_name}"
        if isinstance(status, dict):
            # An expired access token is normal and refreshes itself; a missing
            # refresh token is not, and is worth saying before a day looks empty.
            token = status.get("token") or {}
            if not token.get("has_refresh_token"):
                detail += " — no refresh token stored, so this will stop working"

        self._capabilities = WearableCapabilities(
            provider=PROVIDER_NAME,
            device=self.config.device_name,
            capabilities=[CAPABILITY_SLEEP, CAPABILITY_STEPS],
            status="connected",
            detail=detail,
        )
        return self._capabilities

    # -- sleep -----------------------------------------------------------

    async def get_sleep(self, start: datetime, end: datetime) -> list[WearableSleepRecord]:
        key = (start, end)
        if key in self._cache:
            return self._cache[key]

        try:
            points = await self._load_points("sleep", start, PAGE_SIZE, MAX_PAGES)
        except McpClientError as exc:
            raise WearableProviderError(str(exc)) from exc

        records: list[WearableSleepRecord] = []
        for point in points:
            record = self._to_record(point)
            if record is None:
                continue
            # Overlap, not containment: a night that began before the fetch
            # window still belongs to the day it ends on.
            if record.end <= start or record.start >= end:
                continue
            records.append(record)

        records.sort(key=lambda record: record.start)
        self._cache[key] = records
        return records

    async def _load_points(
        self, data_type: str, start: datetime, page_size: int, max_pages: int
    ) -> list[dict[str, Any]]:
        """Page back through records of one type until one predates the window."""
        collected: list[dict[str, Any]] = []
        token: str | None = None

        async with open_session(
            self.config.mcp_server,
            self.server,
            ALLOWED_TOOLS,
            startup_timeout=self.server.startup_timeout_seconds,
        ) as session:
            for _page in range(max_pages):
                arguments: dict[str, Any] = {
                    "data_type": data_type,
                    "page_size": page_size,
                    "response_format": "json",
                }
                if token:
                    arguments["page_token"] = token

                payload = await session.call_json(DATA_POINTS_TOOL, arguments)
                page = _data_points(payload)
                token = _next_page_token(payload)

                # An empty page is not the end of the data. The first page of
                # steps comes back empty with a token, and stopping there would
                # report a day with no movement on it.
                if not page:
                    if not token:
                        break
                    continue

                collected.extend(page)

                oldest = min(
                    (
                        stamp
                        for stamp in (
                            _start_of(point, data_type, self.tz) for point in page
                        )
                        if stamp is not None
                    ),
                    default=None,
                )
                if oldest is not None and oldest <= start:
                    break

                if not token:
                    break

        return collected

    # -- steps -----------------------------------------------------------

    async def get_steps(self, start: datetime, end: datetime) -> list[StepBucket]:
        key = (start, end)
        if key in self._steps_cache:
            return self._steps_cache[key]

        try:
            points = await self._load_points(
                "steps", start, STEPS_PAGE_SIZE, STEPS_MAX_PAGES
            )
        except McpClientError as exc:
            raise WearableProviderError(str(exc)) from exc

        buckets: list[StepBucket] = []
        for point in points:
            bucket = self._to_bucket(point)
            if bucket is None:
                continue
            # Containment, not overlap: a step bucket is a minute long and
            # belongs to whichever side of the boundary it started on. Counting
            # a straddling bucket into both days would double those steps.
            if bucket.start < start or bucket.start >= end:
                continue
            buckets.append(bucket)

        chosen, rejected = _one_source_only(buckets)

        # Within the winning source, a repeated start would still be a double.
        seen: dict[datetime, StepBucket] = {}
        for bucket in sorted(chosen, key=lambda item: item.start):
            seen.setdefault(bucket.start, bucket)

        ordered = sorted(seen.values(), key=lambda item: item.start)
        if ordered and rejected:
            ordered[0].metadata["chosenOver"] = rejected
        self._steps_cache[key] = ordered
        return ordered

    def _to_bucket(self, point: dict[str, Any]) -> StepBucket | None:
        steps = point.get("steps")
        if not isinstance(steps, dict):
            return None

        interval = steps.get("interval") or {}
        begin = _parse_stamp(interval.get("startTime"), self.tz)
        finish = _parse_stamp(interval.get("endTime"), self.tz)
        if begin is None or finish is None or finish <= begin:
            return None

        count = _number(steps.get("count"))
        if count is None or count < 0:
            return None

        source = point.get("dataSource") or {}
        return StepBucket(
            start=begin,
            end=finish,
            count=count,
            device=(source.get("device") or {}).get("displayName"),
            metadata={
                "recordingMethod": source.get("recordingMethod"),
                "platform": source.get("platform"),
            },
        )

    def _to_record(self, point: dict[str, Any]) -> WearableSleepRecord | None:
        sleep = point.get("sleep")
        if not isinstance(sleep, dict):
            return None

        interval = sleep.get("interval") or {}
        begin = _parse_stamp(interval.get("startTime"), self.tz)
        finish = _parse_stamp(interval.get("endTime"), self.tz)
        if begin is None or finish is None or finish <= begin:
            return None

        metadata = sleep.get("metadata") or {}
        summary = sleep.get("summary") or {}
        source = point.get("dataSource") or {}
        device = (source.get("device") or {}).get("displayName")

        asleep = _minutes(summary.get("minutesAsleep"))
        in_period = _minutes(summary.get("minutesInSleepPeriod"))
        awake = _minutes(summary.get("minutesAwake"))

        # `nap` and `mainSleep` are not exclusive in this API — a 37-minute
        # record can carry both — so an explicit nap flag wins over a mainSleep
        # flag that only means "the longest one that day".
        is_main = bool(metadata.get("mainSleep")) and not metadata.get("nap")

        return WearableSleepRecord(
            id=_point_id(point),
            start=begin,
            end=finish,
            is_main_sleep=is_main,
            time_in_bed_minutes=in_period,
            awake_minutes=awake,
            # Deliberately empty: the hypnogram is dropped here rather than
            # carried to a row that would not draw it. See the module docstring.
            stages=[],
            device=device,
            metadata={
                "minutesAsleep": asleep,
                "recordingMethod": source.get("recordingMethod"),
                "platform": source.get("platform"),
                "stagesRecorded": sleep.get("type") == "STAGES",
                "note": (
                    "Google Health publishes a full hypnogram for this period. It is "
                    "discarded at the connector: this row reports duration, and stages "
                    "it will not draw are not worth storing."
                ),
            },
        )


def _one_source_only(
    buckets: list[StepBucket],
) -> tuple[list[StepBucket], list[dict[str, Any]]]:
    """Keep one device's step buckets and report the rest as discarded.

    Google Health hands back every source it holds, and a phone in a pocket and
    a watch on a wrist are both counting the same feet. Their buckets do not
    line up — the watch reports whole minutes, the phone reports ragged
    intervals starting mid-second — so they cannot be deduplicated by timestamp
    and summing them silently inflates the day by whatever fraction was walked
    with both. Google's own daily rollup answers with one source's total, and so
    does this.

    The source that observed the most of the day wins, which keeps the watch on
    a day it was worn and falls to the phone on a day it was not. Never a blend:
    a day that mixed the two would be a number no device ever measured.
    """
    groups: dict[tuple[str | None, str | None], list[StepBucket]] = {}
    for bucket in buckets:
        key = (bucket.device, bucket.metadata.get("platform"))
        groups.setdefault(key, []).append(bucket)

    if not groups:
        return [], []
    if len(groups) == 1:
        return next(iter(groups.values())), []

    def covered(items: list[StepBucket]) -> float:
        return sum((item.end - item.start).total_seconds() for item in items)

    ranked = sorted(
        groups.items(),
        key=lambda item: (-covered(item[1]), -len(item[1]), str(item[0])),
    )
    chosen = ranked[0][1]
    rejected = [
        {
            "device": key[0],
            "platform": key[1],
            "buckets": len(items),
            "steps": int(round(sum(item.count for item in items))),
        }
        for key, items in ranked[1:]
    ]
    return chosen, rejected


# --------------------------------------------------------------------------
# Payload shapes
# --------------------------------------------------------------------------


def _data_points(payload: Any) -> list[dict[str, Any]]:
    """The tool wraps its answer; prose instead of JSON means "nothing"."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    container = data if isinstance(data, dict) else payload
    points = container.get("dataPoints")
    return [point for point in points if isinstance(point, dict)] if isinstance(points, list) else []


def _next_page_token(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    container = data if isinstance(data, dict) else payload
    token = container.get("nextPageToken")
    return token if isinstance(token, str) and token else None


def _point_id(point: dict[str, Any]) -> str:
    """`users/…/dataPoints/7078689973880976752` -> the trailing id."""
    name = point.get("name")
    if isinstance(name, str) and name:
        return name.rsplit("/", 1)[-1]
    interval = (point.get("sleep") or {}).get("interval") or {}
    return str(interval.get("startTime") or "unknown")


def _start_of(point: dict[str, Any], data_type: str, tz: ZoneInfo) -> datetime | None:
    interval = (point.get(data_type) or {}).get("interval") or {}
    return _parse_stamp(interval.get("startTime"), tz)


def _parse_stamp(value: Any, tz: ZoneInfo) -> datetime | None:
    """Google Health sends UTC instants; the timeline works in local time."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(tz)


def _minutes(value: Any) -> float | None:
    """The summary sends minutes as strings."""
    return _number(value)


def _number(value: Any) -> float | None:
    """This API sends numbers as strings — minutes, and step counts alike."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "GoogleHealthMcpProvider",
    "PROVIDER_NAME",
    "ALLOWED_TOOLS",
    "MAX_PAGES",
    "PAGE_SIZE",
    "STEPS_MAX_PAGES",
    "STEPS_PAGE_SIZE",
]
