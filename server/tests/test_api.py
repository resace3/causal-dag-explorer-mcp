"""Local API contract: shapes, filters, errors and the cache-clearing command."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import create_app


@pytest.fixture
def client(repository, sync_service):
    app = create_app()
    routes.configure(repository, sync_service)
    with TestClient(app) as test_client:
        # `create_app`'s lifespan builds its own singletons; re-point them at the
        # temporary database so tests never touch the developer's data directory.
        routes.configure(repository, sync_service)
        yield test_client


def test_health_reports_the_previous_day(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["localTimezone"] == "America/New_York"
    assert body["mockData"] is True


def test_config_never_leaks_the_home_assistant_token(client):
    body = client.get("/api/config").json()
    serialized = str(body).lower()
    assert "token" not in serialized
    assert body["lightThresholds"]["dark"]["maxLux"] == 5


def test_data_sources_lists_one_row_per_mcp_integration(client):
    body = client.get("/api/data-sources").json()
    ids = {source["id"]: source for source in body["sources"]}

    assert ids["home_assistant"]["status"] == "mock_data"
    assert ids["home_assistant"]["mcpServer"] == "ha-mcp"

    # The wearable row is named after its route, never "Wearables" — that is
    # an internal abstraction, not something the user configured.
    assert "wearable" not in ids
    assert not any(source["name"] == "Wearables" for source in body["sources"])

    wearable = ids["wearable_mock"]
    assert wearable["status"] == "mock_data"
    assert "sleep" in wearable["capabilities"]
    assert wearable["transport"] == "mock"

    # Every row declares how it is reached, so the route is stated not implied.
    for source in body["sources"]:
        assert source["transport"] in {"mcp", "rest", "mock", "file"}


def test_yesterday_returns_camel_case_lanes(client):
    body = client.get("/api/yesterday").json()
    assert body["localTimezone"] == "America/New_York"
    assert body["dayLengthHours"] == 24.0
    lane = body["lanes"][0]
    assert set(lane) >= {"id", "label", "description", "accent", "available", "events", "series"}
    event = lane["events"][0]
    assert "measuredOrDerived" in event
    assert "startTime" in event


def test_lane_filter_and_downsampling(client):
    response = client.get(
        "/api/yesterday",
        params={
            "lanes": "heart_rate",
            "samplingIntervalMinutes": 60,
            "includeProvenance": "false",
        },
    )
    body = response.json()
    assert [lane["id"] for lane in body["lanes"]] == ["heart_rate"]
    series = body["lanes"][0]["series"][0]
    assert len(series["points"]) < 40
    assert series["metadata"]["downsampledToMinutes"] == 60
    assert body["lanes"][0]["events"][0]["provenance"] is None


def test_sync_endpoint_rebuilds_the_day(client):
    body = client.post("/api/yesterday/sync", json={"forceRefresh": True}).json()
    assert body["summary"]["rawRecordCount"] > 0
    assert body["summary"]["derivedFeatureCount"] > 0


def test_event_details_include_provenance_and_raw_records(client):
    timeline = client.get("/api/yesterday").json()
    activity = next(lane for lane in timeline["lanes"] if lane["id"] == "activity")
    event_id = activity["events"][0]["id"]

    body = client.get(f"/api/events/{event_id}").json()
    assert body["event"]["id"] == event_id
    assert body["laneId"] == "activity"
    assert body["event"]["provenance"]["transformationRule"]
    assert body["rawRecordCount"] >= 1
    assert body["rawRecords"][0]["id"]


def test_unknown_event_returns_a_structured_404(client):
    response = client.get("/api/events/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "event_not_found"
    assert "sync" in body["error"]["hint"]


def test_raw_record_endpoint(client):
    timeline = client.get("/api/yesterday").json()
    activity = next(lane for lane in timeline["lanes"] if lane["id"] == "activity")
    record_id = activity["events"][0]["provenance"]["rawRecordIds"][0]
    body = client.get(f"/api/raw-records/{record_id}").json()
    assert body["id"] == record_id
    assert body["source"].startswith("wearable")


def test_lane_config_can_be_updated(client):
    before = client.get("/api/lane-config").json()
    assert before["lanes"]["hrv"] is True
    after = client.patch("/api/lane-config", json={"lanes": {"hrv": False}}).json()
    assert after["lanes"]["hrv"] is False


def test_empty_lane_config_update_is_rejected(client):
    response = client.patch("/api/lane-config", json={"lanes": {}})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_update"


def test_cache_can_be_cleared(client):
    client.get("/api/yesterday")
    body = client.delete("/api/cache").json()
    assert body["cleared"]["raw_records"] > 0
    assert body["cleared"]["day_timelines"] == 1


def test_openapi_document_is_served(client):
    schema = client.get("/openapi.json").json()
    assert "/api/yesterday" in schema["paths"]
    assert "/api/data-sources" in schema["paths"]
