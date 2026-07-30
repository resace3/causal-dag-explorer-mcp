"""Home Assistant client parsing and failure handling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config.schema import HomeAssistantConfig, HomeAssistantEntities
from app.config.settings import Settings
from app.connectors.home_assistant.client import (
    HomeAssistantAuthError,
    HomeAssistantClient,
    HomeAssistantRateLimitError,
    HomeAssistantUnreachableError,
)
from app.connectors.home_assistant.connector import HomeAssistantConnector


def _settings(**overrides) -> Settings:
    base = {
        "HOME_ASSISTANT_URL": "http://ha.test:8123",
        "HOME_ASSISTANT_TOKEN": "token",
        "USE_MOCK_DATA": False,
        "LOCAL_TIMEZONE": "America/New_York",
    }
    base.update(overrides)
    return Settings(**base)


def _config() -> HomeAssistantConfig:
    return HomeAssistantConfig(
        entities=HomeAssistantEntities(
            presence=["person.user"],
            illuminance=["sensor.living_room_illuminance"],
            motion=["binary_sensor.living_room_motion"],
        )
    )


def _client(handler) -> HomeAssistantClient:
    return HomeAssistantClient(
        "http://ha.test:8123", "token", transport=httpx.MockTransport(handler)
    )


async def test_ping_reports_auth_failure_with_actionable_text():
    client = _client(lambda request: httpx.Response(401, json={}))
    with pytest.raises(HomeAssistantAuthError) as error:
        await client.ping()
    assert "HOME_ASSISTANT_TOKEN" in str(error.value)


async def test_ping_reports_unreachable_instance():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = _client(handler)
    with pytest.raises(HomeAssistantUnreachableError) as error:
        await client.ping()
    assert "http://ha.test:8123" in str(error.value)


async def test_rate_limit_is_reported_separately():
    client = _client(lambda request: httpx.Response(429, headers={"Retry-After": "30"}))
    with pytest.raises(HomeAssistantRateLimitError) as error:
        await client.ping()
    assert "30" in str(error.value)


async def test_history_is_parsed_into_raw_records(new_york):
    start = datetime(2025, 6, 10, 0, 0, tzinfo=new_york)
    end = start + timedelta(days=1)

    payload = [
        [
            {
                "entity_id": "sensor.living_room_illuminance",
                "state": "412.5",
                "attributes": {"unit_of_measurement": "lx", "friendly_name": "Living Room"},
                "last_changed": "2025-06-10T14:00:00+00:00",
            },
            {
                "entity_id": "sensor.living_room_illuminance",
                "state": "unavailable",
                "attributes": {"unit_of_measurement": "lx"},
                "last_changed": "2025-06-10T15:00:00+00:00",
            },
            {
                "entity_id": "sensor.living_room_illuminance",
                "state": "not-a-number",
                "attributes": {},
                "last_changed": "2025-06-10T16:00:00+00:00",
            },
        ],
        [
            {
                "entity_id": "person.user",
                "state": "home",
                "attributes": {},
                "last_changed": "2025-06-10T12:00:00+00:00",
            }
        ],
    ]

    connector = HomeAssistantConnector(
        _config(),
        _settings(),
        new_york,
        client=_client(lambda request: httpx.Response(200, json=payload)),
    )
    result = await connector.fetch(start, end)

    assert result.status == "connected"
    illuminance = [record for record in result.records if record.stream == "illuminance"]
    assert illuminance[0].value == 412.5
    assert illuminance[0].unit == "lx"
    # `unavailable` becomes a hole, not a value.
    assert illuminance[1].value is None
    assert illuminance[1].attributes["unavailable"] is True
    # Non-numeric numeric states are dropped with an explicit warning.
    assert illuminance[2].value is None
    assert any("non-numeric" in warning for warning in result.warnings)

    presence = [record for record in result.records if record.stream == "presence"]
    assert presence[0].value == "home"


async def test_records_outside_the_window_are_ignored(new_york):
    start = datetime(2025, 6, 10, 0, 0, tzinfo=new_york)
    end = start + timedelta(hours=1)
    payload = [
        [
            {
                "entity_id": "person.user",
                "state": "home",
                "attributes": {},
                "last_changed": "2025-06-09T00:00:00+00:00",
            }
        ]
    ]
    connector = HomeAssistantConnector(
        _config(),
        _settings(),
        new_york,
        client=_client(lambda request: httpx.Response(200, json=payload)),
    )
    result = await connector.fetch(start, end)
    assert result.records == []
    assert any("no history" in warning for warning in result.warnings)


async def test_duplicate_states_at_the_same_timestamp_are_collapsed(new_york):
    start = datetime(2025, 6, 10, 0, 0, tzinfo=new_york)
    end = start + timedelta(days=1)
    row = {
        "entity_id": "person.user",
        "state": "home",
        "attributes": {},
        "last_changed": "2025-06-10T12:00:00+00:00",
    }
    connector = HomeAssistantConnector(
        _config(),
        _settings(),
        new_york,
        client=_client(lambda request: httpx.Response(200, json=[[row, dict(row)]])),
    )
    result = await connector.fetch(start, end)
    assert len([r for r in result.records if r.stream == "presence"]) == 1


async def test_offline_instance_yields_an_error_and_no_records(new_york):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    connector = HomeAssistantConnector(
        _config(), _settings(), new_york, client=_client(handler)
    )
    result = await connector.fetch(
        datetime(2025, 6, 10, tzinfo=new_york), datetime(2025, 6, 11, tzinfo=new_york)
    )
    assert result.status == "error"
    assert result.records == []
    assert "Wearable data is still displayed" in result.detail


async def test_missing_credentials_is_a_disconnected_state_not_an_error(new_york):
    settings = _settings(HOME_ASSISTANT_URL=None, HOME_ASSISTANT_TOKEN=None)
    connector = HomeAssistantConnector(_config(), settings, new_york)
    result = await connector.fetch(
        datetime(2025, 6, 10, tzinfo=new_york), datetime(2025, 6, 11, tzinfo=new_york)
    )
    assert result.status == "disconnected"
    assert not result.errors
    assert "HOME_ASSISTANT_URL" in result.detail


async def test_unconfigured_entities_produce_a_specific_error(new_york):
    config = HomeAssistantConfig(entities=HomeAssistantEntities())
    connector = HomeAssistantConnector(config, _settings(), new_york)
    result = await connector.fetch(
        datetime(2025, 6, 10, tzinfo=new_york), datetime(2025, 6, 11, tzinfo=new_york)
    )
    assert result.status == "error"
    assert "config.yaml" in result.detail


async def test_timestamps_are_converted_to_the_local_timezone(new_york):
    start = datetime(2025, 6, 10, 0, 0, tzinfo=new_york)
    end = start + timedelta(days=1)
    payload = [
        [
            {
                "entity_id": "person.user",
                "state": "home",
                "attributes": {},
                "last_changed": "2025-06-10T16:00:00Z",
            }
        ]
    ]
    connector = HomeAssistantConnector(
        _config(),
        _settings(),
        new_york,
        client=_client(lambda request: httpx.Response(200, json=payload)),
    )
    result = await connector.fetch(start, end)
    record = result.records[0]
    assert record.timestamp.tzinfo is not None
    assert record.timestamp.astimezone(timezone.utc).hour == 16
    assert record.timestamp.hour == 12  # EDT
