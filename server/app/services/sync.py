"""Orchestrates one previous-day reconstruction.

Connectors -> normalization -> feature engineering -> stored `DayTimeline`.
Partial failure is normal and expected: a source that fails contributes an
error string and zero records, and the day is still reconstructed from whatever
else responded.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date as date_type, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..config.loader import get_config, resolve_timezone
from ..config.schema import AppConfig
from ..config.settings import Settings, get_settings
from ..connectors.home_assistant.connector import (
    SOURCE_ID as HA_SOURCE_ID,
    SOURCE_NAME as HA_SOURCE_NAME,
    HomeAssistantConnector,
)
from ..connectors.wearables.base import WearableProvider
from ..connectors.wearables.connector import WearableConnector, WearablePayload
from ..connectors.wearables.registry import build_provider
from ..feature_engineering.context import RuleContext
from ..feature_engineering.pipeline import run as run_pipeline
from ..models.raw import RawRecord
from ..models.sources import DataSource, DataSourceReport
from ..models.timeline import DayTimeline, SyncSummary
from ..normalization.normalizer import normalize
from ..storage.repository import Repository
from .day import DayWindow, day_window, previous_day

logger = logging.getLogger(__name__)

#: How each wearable provider is presented in the Data Sources panel. Every
#: row names the MCP integration it corresponds to, so the sidebar matches the
#: servers configured in the user's MCP client.
WEARABLE_SOURCES = {
    "auto": {
        "id": "garmin",
        "name": "Garmin",
        "mcp_server": "garmin",
        "transport": "mcp",
    },
    "garmin_mcp": {
        "id": "garmin",
        "name": "Garmin",
        "mcp_server": "garmin",
        "transport": "mcp",
    },
    "home_assistant": {
        "id": "wearable_home_assistant",
        "name": "Wearable via Home Assistant",
        "mcp_server": "ha-mcp",
        "transport": "rest",
    },
    "json_file": {
        "id": "wearable_file",
        "name": "Wearable export",
        "mcp_server": None,
        "transport": "file",
    },
    "mock": {
        "id": "wearable_mock",
        "name": "Mock wearable",
        "mcp_server": None,
        "transport": "mock",
    },
}


def _lane_has_data(timeline, lane_ids: tuple[str, ...]) -> bool:
    """True when the last sync produced at least one available lane here."""
    if timeline is None:
        return True  # Nothing synced yet; do not claim emptiness.
    return any(lane.available for lane in timeline.lanes if lane.id in lane_ids)


# Sleep that started the night before, and sleep that runs into today.
LOOKBACK = timedelta(hours=14)
LOOKAHEAD = timedelta(hours=12)

#: How long a wearable's capability probe stays valid. Long enough that the
#: sidebar's poll never respawns an MCP server, short enough that plugging one
#: in shows up without a restart.
CAPABILITIES_TTL_SECONDS = 600.0


class SyncService:
    def __init__(
        self,
        repository: Repository,
        settings: Settings | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or get_settings()
        self.config = config or get_config()
        self.tz: ZoneInfo = resolve_timezone(self.config)
        self._lock = asyncio.Lock()
        self._provider: WearableProvider | None = None
        self._capabilities: tuple[float, Any] | None = None
        self._capabilities_lock = asyncio.Lock()

    # -- helpers ---------------------------------------------------------

    def yesterday(self, *, now: datetime | None = None) -> DayWindow:
        return previous_day(self.tz, now=now)

    def window_for(self, day: date_type) -> DayWindow:
        return day_window(day, self.tz)

    def today(self, *, now: datetime | None = None) -> date_type:
        return (now or datetime.now(self.tz)).astimezone(self.tz).date()

    def _wearable_provider(self) -> WearableProvider:
        """One provider instance per process.

        A provider backed by an MCP server spawns a subprocess and signs in on
        first use — seconds of work. The sidebar polls source status, so
        rebuilding the provider each time would spawn that subprocess on every
        poll and make the panel hang.
        """
        if self._provider is None:
            self._provider = build_provider(self.config, self.settings, self.tz)
        return self._provider

    def _reset_provider(self) -> None:
        """Drop cached provider state so the next fetch really re-reads."""
        self._provider = None
        self._capabilities = None

    def _connectors(self) -> tuple[HomeAssistantConnector, WearableConnector]:
        home_assistant = HomeAssistantConnector(
            self.config.home_assistant, self.settings, self.tz
        )
        return home_assistant, WearableConnector(self._wearable_provider())

    # -- status ----------------------------------------------------------

    async def data_sources(self) -> DataSourceReport:
        """Report one row per MCP integration the timeline reads from."""
        home_assistant, wearable = self._connectors()
        ha_status, ha_detail = await home_assistant.check_status()

        last_run = self.repository.last_sync()
        last_sync = last_run.completed_at if last_run else None
        cached = self.repository.get_timeline(self.yesterday().day)

        sources = [
            DataSource(
                id=HA_SOURCE_ID,
                name=HA_SOURCE_NAME,
                status=ha_status,
                mcp_server=self.config.home_assistant.mcp_server,
                transport="mock" if self.settings.use_mock_data else "rest",
                capabilities=home_assistant.capabilities,
                detail=ha_detail,
                last_sync=last_sync,
                entity_count=len(self.config.home_assistant.entities.all_entity_ids()),
                has_data=_lane_has_data(cached, ("environment", "presence", "location")),
            ),
            await self._wearable_source(wearable, last_sync, cached),
        ]

        return DataSourceReport(
            sources=sources,
            mock_data=self.settings.use_mock_data,
            checked_at=datetime.now().astimezone(),
        )

    async def _wearable_source(self, wearable, last_sync, cached) -> DataSource:
        """The wearable row is named after the MCP server behind it."""
        provider_name = getattr(wearable.provider, "name", "unknown")
        descriptor = WEARABLE_SOURCES.get(provider_name, WEARABLE_SOURCES["mock"])
        mcp_server = descriptor["mcp_server"]
        if provider_name == "garmin_mcp":
            mcp_server = self.config.wearable.garmin_mcp.mcp_server
        elif provider_name == "home_assistant":
            mcp_server = self.config.home_assistant.mcp_server

        source = DataSource(
            id=descriptor["id"],
            name=descriptor["name"],
            status="disconnected",
            mcp_server=mcp_server,
            transport=descriptor["transport"],
            provider=provider_name,
        )

        try:
            capabilities = await self._cached_capabilities(wearable.provider)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            source.status = "error"
            source.detail = str(exc)
            source.has_data = False
            return source

        source.status = "mock_data" if capabilities.status == "mock_data" else "connected"
        source.capabilities = capabilities.capabilities
        source.detail = capabilities.detail
        source.last_sync = last_sync
        source.has_data = _lane_has_data(
            cached, ("activity", "heart_rate", "hrv", "readiness", "sleep", "temperature")
        )
        if source.status == "connected" and not source.has_data and cached is not None:
            source.detail = (
                f"{source.detail or 'Connected.'} No data for {cached.date} — the "
                "account is reachable but recorded nothing on that day."
            )
        return source

    async def _cached_capabilities(self, provider: WearableProvider):
        """Capabilities, cached for `CAPABILITIES_TTL_SECONDS`.

        Probing an MCP-backed provider spawns a subprocess and signs in, which
        takes seconds. Without caching, the sidebar's status poll would pay that
        cost every time and the panel would appear to hang. The lock means
        concurrent callers share one probe instead of racing to spawn several.
        """
        fresh = self._fresh_capabilities()
        if fresh is not None:
            return fresh

        async with self._capabilities_lock:
            # Another caller may have finished probing while we waited.
            fresh = self._fresh_capabilities()
            if fresh is not None:
                return fresh
            capabilities = await provider.get_capabilities()
            self._capabilities = (time.monotonic(), capabilities)
            return capabilities

    def _fresh_capabilities(self):
        if self._capabilities is None:
            return None
        cached_at, capabilities = self._capabilities
        if time.monotonic() - cached_at < CAPABILITIES_TTL_SECONDS:
            return capabilities
        return None

    async def warm_up(self) -> None:
        """Probe the wearable route once at startup so the first page is fast."""
        try:
            _home_assistant, wearable = self._connectors()
            await self._cached_capabilities(wearable.provider)
        except Exception as exc:  # noqa: BLE001 - warm-up is best effort
            logger.info("Wearable capability warm-up did not complete: %s", exc)

    # -- sync ------------------------------------------------------------

    async def sync(
        self,
        *,
        force_refresh: bool = False,
        now: datetime | None = None,
        day: date_type | None = None,
    ) -> DayTimeline:
        """Reconstruct one local calendar day. Defaults to yesterday."""
        async with self._lock:
            window = self.window_for(day) if day is not None else self.yesterday(now=now)
            if not force_refresh:
                cached = self.repository.get_timeline(window.day)
                if cached is not None:
                    return cached
            else:
                # Providers cache their own fetches; drop them so a forced
                # refresh really goes back to the source.
                self._reset_provider()
            return await self._run_sync(window)

    async def _run_sync(self, window: DayWindow) -> DayTimeline:
        started = datetime.now().astimezone()
        run_id = self.repository.start_sync(window.day)

        fetch_start = window.start - LOOKBACK
        fetch_end = window.end + LOOKAHEAD

        home_assistant, wearable = self._connectors()
        ha_result, wearable_payload = await asyncio.gather(
            home_assistant.fetch(fetch_start, fetch_end),
            wearable.fetch(fetch_start, fetch_end),
        )

        warnings = list(ha_result.warnings) + list(wearable_payload.warnings)
        errors = list(ha_result.errors) + list(wearable_payload.errors)

        raw_records: list[RawRecord] = list(ha_result.records) + list(wearable_payload.raw_records)
        normalized = normalize(raw_records, fetch_start, fetch_end)
        warnings.extend(normalized.warnings)

        baselines = self.repository.compute_baselines(
            window.day, self.config.feature_engineering.elevated_heart_rate.baseline_window_days
        )

        context = RuleContext(
            window=window,
            fetch_start=fetch_start,
            fetch_end=fetch_end,
            tz=self.tz,
            config=self.config.feature_engineering,
            normalized=normalized,
            wearable=wearable_payload,
            home_assistant_available=ha_result.status in {"connected", "mock_data"},
            baselines=baselines,
        )

        lanes, coverage, highlights = run_pipeline(context)
        warnings.extend(context.warnings)

        wearable_name = WEARABLE_SOURCES.get(
            getattr(wearable.provider, "name", "mock"), WEARABLE_SOURCES["mock"]
        )["name"]
        sources_checked = [HA_SOURCE_NAME, wearable_name]
        derived_count = sum(
            1
            for lane in lanes
            for event in lane.events
            if event.measured_or_derived == "derived"
        )
        event_count = sum(len(lane.events) for lane in lanes)
        point_count = sum(len(series.points) for lane in lanes for series in lane.series)

        if not any(lane.available for lane in lanes):
            errors.append(
                "No data source returned usable data for this day. Check the Data Sources "
                "panel for the specific failure, or set USE_MOCK_DATA=true to explore the "
                "interface with generated data."
            )

        summary = SyncSummary(
            date_processed=window.iso_date,
            local_timezone=self.tz.key,
            day_start=window.start,
            day_end=window.end,
            day_length_hours=round(window.length_hours, 2),
            sources_checked=sources_checked,
            raw_record_count=len(raw_records),
            normalized_event_count=event_count,
            derived_feature_count=derived_count,
            series_point_count=point_count,
            coverage=coverage,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
            started_at=started,
            completed_at=datetime.now().astimezone(),
        )

        timeline = DayTimeline(
            date=window.iso_date,
            local_timezone=self.tz.key,
            day_start=window.start,
            day_end=window.end,
            day_length_hours=round(window.length_hours, 2),
            generated_at=datetime.now().astimezone(),
            lanes=lanes,
            summary=summary,
            highlights=highlights,
            mock_data=self.settings.use_mock_data,
        )

        self.repository.save_raw_records(window.day, raw_records)
        self.repository.save_timeline(timeline)
        self.repository.finish_sync(
            run_id,
            "error" if errors else ("partial" if warnings else "ok"),
            summary.model_dump(mode="json", by_alias=True),
        )
        return timeline

    async def get_or_sync(
        self, *, now: datetime | None = None, day: date_type | None = None
    ) -> DayTimeline:
        window = self.window_for(day) if day is not None else self.yesterday(now=now)
        cached = self.repository.get_timeline(window.day)
        if cached is not None and not self._is_stale_partial(cached, window, now=now):
            return cached
        return await self.sync(force_refresh=cached is not None, now=now, day=window.day)

    def _is_stale_partial(
        self, timeline: DayTimeline, window: DayWindow, *, now: datetime | None = None
    ) -> bool:
        """True when a *finished* day is being served from a mid-day snapshot.

        A day synced while it was still in progress only holds the hours that
        had happened by then. Left alone that snapshot is served forever, so the
        morning after shows a day that stops at breakfast.

        The check deliberately only fires once the day is over. Re-fetching a
        day that is *still* in progress would be defensible on freshness
        grounds, but the page polls every minute and a Garmin fetch spawns and
        authenticates an MCP subprocess — so today stays cached, and the Refresh
        control is how you ask for its latest hours.
        """
        moment = (now or datetime.now(self.tz)).astimezone(self.tz)
        if moment < window.end:
            return False  # the day is still running; nothing is missing yet

        generated = timeline.generated_at
        if generated.tzinfo is None:  # pragma: no cover - defensive
            generated = generated.replace(tzinfo=window.end.tzinfo)
        return generated < window.end

    def available_days(self, *, span_days: int = 45, now: datetime | None = None) -> list[dict]:
        """Which days the calendar can offer, and which already hold data.

        Days beyond today are never selectable. A day with no stored timeline is
        still selectable — it is fetched on demand — but the calendar marks it
        so the difference between "nothing recorded" and "not looked at yet" is
        visible rather than guessed.
        """
        today = self.today(now=now)
        stored = {row["date"]: row for row in self.repository.stored_days()}
        days: list[dict] = []
        for offset in range(span_days):
            day = today - timedelta(days=offset)
            record = stored.get(day.isoformat())
            days.append(
                {
                    "date": day.isoformat(),
                    "isToday": day == today,
                    "isYesterday": day == today - timedelta(days=1),
                    "stored": record is not None,
                    "eventCount": (record or {}).get("event_count"),
                    "coverage": (record or {}).get("coverage"),
                    "hasData": bool((record or {}).get("event_count")),
                }
            )
        return days


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
