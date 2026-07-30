"""Data sources are MCP integrations: the client, the routes, and the panel."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from app.config.schema import McpConfig, McpServerConfig
from app.connectors.mcp_client import (
    McpToolNotAllowed,
    McpStdioSession,
    discover_server,
    resolve_server,
)
from app.connectors.wearables.base import (
    BaseWearableProvider,
    HeartRatePoint,
    WearableCapabilities,
    WearableProviderError,
    WearableSleepRecord,
)
from app.connectors.wearables.composite import CompositeWearableProvider


# --------------------------------------------------------------------------
# The read-only guard
# --------------------------------------------------------------------------


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeResult:
    def __init__(self, text: str, is_error: bool = False) -> None:
        self.content = [_FakeContent(text)]
        self.is_error = is_error


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeToolList:
    def __init__(self, names: list[str]) -> None:
        self.tools = [_FakeTool(name) for name in names]


class _FakeSession:
    def __init__(self, names: list[str], payload: str = "{}") -> None:
        self._names = names
        self._payload = payload
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        return _FakeToolList(self._names)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return _FakeResult(self._payload)


async def test_a_tool_outside_the_allow_list_is_refused():
    """The Garmin MCP can create workouts and delete courses. This app must not."""
    inner = _FakeSession(["get_sleep_data", "delete_course"])
    session = McpStdioSession("garmin", inner, frozenset({"get_sleep_data"}))
    await session.list_tools()

    with pytest.raises(McpToolNotAllowed) as error:
        await session.call_json("delete_course", {"course_id": 1})
    assert "read-only allow-list" in str(error.value)
    assert inner.calls == [], "the refused call must never reach the server"


async def test_an_allowed_tool_is_called_and_parsed():
    inner = _FakeSession(["get_sleep_data"], json.dumps({"ok": True}))
    session = McpStdioSession("garmin", inner, frozenset({"get_sleep_data"}))
    await session.list_tools()
    assert await session.call_json("get_sleep_data", {"date": "2025-06-10"}) == {"ok": True}


async def test_prose_replies_are_treated_as_no_data_not_an_error():
    """These servers answer "No steps data found for ..." in plain text."""
    inner = _FakeSession(["get_steps_data"], "No steps data found for 2025-06-10")
    session = McpStdioSession("garmin", inner, frozenset({"get_steps_data"}))
    await session.list_tools()
    assert await session.call_json("get_steps_data", {"date": "2025-06-10"}) is None


async def test_a_tool_the_server_does_not_expose_returns_nothing():
    inner = _FakeSession(["get_sleep_data"])
    session = McpStdioSession("garmin", inner, frozenset({"get_sleep_data", "get_hrv_data"}))
    await session.list_tools()
    assert await session.call_json("get_hrv_data", {"date": "2025-06-10"}) is None


# --------------------------------------------------------------------------
# Launch configuration
# --------------------------------------------------------------------------


def test_an_explicit_command_wins_over_discovery():
    config = McpServerConfig(command="uvx", args=["garmin-mcp"], env={"A": "1"})
    resolved = resolve_server(config)
    assert resolved is not None
    command, env = resolved
    assert command == ["uvx", "garmin-mcp"]
    assert env["A"] == "1"


def test_discovery_reads_an_mcp_client_config(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    path.write_text(
        json.dumps(
            {"mcpServers": {"garmin": {"command": "cmd", "args": ["/c", "uvx", "garmin-mcp"]}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.connectors.mcp_client.CLIENT_CONFIG_CANDIDATES", (path,))

    entry = discover_server("garmin")
    assert entry is not None
    assert entry["command"] == "cmd"

    resolved = resolve_server(
        McpServerConfig(discover_from_client=True, discovery_name="garmin")
    )
    assert resolved is not None
    assert resolved[0] == ["cmd", "/c", "uvx", "garmin-mcp"]


def test_an_unconfigured_server_resolves_to_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.connectors.mcp_client.CLIENT_CONFIG_CANDIDATES", (tmp_path / "absent.json",)
    )
    assert resolve_server(McpServerConfig(discovery_name="nope")) is None


def test_mcp_config_defaults_the_discovery_name_to_the_key():
    config = McpConfig(servers={"garmin": McpServerConfig()})
    assert config.server("garmin").discovery_name == "garmin"
    # An unlisted server still resolves to sensible defaults.
    assert config.server("ha-mcp").discovery_name == "ha-mcp"


# --------------------------------------------------------------------------
# Several routes at once
# --------------------------------------------------------------------------


class _EmptyProvider(BaseWearableProvider):
    name = "empty"

    async def get_capabilities(self) -> WearableCapabilities:
        return WearableCapabilities(
            provider="empty", capabilities=["sleep", "heart_rate"], status="connected"
        )


class _SleepOnlyProvider(BaseWearableProvider):
    name = "sleep_only"

    def __init__(self, start: datetime) -> None:
        self.start = start

    async def get_capabilities(self) -> WearableCapabilities:
        return WearableCapabilities(
            provider="sleep_only", capabilities=["sleep"], status="connected"
        )

    async def get_sleep(self, start, end):
        return [
            WearableSleepRecord(
                id="s1", start=self.start, end=self.start + timedelta(hours=7)
            )
        ]


class _HeartRateProvider(BaseWearableProvider):
    name = "hr_only"

    def __init__(self, start: datetime) -> None:
        self.start = start

    async def get_capabilities(self) -> WearableCapabilities:
        return WearableCapabilities(
            provider="hr_only", capabilities=["heart_rate"], status="connected"
        )

    async def get_heart_rate(self, start, end):
        return [HeartRatePoint(timestamp=self.start, bpm=61)]


class _BrokenProvider(BaseWearableProvider):
    name = "broken"

    async def get_capabilities(self) -> WearableCapabilities:
        raise WearableProviderError("not signed in")


async def test_routes_are_tried_in_order_and_the_first_with_data_wins(new_york):
    start = datetime(2025, 6, 10, 2, 0, tzinfo=new_york)
    composite = CompositeWearableProvider(
        [("garmin", _EmptyProvider()), ("fitbit", _SleepOnlyProvider(start))]
    )
    await composite.get_capabilities()

    records = await composite.get_sleep(start - timedelta(hours=6), start + timedelta(hours=20))
    assert len(records) == 1
    assert composite.contributions["sleep"] == "fitbit"


async def test_each_metric_picks_its_own_route(new_york):
    start = datetime(2025, 6, 10, 2, 0, tzinfo=new_york)
    composite = CompositeWearableProvider(
        [("garmin", _HeartRateProvider(start)), ("fitbit", _SleepOnlyProvider(start))]
    )
    capabilities = await composite.get_capabilities()
    assert set(capabilities.capabilities) == {"heart_rate", "sleep"}

    window = (start - timedelta(hours=6), start + timedelta(hours=20))
    assert await composite.get_heart_rate(*window)
    assert await composite.get_sleep(*window)
    assert composite.contributions == {"heart_rate": "garmin", "sleep": "fitbit"}


async def test_a_failing_route_is_recorded_and_the_others_still_work(new_york):
    start = datetime(2025, 6, 10, 2, 0, tzinfo=new_york)
    composite = CompositeWearableProvider(
        [("garmin", _BrokenProvider()), ("fitbit", _SleepOnlyProvider(start))]
    )
    capabilities = await composite.get_capabilities()
    assert capabilities.capabilities == ["sleep"]
    assert "garmin" in composite.errors
    assert await composite.get_sleep(start - timedelta(hours=6), start + timedelta(hours=20))


async def test_every_route_failing_is_reported(new_york):
    composite = CompositeWearableProvider([("garmin", _BrokenProvider())])
    with pytest.raises(WearableProviderError) as error:
        await composite.get_capabilities()
    assert "not signed in" in str(error.value)


# --------------------------------------------------------------------------
# The panel itself
# --------------------------------------------------------------------------


async def test_data_sources_name_their_mcp_server(sync_service):
    report = await sync_service.data_sources()
    ids = {source.id for source in report.sources}

    assert "wearable" not in ids, "'Wearables' is an abstraction, not an MCP integration"
    assert all(source.name != "Wearables" for source in report.sources)

    home_assistant = next(s for s in report.sources if s.id == "home_assistant")
    assert home_assistant.mcp_server == "ha-mcp"
    assert home_assistant.transport in {"rest", "mock"}

    for source in report.sources:
        assert source.transport in {"mcp", "rest", "mock", "file"}


async def test_garmin_route_is_presented_as_the_garmin_mcp(
    repository, example_config, monkeypatch, new_york
):
    """A Garmin-backed wearable shows up as the Garmin MCP server, not 'Wearables'."""
    from app.config.settings import Settings
    from app.services.sync import SyncService

    example_config.wearable.provider = "garmin_mcp"
    example_config.wearable.garmin_mcp.mcp_server = "garmin"
    service = SyncService(repository, Settings(USE_MOCK_DATA=False), example_config)

    report = await service.data_sources()
    garmin = next(source for source in report.sources if source.id == "garmin")
    assert garmin.name == "Garmin"
    assert garmin.mcp_server == "garmin"
    assert garmin.transport == "mcp"
