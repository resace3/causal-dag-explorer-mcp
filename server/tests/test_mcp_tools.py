"""MCP tools return valid structured responses.

The HTTP layer is stubbed so the tools can be exercised without spawning real
servers; `process.ensure_backend` is patched to a no-op for the same reason.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import create_app
from app.mcp import server as mcp_server


@pytest.fixture
def stub_backend(monkeypatch, repository, sync_service):
    app = create_app()
    routes.configure(repository, sync_service)
    client = TestClient(app)
    client.__enter__()
    routes.configure(repository, sync_service)

    monkeypatch.setattr(mcp_server.process, "ensure_backend", lambda: {"started": False})

    class _Response:
        def __init__(self, inner):
            self.status_code = inner.status_code
            self._inner = inner

        def json(self):
            return self._inner.json()

        @property
        def text(self):
            return self._inner.text

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, **kwargs):
            path = url.replace(mcp_server._base_url(), "")
            return _Response(client.request(method, path, **kwargs))

    monkeypatch.setattr(mcp_server.httpx, "AsyncClient", _AsyncClient)
    yield client
    client.__exit__(None, None, None)


async def test_tools_are_registered():
    tools = {tool.name for tool in await mcp_server.mcp.list_tools()}
    assert tools == {
        "launch_yesterday_timeline",
        "sync_yesterday_data",
        "get_yesterday_timeline",
        "get_day_timeline",
        "list_days",
        "get_expected_dag",
        "list_causal_variables",
        "get_data_sources",
        "get_event_details",
        "refresh_timeline",
        "open_timeline",
    }


async def test_every_tool_has_a_description():
    for tool in await mcp_server.mcp.list_tools():
        assert tool.description, f"{tool.name} needs a docstring"
        schema = getattr(tool, "input_schema", None) or tool.inputSchema
        assert schema["type"] == "object"


async def test_sync_yesterday_data_returns_the_documented_fields(stub_backend):
    result = await mcp_server.sync_yesterday_data(force_refresh=True)
    for key in (
        "date_processed",
        "local_timezone",
        "sources_checked",
        "raw_record_count",
        "normalized_event_count",
        "derived_feature_count",
        "data_coverage",
        "warnings",
        "errors",
    ):
        assert key in result
    assert result["raw_record_count"] > 0
    assert json.dumps(result)  # JSON-serialisable for the MCP transport


async def test_get_data_sources_shape(stub_backend):
    result = await mcp_server.get_data_sources()
    assert result["home_assistant"]["status"] == "mock_data"
    assert result["home_assistant"]["mcp_server"] == "ha-mcp"

    # Sources are keyed by their own id, not by a generic "wearable" bucket.
    assert "wearable" not in result
    assert "sleep" in result["wearable_mock"]["capabilities"]
    assert result["wearable_mock"]["provider"] == "mock"
    assert result["wearable_mock"]["transport"] == "mock"


async def test_get_yesterday_timeline_summary_is_compact(stub_backend):
    result = await mcp_server.get_yesterday_timeline()
    assert result["date"]
    assert len(result["lanes"]) == 9
    assert all("eventCount" in lane for lane in result["lanes"])
    # A summary must not carry the full sample payload.
    assert "events" not in result["lanes"][0]


async def test_get_yesterday_timeline_can_return_the_full_payload(stub_backend):
    result = await mcp_server.get_yesterday_timeline(
        lanes="activity", summary_only=False, include_provenance=True
    )
    assert [lane["id"] for lane in result["lanes"]] == ["activity"]
    assert result["lanes"][0]["events"][0]["provenance"]["transformationRule"]


async def test_get_event_details_round_trip(stub_backend):
    timeline = await mcp_server.get_yesterday_timeline(lanes="sleep", summary_only=False)
    event_id = timeline["lanes"][0]["events"][0]["id"]
    details = await mcp_server.get_event_details(event_id)
    assert details["event"]["id"] == event_id
    assert details["laneId"] == "sleep"


async def test_get_event_details_reports_a_missing_id(stub_backend):
    details = await mcp_server.get_event_details("nope")
    assert details["ok"] is False
    assert details["statusCode"] == 404


async def test_a_specific_day_can_be_requested(stub_backend):
    from datetime import date, timedelta

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    result = await mcp_server.get_day_timeline(yesterday)
    assert result["date"]
    assert len(result["lanes"]) == 9


async def test_a_future_day_is_refused(stub_backend):
    from datetime import date, timedelta

    future = (date.today() + timedelta(days=30)).isoformat()
    result = await mcp_server.get_day_timeline(future)
    assert result["ok"] is False
    assert result["error"]["code"] == "future_date"


async def test_list_days_reports_what_is_stored(stub_backend):
    result = await mcp_server.list_days()
    assert result["today"]
    assert result["yesterday"]
    assert isinstance(result["days"], list)
    assert all("stored" in day for day in result["days"])


async def test_the_dag_tool_returns_a_hypothesis_not_an_estimate(stub_backend):
    result = await mcp_server.get_expected_dag("sleep_duration", "exercise")
    assert result["estimated"] is False
    assert "not an estimate" in result["disclaimer"]
    assert result["nodes"] and result["edges"]
    # Unmeasured confounders must be surfaced, not quietly dropped.
    assert result["unmeasuredConfounders"]


async def test_the_dag_tool_rejects_an_unknown_variable(stub_backend):
    result = await mcp_server.get_expected_dag("vibes")
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_causal_question"


async def test_causal_variables_can_be_listed(stub_backend):
    result = await mcp_server.list_causal_variables()
    ids = {item["id"] for item in result["variables"]}
    assert {"sleep_duration", "exercise"} <= ids


async def test_refresh_timeline_reports_what_changed(stub_backend):
    result = await mcp_server.refresh_timeline()
    assert result["date_processed"]
    assert "reloads it automatically" in result["message"]
