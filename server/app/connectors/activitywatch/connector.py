"""Turn ActivityWatch focus history into `RawRecord`s.

ActivityWatch answers a question no other source here can: what this machine was
being used for, minute by minute. Three watchers contribute:

* `aw-watcher-afk` — whether the keyboard and mouse were being touched.
* `aw-watcher-window` — which application had focus.
* `aw-watcher-web-*` — which site a browser tab was on, when the extension is
  installed.

**Reduction happens here, at the boundary, not downstream.** Window titles and
full URLs are dropped before a record is constructed, exactly as the Home
Assistant connector drops latitude and longitude, so that detail the user did
not ask for never enters the data model, the SQLite cache or the API at all.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from ...config.schema import ActivityWatchConfig
from ...config.settings import Settings
from ...models.raw import RawRecord
from ...models.sources import SourceStatus
from ..base import ConnectorResult
from .client import ActivityWatchClient, ActivityWatchError
from .mock_events import generate_events

logger = logging.getLogger(__name__)

SOURCE_ID = "activitywatch"
SOURCE_NAME = "ActivityWatch"

STREAM_AFK = "computer_afk"
STREAM_WINDOW = "computer_window"
STREAM_WEB = "computer_web"

BUCKET_TYPES = {
    "afkstatus": STREAM_AFK,
    "currentwindow": STREAM_WINDOW,
    "web.tab.current": STREAM_WEB,
}

CAPABILITY_BY_STREAM = {
    STREAM_AFK: "idle_detection",
    STREAM_WINDOW: "window_activity",
    STREAM_WEB: "web_browsing",
}

#: Shorter than this and an event is noise — an alt-tab in passing, not use.
MIN_EVENT_SECONDS = 1.0


class ActivityWatchConnector:
    def __init__(
        self,
        config: ActivityWatchConfig,
        settings: Settings,
        tz: ZoneInfo,
        *,
        client: ActivityWatchClient | None = None,
    ) -> None:
        self.config = config
        self.settings = settings
        self.tz = tz
        self._client = client

    # -- status ----------------------------------------------------------

    def _build_client(self) -> ActivityWatchClient:
        if self._client is not None:
            return self._client
        return ActivityWatchClient(
            self.settings.activitywatch_url,
            timeout=self.settings.activitywatch_timeout_seconds,
        )

    async def check_status(self) -> tuple[SourceStatus, str | None, list[str]]:
        """Reachability plus which watchers are actually running.

        Capabilities come from the buckets that exist rather than from config:
        the browser extension is frequently not installed, and claiming browsing
        support it does not have would be a lie the panel repeats.
        """
        if not self.config.enabled:
            return "disconnected", "ActivityWatch is disabled in config.yaml.", []
        if self.settings.use_mock_data:
            return (
                "mock_data",
                "USE_MOCK_DATA=true — computer use is generated locally, no "
                "ActivityWatch server is contacted.",
                sorted(CAPABILITY_BY_STREAM.values()),
            )

        client = self._build_client()
        try:
            buckets = await client.buckets()
            info = await client.info()
        except ActivityWatchError as exc:
            return "error", str(exc), []

        streams = self._select_buckets(buckets)[0]
        if STREAM_WINDOW not in streams:
            return (
                "error",
                f"ActivityWatch is running at {client.base_url} but no window watcher "
                "has reported. Open the ActivityWatch dashboard and check that "
                "aw-watcher-window is running.",
                [CAPABILITY_BY_STREAM[stream] for stream in streams],
            )

        host = info.get("hostname") or "this machine"
        return (
            "connected",
            f"Connected to ActivityWatch {info.get('version', '')} on {host} "
            f"({client.base_url}), detail level '{self.config.detail}'.".replace("  ", " "),
            [CAPABILITY_BY_STREAM[stream] for stream in streams],
        )

    # -- bucket selection ------------------------------------------------

    def _select_buckets(
        self, buckets: dict[str, dict[str, Any]]
    ) -> tuple[dict[str, str], list[str]]:
        """Choose one bucket per stream, and say what was left out.

        One ActivityWatch server can collect several machines. Merging two
        machines' focus histories would produce a timeline of a computer nobody
        used, so one host is chosen and the rest are named.
        """
        warnings: list[str] = []
        candidates: dict[str, list[str]] = {}
        for bucket_id, meta in buckets.items():
            stream = BUCKET_TYPES.get(str(meta.get("type")))
            if stream is None:
                continue
            if self.config.hostname and meta.get("hostname") != self.config.hostname:
                continue
            candidates.setdefault(stream, []).append(bucket_id)

        chosen: dict[str, str] = {}
        for stream, ids in candidates.items():
            ordered = sorted(ids)
            chosen[stream] = ordered[0]
            if len(ordered) > 1:
                warnings.append(
                    f"ActivityWatch has {len(ordered)} buckets of this kind "
                    f"({', '.join(ordered)}). Read {ordered[0]} and ignored the rest — "
                    "set activitywatch.hostname in config.yaml to choose, rather than "
                    "having two machines' activity merged into one day."
                )

        if self.config.hostname and not chosen:
            warnings.append(
                f"No ActivityWatch bucket reports hostname '{self.config.hostname}'. "
                "Check activitywatch.hostname in config.yaml."
            )
        return chosen, warnings

    # -- fetching --------------------------------------------------------

    async def fetch(self, start: datetime, end: datetime) -> ConnectorResult:
        result = ConnectorResult()

        if not self.config.enabled:
            result.status = "disconnected"
            result.detail = "ActivityWatch is disabled in config.yaml."
            return result

        if self.settings.use_mock_data:
            events = generate_events(start, end, self.tz, self.settings.mock_data_seed)
            result.status = "mock_data"
            result.detail = (
                f"Mock computer use (seed {self.settings.mock_data_seed}); no "
                "ActivityWatch server was contacted."
            )
            result.capabilities = sorted(CAPABILITY_BY_STREAM.values())
            result.records = self._to_records(events, mock=True)
            result.entity_count = len({record.entity_id for record in result.records})
            return result

        client = self._build_client()
        try:
            buckets = await client.buckets()
        except ActivityWatchError as exc:
            result.status = "error"
            result.detail = f"{exc} The other lanes are unaffected."
            result.errors.append(result.detail)
            return result

        streams, warnings = self._select_buckets(buckets)
        result.warnings.extend(warnings)
        result.entity_count = len(streams)
        result.capabilities = [CAPABILITY_BY_STREAM[stream] for stream in streams]

        if STREAM_WINDOW not in streams:
            result.status = "error"
            result.detail = (
                "ActivityWatch answered but no window watcher has reported, so there "
                "is no record of what this machine was used for."
            )
            result.errors.append(result.detail)
            return result

        try:
            events = await self._query_all(client, streams, start, end)
        except ActivityWatchError as exc:
            result.status = "error"
            result.detail = f"{exc} The other lanes are unaffected."
            result.errors.append(result.detail)
            return result

        result.status = "connected"
        result.records = self._to_records(events)
        result.detail = (
            f"Read {len(result.records)} focus and idle events from "
            f"{client.base_url} at detail level '{self.config.detail}'."
        )
        if STREAM_AFK not in streams:
            result.warnings.append(
                "ActivityWatch has no idle watcher, so time at the computer is inferred "
                "from focus events alone and a window left open counts as use."
            )
        if self.config.detail != "app" and STREAM_WEB not in streams:
            result.warnings.append(
                "No ActivityWatch browser extension is reporting, so browsing is not "
                "shown. Browser time still appears under the browser's application name."
            )
        return result

    async def _query_all(
        self,
        client: ActivityWatchClient,
        streams: dict[str, str],
        start: datetime,
        end: datetime,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Run one query per stream. Returns `(stream, bucket_id, event)`."""
        collected: list[tuple[str, str, dict[str, Any]]] = []

        afk_bucket = streams.get(STREAM_AFK)
        if afk_bucket:
            for event in await client.query(
                [
                    f"afk = flood(query_bucket({_q(afk_bucket)}));",
                    "RETURN = sort_by_timestamp(afk);",
                ],
                start,
                end,
            ):
                collected.append((STREAM_AFK, afk_bucket, event))

        window_bucket = streams[STREAM_WINDOW]
        for event in await client.query(
            _active_statements(window_bucket, afk_bucket, "events"), start, end
        ):
            collected.append((STREAM_WINDOW, window_bucket, event))

        web_bucket = streams.get(STREAM_WEB)
        if web_bucket and self.config.detail != "app":
            for event in await client.query(
                _active_statements(web_bucket, afk_bucket, "web"), start, end
            ):
                collected.append((STREAM_WEB, web_bucket, event))

        return collected

    # -- record construction ---------------------------------------------

    def _to_records(
        self, events: list[tuple[str, str, dict[str, Any]]], *, mock: bool = False
    ) -> list[RawRecord]:
        """Build records, keeping one copy of each distinct period.

        `flood` repeats a period once per heartbeat it absorbed — a quiet
        45-minute idle stretch comes back nine times — and the copies are not
        always the same length, the longest being the one that was still being
        extended when it ended. Left alone they multiply every duration this
        rule adds up, so identical periods collapse here, longest kept.
        """
        deduped: dict[tuple[str, str, datetime, str], RawRecord] = {}

        for stream, bucket_id, event in events:
            timestamp = _parse_timestamp(event.get("timestamp"))
            duration = _to_float(event.get("duration"))
            if timestamp is None or duration is None:
                continue
            if stream != STREAM_AFK and duration < MIN_EVENT_SECONDS:
                continue

            timestamp = timestamp.astimezone(self.tz)
            data = event.get("data") or {}
            value, attributes = self._reduce(stream, data)
            if value is None:
                continue

            key = (stream, bucket_id, timestamp, value)
            end = timestamp + timedelta(seconds=duration)
            existing = deduped.get(key)
            if existing is not None and (existing.end_timestamp or existing.timestamp) >= end:
                continue

            deduped[key] = RawRecord(
                id=RawRecord.make_id(
                    SOURCE_ID, stream, f"{bucket_id}|{timestamp.isoformat()}|{value}"
                ),
                source=SOURCE_ID,
                stream=stream,
                entity_id=bucket_id,
                device=("Mock computer" if mock else bucket_id.split("_")[-1]) or None,
                timestamp=timestamp,
                end_timestamp=end,
                value=value,
                unit="seconds",
                attributes=attributes,
            )

        records = sorted(deduped.values(), key=lambda record: (record.stream, record.timestamp))
        return records

    def _reduce(self, stream: str, data: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        """Reduce one ActivityWatch event to what the detail level permits.

        Anything the level does not permit is not returned at all — there is no
        redacted copy kept anywhere for it to leak out of later.
        """
        detail = self.config.detail
        attributes: dict[str, Any] = {"detail": detail}

        if stream == STREAM_AFK:
            status = str(data.get("status") or "").strip().lower()
            return (status or None), attributes

        if stream == STREAM_WINDOW:
            app = str(data.get("app") or "").strip()
            if not app:
                return None, attributes
            if detail == "full":
                title = str(data.get("title") or "").strip()
                if title:
                    attributes["title"] = title
            return app, attributes

        # STREAM_WEB
        url = str(data.get("url") or "").strip()
        if not url:
            return None, attributes
        domain = _domain_of(url)
        if not domain:
            return None, attributes
        attributes["domain"] = domain
        if detail == "full":
            attributes["url"] = url
            title = str(data.get("title") or "").strip()
            if title:
                attributes["title"] = title
            return url, attributes
        return domain, attributes


def _active_statements(bucket: str, afk_bucket: str | None, name: str) -> list[str]:
    """query2 for "this bucket's events, while the user was actually there".

    `flood` closes the sub-second holes between heartbeats;
    `filter_period_intersect` against the not-afk periods is how ActivityWatch
    expresses "while the keyboard was being touched". Without the AFK watcher
    the events are returned unfiltered and the caller warns that a window left
    open counts as use.
    """
    lines = [f"{name} = flood(query_bucket({_q(bucket)}));"]
    if afk_bucket:
        lines += [
            f"not_afk = flood(query_bucket({_q(afk_bucket)}));",
            'not_afk = filter_keyvals(not_afk, "status", ["not-afk"]);',
            f"{name} = filter_period_intersect({name}, not_afk);",
        ]
    lines.append(f"RETURN = sort_by_timestamp({name});")
    return lines


def _q(value: str) -> str:
    """A double-quoted query2 string literal."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _domain_of(url: str) -> str | None:
    """The site a URL belongs to, with no path, query or fragment.

    A path is where the identifying detail lives — `/watch?v=…`, a document
    name, a search string — so it is dropped before the value is built rather
    than trimmed for display.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme in {"http", "https"}:
        host = (parsed.hostname or "").lower()
        if not host:
            return None
        return host[4:] if host.startswith("www.") else host
    if parsed.scheme:
        # `chrome://`, `file://`, `about:` — the scheme is all that is safe to
        # keep, since the rest is a local path or an internal page name.
        return f"{parsed.scheme}://"
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
