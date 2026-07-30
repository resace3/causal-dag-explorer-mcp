"""Phone location: place names only, never coordinates."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.config.schema import PhoneLocationRule
from app.models.raw import RawRecord
from app.normalization.normalizer import normalize


def _tracker(timestamp: datetime, state: str) -> RawRecord:
    """A device-tracker record as the connector produces it.

    Home Assistant puts latitude/longitude/gps_accuracy in the attributes; the
    connector keeps only the ones it needs, so they never reach this far.
    """
    return RawRecord(
        id=f"loc-{timestamp.isoformat()}",
        source="home_assistant",
        stream="location",
        entity_id="device_tracker.phone",
        timestamp=timestamp,
        value=state,
        attributes={"raw_state": state, "unavailable": False},
    )


def _place(timestamp: datetime, address: str, locality: str) -> RawRecord:
    return RawRecord(
        id=f"place-{timestamp.isoformat()}",
        source="home_assistant",
        stream="place",
        entity_id="sensor.phone_geocoded_location",
        timestamp=timestamp,
        value=address,
        attributes={
            "raw_state": address,
            "unavailable": False,
            "locality": locality,
            "administrative_area": "MA",
        },
    )


@pytest.fixture
def location_context(sync_service, new_york):
    """Build a rule context around a day of location records."""
    from app.feature_engineering.context import RuleContext
    from app.services.day import day_window
    from app.connectors.wearables.connector import WearablePayload
    from datetime import date

    window = day_window(date(2025, 6, 10), new_york)

    def build(records, rule: PhoneLocationRule | None = None):
        normalized = normalize(records, window.start, window.end)
        config = sync_service.config.feature_engineering.model_copy(deep=True)
        if rule is not None:
            config.phone_location = rule
        return RuleContext(
            window=window,
            fetch_start=window.start,
            fetch_end=window.end,
            tz=new_york,
            config=config,
            normalized=normalized,
            wearable=WearablePayload(),
        )

    return window, build


def test_zone_and_place_are_both_drawn(location_context):
    from app.feature_engineering.rules import location as rule_module

    window, build = location_context
    records = [
        _tracker(window.start, "home"),
        _tracker(window.start + timedelta(hours=9), "not_home"),
        _tracker(window.start + timedelta(hours=18), "home"),
        _place(window.start, "12 Example St, Springfield, MA 01101, USA", "Springfield"),
        _place(window.start + timedelta(hours=9), "40 Market St, Riverton, MA, USA", "Riverton"),
    ]
    lane = rule_module.build_lane(build(records))

    assert lane.available
    zones = [event for event in lane.events if (event.category or "").startswith("zone_")]
    places = [event for event in lane.events if event.category == "place"]
    assert [event.label for event in zones] == ["Home", "Away", "Home"]
    assert [event.label for event in places] == ["Springfield, MA", "Riverton, MA"]


def test_the_street_address_is_hidden_by_default(location_context):
    from app.feature_engineering.rules import location as rule_module

    window, build = location_context
    records = [
        _place(window.start, "12 Example St, Springfield, MA 01101, USA", "Springfield")
    ]
    lane = rule_module.build_lane(build(records))
    place = next(event for event in lane.events if event.category == "place")

    assert place.label == "Springfield, MA"
    assert "Example St" not in place.label
    assert "Example St" not in lane.model_dump_json()
    assert place.metadata["precision"] == "town or city"
    assert place.provenance.thresholds["include_street_address"] is False


def test_the_street_address_appears_only_when_explicitly_enabled(location_context):
    from app.feature_engineering.rules import location as rule_module

    window, build = location_context
    records = [
        _place(window.start, "12 Example St, Springfield, MA 01101, USA", "Springfield")
    ]
    lane = rule_module.build_lane(
        build(records, PhoneLocationRule(include_street_address=True))
    )
    place = next(event for event in lane.events if event.category == "place")

    assert place.label == "12 Example St, Springfield, MA 01101, USA"
    assert place.metadata["precision"] == "street address"
    assert place.provenance.thresholds["include_street_address"] is True


def test_no_coordinates_ever_reach_the_timeline(location_context):
    """Assert on the data, not the prose.

    The lane's own note explains that coordinates are not read, so a substring
    search would match its own explanation. Walk the payload and check that no
    *field* carries a coordinate instead.
    """
    import json

    from app.feature_engineering.rules import location as rule_module

    window, build = location_context
    records = [
        _tracker(window.start, "home"),
        _place(window.start, "12 Example St, Springfield, MA 01101, USA", "Springfield"),
    ]
    lane = rule_module.build_lane(build(records))
    banned = {"latitude", "longitude", "gps_accuracy", "altitude", "lat", "lon", "lng"}

    def walk(node, path="lane"):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key.lower() not in banned, f"{path}.{key} carries a coordinate"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(json.loads(lane.model_dump_json()))

    # The lane still says plainly that it does not read them.
    zone = next(event for event in lane.events if (event.category or "").startswith("zone_"))
    assert "not read or stored" in zone.metadata["note"]


def test_gps_drift_between_neighbouring_addresses_is_merged(location_context):
    """A stationary phone hops between nearby streets; that is not a move."""
    from app.feature_engineering.rules import location as rule_module

    window, build = location_context
    records = [
        _place(window.start, "178 Thornton Rd, Needham, MA 02492, USA", "Needham"),
        _place(window.start + timedelta(hours=1), "56 Morningside Rd, Needham, MA, USA", "Needham"),
        _place(window.start + timedelta(hours=2), "110 Aletha Rd, Needham, MA, USA", "Needham"),
    ]
    lane = rule_module.build_lane(build(records))
    places = [event for event in lane.events if event.category == "place"]

    assert len(places) == 1, "three addresses in one town are one place"
    assert places[0].label == "Needham, MA"


def test_a_lane_with_no_tracker_says_what_to_configure(location_context):
    from app.feature_engineering.rules import location as rule_module

    _window, build = location_context
    lane = rule_module.build_lane(build([]))
    assert not lane.available
    assert "home_assistant.entities.location" in lane.unavailable_reason


def test_brief_stops_are_dropped(location_context):
    from app.feature_engineering.rules import location as rule_module

    window, build = location_context
    records = [
        _tracker(window.start, "home"),
        _tracker(window.start + timedelta(minutes=1), "not_home"),
        _tracker(window.start + timedelta(minutes=2), "home"),
    ]
    lane = rule_module.build_lane(
        build(records, PhoneLocationRule(min_duration_minutes=10))
    )
    zones = [event for event in lane.events if (event.category or "").startswith("zone_")]
    assert [event.label for event in zones] == ["Home"]
