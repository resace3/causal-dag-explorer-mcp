"""Choosing which MCP integrations supply the day.

Two properties matter. A source switched off must not be contacted at all —
reporting it as connected would describe an attempt never made. And the order
must actually reach the composite provider, or the priority shown in the panel
is decoration.
"""

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
        routes.configure(repository, sync_service)
        yield test_client


def test_the_default_selection_follows_the_configured_route_order(sync_service):
    assert sync_service.source_selection() == sync_service.default_selection()


def test_every_available_source_is_selected_by_default(sync_service):
    available = {item["id"] for item in sync_service.available_sources()}
    assert set(sync_service.source_selection()) == available


def test_the_order_reaches_the_provider_routes(sync_service):
    ids = [item["id"] for item in sync_service.available_sources()]
    if len(ids) < 2:
        pytest.skip("This configuration has only one source.")

    sync_service.set_source_selection(list(reversed(ids)))
    first = sync_service._configured_for_selection().wearable.routes
    sync_service.set_source_selection(ids)
    second = sync_service._configured_for_selection().wearable.routes
    assert first != second, "reordering sources must change the merge order"


def test_switching_home_assistant_off_stops_it_being_read(sync_service):
    ids = [item["id"] for item in sync_service.available_sources()]
    others = [item for item in ids if item != "home_assistant"]
    if not others:
        pytest.skip("Home Assistant is the only source here.")

    sync_service.set_source_selection(others)
    assert sync_service.home_assistant_selected() is False
    sync_service.set_source_selection(ids)
    assert sync_service.home_assistant_selected() is True


def test_a_source_no_longer_in_the_config_is_dropped_from_a_stored_selection(
    repository, sync_service
):
    repository.set_source_selection(["home_assistant", "a_source_that_left"])
    assert "a_source_that_left" not in sync_service.source_selection()


def test_a_source_added_after_the_choice_joins_it_rather_than_reading_as_switched_off(
    repository, sync_service
):
    """The case that made this necessary: connecting ActivityWatch to an
    install that already had a stored selection. It was never on offer when the
    choice was made, so reporting it "switched off in the MCPs panel" describes
    a decision nobody took — and the newly connected source would show nothing
    until the user found the switch."""
    repository.set_source_selection(["home_assistant"], known=["home_assistant"])
    selection = sync_service.source_selection()

    assert "activitywatch" in selection
    assert selection[-1] == "activitywatch", "a new source joins last, not first"


def test_a_source_that_was_offered_and_left_out_stays_switched_off(repository, sync_service):
    available = [item["id"] for item in sync_service.available_sources()]
    keep = [source_id for source_id in available if source_id != "activitywatch"]
    sync_service.set_source_selection(keep)

    assert "activitywatch" not in sync_service.source_selection(), (
        "a deliberate deselection must survive; otherwise the switch does nothing"
    )


def test_activitywatch_is_offered_and_switchable(sync_service):
    assert "activitywatch" in [item["id"] for item in sync_service.available_sources()]
    assert sync_service.activitywatch_selected() is True


def test_a_source_that_is_not_a_wearable_leaves_the_merge_order_intact(sync_service):
    """ActivityWatch supplies no body metric, so it belongs to no route.

    Mapping it into the wearable route list would put a `None` in there and
    every metric would then resolve against a route that does not exist.
    """
    sync_service.set_source_selection(
        ["activitywatch", *(item["id"] for item in sync_service.available_sources()
                            if item["id"] != "activitywatch")]
    )
    routes = sync_service._configured_for_selection().wearable.routes
    assert None not in routes
    assert routes, "the wearable routes must survive a non-wearable source being first"


async def test_switching_activitywatch_off_leaves_its_lane_saying_so(sync_service):
    others = [
        item["id"] for item in sync_service.available_sources() if item["id"] != "activitywatch"
    ]
    sync_service.set_source_selection(others)
    assert sync_service.activitywatch_selected() is False

    timeline = await sync_service.sync(force_refresh=True)
    lane = next(lane for lane in timeline.lanes if lane.id == "computer_use")
    assert lane.available is False
    assert "Switched off in the MCPs panel" in lane.unavailable_reason
    assert not lane.events, "a source that was never contacted cannot have produced events"


def test_changing_the_selection_rebuilds_the_cached_provider(sync_service):
    sync_service._provider = object()
    sync_service.set_source_selection([item["id"] for item in sync_service.available_sources()])
    assert sync_service._provider is None, "a stale provider would keep the old routes"


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_the_selection_endpoint_reports_what_is_available(client):
    body = client.get("/api/sources/selection").json()
    assert body["available"]
    assert body["selected"]
    assert set(body["selected"]) <= {item["id"] for item in body["available"]}


def test_an_empty_selection_is_refused(client):
    response = client.put("/api/sources/selection", json={"selected": []})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "no_sources_selected"


def test_an_unknown_source_is_refused_and_the_real_ones_listed(client):
    response = client.put("/api/sources/selection", json={"selected": ["fitbit"]})
    assert response.status_code == 400
    assert "fitbit" in response.json()["error"]["message"]


def test_a_deselected_source_is_reported_as_off_rather_than_connected(client):
    report = client.get("/api/data-sources").json()
    if report["mockData"]:
        pytest.skip("Mock mode has no switchable MCP rows.")

    available = client.get("/api/sources/selection").json()["available"]
    ids = [item["id"] for item in available]
    if "home_assistant" not in ids or len(ids) < 2:
        pytest.skip("Needs Home Assistant plus one more source.")

    client.put("/api/sources/selection", json={"selected": ["home_assistant"]})
    off = [
        source
        for source in client.get("/api/data-sources").json()["sources"]
        if not source["selected"]
    ]
    assert off, "one source should now be switched off"
    for source in off:
        assert source["status"] == "disconnected"
        assert "Switched off" in source["detail"]
        assert source["priority"] is None


def test_a_switchable_source_carries_its_merge_position(client):
    report = client.get("/api/data-sources").json()
    ranked = [s for s in report["sources"] if s["priority"] is not None]
    for source in ranked:
        assert source["selected"] is True
        assert source["priority"] >= 1


def test_mock_mode_leaves_rows_alone_because_nothing_is_switchable(client):
    """`USE_MOCK_DATA` forces the mock provider, so the picker cannot apply.

    A mock row reported as "switched off" would be a lie about a switch that
    does not govern it.
    """
    report = client.get("/api/data-sources").json()
    if not report["mockData"]:
        pytest.skip("Only meaningful with mock data.")
    for source in report["sources"]:
        if source["id"].startswith("wearable_"):
            assert source["selected"] is True
            assert source["priority"] is None
