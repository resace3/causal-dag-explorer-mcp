"""Turn Home Assistant state history into `RawRecord`s.

The connector degrades gracefully: an unreachable or unauthenticated instance
produces a specific, actionable status plus zero records, and the rest of the
timeline still renders from wearable data.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ...config.schema import ENTITY_GROUPS, HomeAssistantConfig
from ...config.settings import Settings
from ...models.raw import RawRecord
from ...models.sources import SourceStatus
from ..base import ConnectorResult
from .client import (
    HomeAssistantClient,
    HomeAssistantError,
)
from .mock_states import generate_history

logger = logging.getLogger(__name__)

SOURCE_ID = "home_assistant"
SOURCE_NAME = "Home Assistant"

UNKNOWN_STATES = {"unknown", "unavailable", "none", "", "null"}

# Which config group maps to which logical stream in the timeline.
STREAM_BY_DOMAIN = {
    "presence": "presence",
    "motion": "motion",
    "temperature": "room_temperature",
    "illuminance": "illuminance",
    "humidity": "humidity",
    "sleep": "bed_occupancy",
    "door": "door",
    "device_use": "device_use",
    "app_usage": "app_usage",
    "tv_use": "tv_use",
    "tv_app": "tv_app",
    "tv_title": "tv_title",
    "steps": "steps",
    "resting_heart_rate": "resting_heart_rate",
    "heart_rate": "heart_rate",
    "location": "location",
    "place": "place",
}

NUMERIC_DOMAINS = {
    "temperature",
    "illuminance",
    "humidity",
    "steps",
    "resting_heart_rate",
    "heart_rate",
}


class HomeAssistantConnector:
    def __init__(
        self,
        config: HomeAssistantConfig,
        settings: Settings,
        tz: ZoneInfo,
        *,
        client: HomeAssistantClient | None = None,
    ) -> None:
        self.config = config
        self.settings = settings
        self.tz = tz
        self._client = client

    # -- status ----------------------------------------------------------

    @property
    def capabilities(self) -> list[str]:
        entities = self.config.entities
        return [
            STREAM_BY_DOMAIN[name]
            for name in ENTITY_GROUPS
            if getattr(entities, name)
        ]

    def _build_client(self) -> HomeAssistantClient | None:
        if self._client is not None:
            return self._client
        url = self.settings.home_assistant_url
        token = self.settings.home_assistant_token
        if not url or not token:
            return None
        return HomeAssistantClient(
            url,
            token,
            timeout=self.settings.home_assistant_timeout_seconds,
            verify_ssl=self.settings.home_assistant_verify_ssl,
        )

    async def check_status(self) -> tuple[SourceStatus, str | None]:
        if not self.config.enabled:
            return "disconnected", "Home Assistant is disabled in config.yaml."
        if self.settings.use_mock_data:
            return "mock_data", (
                "USE_MOCK_DATA=true — states are generated locally, no Home Assistant "
                "instance is contacted."
            )
        client = self._build_client()
        if client is None:
            return "disconnected", (
                "Set HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN in .env to connect."
            )
        try:
            await client.ping()
        except HomeAssistantError as exc:
            return "error", str(exc)
        return "connected", f"Connected to {client.base_url}"

    # -- fetching --------------------------------------------------------

    async def fetch(self, start: datetime, end: datetime) -> ConnectorResult:
        result = ConnectorResult(capabilities=self.capabilities)
        entity_ids = self.config.entities.all_entity_ids()
        result.entity_count = len(entity_ids)

        if not self.config.enabled:
            result.status = "disconnected"
            result.detail = "Home Assistant is disabled in config.yaml."
            return result

        if not entity_ids:
            result.status = "error"
            result.detail = (
                "No Home Assistant entities are configured. Add entity IDs under "
                "home_assistant.entities in config.yaml."
            )
            result.errors.append(result.detail)
            return result

        if self.settings.use_mock_data:
            history = generate_history(
                self.config.entities, start, end, self.tz, self.settings.mock_data_seed
            )
            result.status = "mock_data"
            result.detail = (
                f"Mock states for {len(entity_ids)} configured entities "
                f"(seed {self.settings.mock_data_seed})."
            )
        else:
            client = self._build_client()
            if client is None:
                result.status = "disconnected"
                result.detail = (
                    "Set HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN in .env to connect. "
                    "Wearable data is still displayed."
                )
                result.warnings.append(result.detail)
                return result
            try:
                history = await client.get_history(entity_ids, start, end)
            except HomeAssistantError as exc:
                result.status = "error"
                result.detail = f"{exc} Wearable data is still displayed."
                result.errors.append(result.detail)
                return result
            result.status = "connected"
            result.detail = f"Read history for {len(entity_ids)} entities from {client.base_url}"

        result.records, parse_warnings = self._parse_history(history, start, end)
        result.warnings.extend(parse_warnings)

        missing = self._missing_entities(entity_ids, result.records)
        if missing:
            message = (
                "Home Assistant returned no history for: "
                + ", ".join(sorted(missing))
                + ". Check that these entity IDs exist and that recorder is enabled for them."
            )
            result.warnings.append(message)

        return result

    def _missing_entities(self, entity_ids: list[str], records: list[RawRecord]) -> set[str]:
        seen = {record.entity_id for record in records if record.entity_id}
        return set(entity_ids) - seen

    def _parse_history(
        self, history: list[list[dict[str, Any]]], start: datetime, end: datetime
    ) -> tuple[list[RawRecord], list[str]]:
        records: list[RawRecord] = []
        warnings: list[str] = []
        seen_keys: set[tuple[str, str]] = set()

        for group in history:
            # Home Assistant sends the full state only for the first row of an
            # entity's history; every later row carries just `state` and
            # `last_changed`. Both the entity id and the attributes have to be
            # carried forward, or all but the first sample is silently lost.
            group_entity_id: str | None = None
            group_attributes: dict[str, Any] = {}

            for row in group:
                entity_id = row.get("entity_id") or group_entity_id
                if not entity_id:
                    continue
                if row.get("entity_id"):
                    group_entity_id = entity_id
                    group_attributes = row.get("attributes") or {}

                domain = self.config.entities.domain_for(entity_id)
                if domain is None:
                    continue
                stream = STREAM_BY_DOMAIN[domain]

                stamp_raw = row.get("last_changed") or row.get("last_updated")
                timestamp = _parse_timestamp(stamp_raw)
                if timestamp is None:
                    warnings.append(
                        f"Skipped a {entity_id} state with an unreadable timestamp "
                        f"({stamp_raw!r})."
                    )
                    continue
                timestamp = timestamp.astimezone(self.tz)
                if timestamp < start or timestamp >= end:
                    continue

                key = (entity_id, timestamp.isoformat())
                if key in seen_keys:
                    continue  # Home Assistant can repeat a state at a boundary.
                seen_keys.add(key)

                attributes = row.get("attributes") or group_attributes
                state_text = str(row.get("state", "")).strip()
                unavailable = state_text.lower() in UNKNOWN_STATES

                value: float | str | None
                if unavailable:
                    value = None
                elif domain in NUMERIC_DOMAINS:
                    value = _parse_float(state_text)
                    if value is None:
                        warnings.append(
                            f"{entity_id} reported a non-numeric state '{state_text}' "
                            "and was treated as missing."
                        )
                else:
                    value = state_text

                records.append(
                    RawRecord(
                        id=RawRecord.make_id(SOURCE_ID, stream, f"{entity_id}|{key[1]}"),
                        source=SOURCE_ID,
                        stream=stream,
                        entity_id=entity_id,
                        device=attributes.get("friendly_name"),
                        timestamp=timestamp,
                        value=value,
                        unit=attributes.get("unit_of_measurement"),
                        attributes={
                            "raw_state": state_text,
                            "unavailable": unavailable,
                            "device_class": attributes.get("device_class"),
                            "friendly_name": attributes.get("friendly_name"),
                        },
                    )
                )

        records.sort(key=lambda record: (record.stream, record.entity_id or "", record.timestamp))
        return records, warnings


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
