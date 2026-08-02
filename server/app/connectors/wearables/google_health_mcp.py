"""Sleep read from the Google Health MCP server.

Sleep only. Google Health also carries steps, heart rate and more, but those
lanes already have sources on this machine, and a provider that claimed
capabilities it was not configured to be the answer for would start winning
metrics nobody asked it for.

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
    BaseWearableProvider,
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

        detail = f"Sleep from {self.config.device_name}"
        if isinstance(status, dict):
            # An expired access token is normal and refreshes itself; a missing
            # refresh token is not, and is worth saying before a day looks empty.
            token = status.get("token") or {}
            if not token.get("has_refresh_token"):
                detail += " — no refresh token stored, so this will stop working"

        self._capabilities = WearableCapabilities(
            provider=PROVIDER_NAME,
            device=self.config.device_name,
            capabilities=[CAPABILITY_SLEEP],
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
            points = await self._load_points(start)
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

    async def _load_points(self, start: datetime) -> list[dict[str, Any]]:
        """Page back through sleep records until one predates the window."""
        collected: list[dict[str, Any]] = []
        token: str | None = None

        async with open_session(
            self.config.mcp_server,
            self.server,
            ALLOWED_TOOLS,
            startup_timeout=self.server.startup_timeout_seconds,
        ) as session:
            for _page in range(MAX_PAGES):
                arguments: dict[str, Any] = {
                    "data_type": "sleep",
                    "page_size": PAGE_SIZE,
                    "response_format": "json",
                }
                if token:
                    arguments["page_token"] = token

                payload = await session.call_json(DATA_POINTS_TOOL, arguments)
                page = _data_points(payload)
                if not page:
                    break
                collected.extend(page)

                oldest = min(
                    (
                        stamp
                        for stamp in (_start_of(point, self.tz) for point in page)
                        if stamp is not None
                    ),
                    default=None,
                )
                if oldest is not None and oldest <= start:
                    break

                token = _next_page_token(payload)
                if not token:
                    break

        return collected

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


def _start_of(point: dict[str, Any], tz: ZoneInfo) -> datetime | None:
    interval = (point.get("sleep") or {}).get("interval") or {}
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
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["GoogleHealthMcpProvider", "PROVIDER_NAME", "ALLOWED_TOOLS", "MAX_PAGES", "PAGE_SIZE"]
