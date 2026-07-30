"""Regressions found against a live Home Assistant instance.

Each test here corresponds to a bug that only showed up with real data, not
with the mock generator.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest

from app.config.schema import (
    HomeAssistantConfig,
    HomeAssistantEntities,
    HomeAssistantWearableConfig,
    WearableSleepEntities,
)
from app.config.settings import Settings
from app.connectors.home_assistant.client import HomeAssistantClient
from app.connectors.home_assistant.connector import HomeAssistantConnector
from app.connectors.wearables.home_assistant_provider import HomeAssistantWearableProvider
from app.feature_engineering.provenance import detect_gaps
from app.models.raw import RawRecord
from app.normalization.normalizer import normalize


def _settings() -> Settings:
    return Settings(
        HOME_ASSISTANT_URL="http://ha.test:8123",
        HOME_ASSISTANT_TOKEN="token",
        USE_MOCK_DATA=False,
        LOCAL_TIMEZONE="America/New_York",
    )


def _client(payload) -> HomeAssistantClient:
    return HomeAssistantClient(
        "http://ha.test:8123",
        "token",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )


# --------------------------------------------------------------------------
# Home Assistant sends the full state only on the first row of each group.
# --------------------------------------------------------------------------


async def test_minimal_rows_after_the_first_are_not_dropped(new_york):
    """Only row 0 carries `entity_id` and `attributes`; the rest are minimal.

    Before this was handled, exactly one sample per entity survived and every
    later reading was silently lost.
    """
    start = datetime(2025, 6, 10, 0, 0, tzinfo=new_york)
    end = start + timedelta(days=1)

    payload = [
        [
            {
                "entity_id": "sensor.user_steps",
                "state": "11541",
                "attributes": {
                    "unit_of_measurement": "steps",
                    "friendly_name": "User Steps",
                    "state_class": "total_increasing",
                },
                "last_changed": "2025-06-10T04:00:00+00:00",
            },
            {"state": "114", "last_changed": "2025-06-10T04:19:36+00:00"},
            {"state": "147", "last_changed": "2025-06-10T04:49:36+00:00"},
            {"state": "222", "last_changed": "2025-06-10T05:19:36+00:00"},
        ]
    ]

    config = HomeAssistantConfig(
        entities=HomeAssistantEntities(steps=["sensor.user_steps"])
    )
    connector = HomeAssistantConnector(config, _settings(), new_york, client=_client(payload))
    result = await connector.fetch(start, end)

    assert len(result.records) == 4, "every row must survive, not just the first"
    assert [record.value for record in result.records] == [11541.0, 114.0, 147.0, 222.0]
    # The unit is carried forward from the first row too.
    assert {record.unit for record in result.records} == {"steps"}
    assert {record.entity_id for record in result.records} == {"sensor.user_steps"}


# --------------------------------------------------------------------------
# Cumulative daily counters reset at midnight.
# --------------------------------------------------------------------------


def _counter(timestamp: datetime, value: float) -> RawRecord:
    return RawRecord(
        id=RawRecord.make_id("home_assistant", "steps", timestamp.isoformat()),
        source="home_assistant",
        stream="steps",
        entity_id="sensor.user_steps",
        timestamp=timestamp,
        value=value,
        unit="steps",
    )


def test_counter_reset_is_flagged_and_not_treated_as_a_negative_step_count(new_york):
    start = datetime(2025, 6, 10, 23, 0, tzinfo=new_york)
    records = [
        _counter(start, 11541),
        _counter(start + timedelta(hours=1), 114),  # midnight reset
        _counter(start + timedelta(hours=2), 260),
    ]
    result = normalize(records, start, start + timedelta(hours=3))
    samples = result.samples_for("steps")

    assert [sample.value for sample in samples] == [11541.0, 114.0, 260.0]
    # The reading straight after a reset is marked so rate maths can skip it.
    assert [sample.quality for sample in samples] == [1.0, 0.5, 1.0]
    assert not result.warnings, "one reset per midnight is expected, not a fault"


def test_more_resets_than_midnights_is_warned(new_york):
    start = datetime(2025, 6, 10, 8, 0, tzinfo=new_york)
    records = [
        _counter(start, 500),
        _counter(start + timedelta(hours=1), 100),
        _counter(start + timedelta(hours=2), 900),
        _counter(start + timedelta(hours=3), 50),
    ]
    result = normalize(records, start, start + timedelta(hours=4))
    assert any("reset" in warning for warning in result.warnings)


# --------------------------------------------------------------------------
# Silence is not the same as an explicit outage.
# --------------------------------------------------------------------------


def test_explicit_unavailable_is_a_gap_however_brief(new_york):
    start = datetime(2025, 6, 10, 0, 0, tzinfo=new_york)

    def record(minutes: int, value, unavailable=False):
        moment = start + timedelta(minutes=minutes)
        return RawRecord(
            id=f"raw-{minutes}",
            source="home_assistant",
            stream="illuminance",
            entity_id="sensor.lux",
            timestamp=moment,
            value=value,
            attributes={"unavailable": unavailable},
        )

    records = [
        record(0, 120.0),
        record(30, None, unavailable=True),
        record(60, 140.0),
    ]
    result = normalize(records, start, start + timedelta(hours=2))

    outages = result.unavailable_for("illuminance")
    assert len(outages) == 1
    assert outages[0].start_time == start + timedelta(minutes=30)

    # A 30-minute outage is shorter than a 3-hour staleness limit, but it is
    # *known* missing data and must still be reported.
    gaps = detect_gaps(
        result.samples_for("illuminance"),
        start,
        start + timedelta(hours=2),
        timedelta(hours=3),
        explicit=[(period.start_time, period.end_time) for period in outages],
    )
    assert gaps
    assert any("unavailable" in (gap.reason or "") for gap in gaps)


def test_quiet_sensor_within_the_staleness_limit_is_not_a_gap(new_york):
    """Home Assistant records changes, not samples: steady is not missing."""
    start = datetime(2025, 6, 10, 0, 0, tzinfo=new_york)
    records = [
        RawRecord(
            id="raw-a",
            source="home_assistant",
            stream="illuminance",
            entity_id="sensor.lux",
            timestamp=start,
            value=7.0,
        ),
        RawRecord(
            id="raw-b",
            source="home_assistant",
            stream="illuminance",
            entity_id="sensor.lux",
            timestamp=start + timedelta(hours=2),
            value=9.0,
        ),
    ]
    result = normalize(records, start, start + timedelta(hours=2, minutes=1))
    gaps = detect_gaps(
        result.samples_for("illuminance"),
        start,
        start + timedelta(hours=2, minutes=1),
        timedelta(hours=4),
    )
    assert gaps == []


# --------------------------------------------------------------------------
# Sleep reconstructed from daily summary sensors.
# --------------------------------------------------------------------------


def _sleep_config() -> HomeAssistantWearableConfig:
    return HomeAssistantWearableConfig(
        device_name="Fitbit Inspire 3",
        sleep=WearableSleepEntities(
            start_time="sensor.user_sleep_start_time",
            time_in_bed_minutes="sensor.user_sleep_time_in_bed",
            minutes_asleep="sensor.user_sleep_minutes_asleep",
            efficiency="sensor.user_sleep_efficiency",
        ),
    )


def _sleep_payload(clock: str, in_bed: str, reported_utc: str):
    return [
        [
            {
                "entity_id": "sensor.user_sleep_start_time",
                "state": "",
                "attributes": {},
                "last_changed": "2025-06-10T04:00:00+00:00",
            },
            {"state": clock, "last_changed": reported_utc},
        ],
        [
            {
                "entity_id": "sensor.user_sleep_time_in_bed",
                "state": "0",
                "attributes": {"unit_of_measurement": "min"},
                "last_changed": "2025-06-10T04:00:00+00:00",
            },
            {"state": in_bed, "last_changed": reported_utc},
        ],
        [
            {
                "entity_id": "sensor.user_sleep_minutes_asleep",
                "state": "0",
                "attributes": {},
                "last_changed": "2025-06-10T04:00:00+00:00",
            },
            {"state": "344", "last_changed": reported_utc},
        ],
        [
            {
                "entity_id": "sensor.user_sleep_efficiency",
                "state": "0",
                "attributes": {},
                "last_changed": "2025-06-10T04:00:00+00:00",
            },
            {"state": "85", "last_changed": reported_utc},
        ],
    ]


async def test_sleep_is_reconstructed_from_a_clock_string_plus_a_duration(new_york):
    start = datetime(2025, 6, 10, 0, 0, tzinfo=new_york)
    end = start + timedelta(days=1)
    # Reported at 09:49 local; the night began 02:11 the same morning.
    payload = _sleep_payload("02:11", "405", "2025-06-10T13:49:36+00:00")

    provider = HomeAssistantWearableProvider(_sleep_config(), _client(payload), new_york)
    records = await provider.get_sleep(start, end)

    assert len(records) == 1
    record = records[0]
    assert record.start == datetime(2025, 6, 10, 2, 11, tzinfo=new_york)
    assert record.end == datetime(2025, 6, 10, 8, 56, tzinfo=new_york)
    assert record.time_in_bed_minutes == 405
    assert record.is_main_sleep
    assert record.efficiency == pytest.approx(0.85)
    assert record.stages == [], "this integration publishes no stages; none are invented"
    assert record.metadata["reconstructedFrom"] == "daily sleep summary sensors"
    assert record.metadata["reportedStartClock"] == "02:11"
    assert "reconstructed" in record.metadata["note"]


async def test_a_late_bedtime_is_attributed_to_the_previous_day(new_york):
    """23:30 reported the next morning belongs to the night before."""
    start = datetime(2025, 6, 9, 0, 0, tzinfo=new_york)
    end = datetime(2025, 6, 11, 0, 0, tzinfo=new_york)
    payload = _sleep_payload("23:30", "420", "2025-06-10T12:00:00+00:00")

    provider = HomeAssistantWearableProvider(_sleep_config(), _client(payload), new_york)
    records = await provider.get_sleep(start, end)

    assert len(records) == 1
    record = records[0]
    assert record.start == datetime(2025, 6, 9, 23, 30, tzinfo=new_york)
    assert record.end == datetime(2025, 6, 10, 6, 30, tzinfo=new_york)
    assert record.end <= datetime(2025, 6, 10, 8, 0, tzinfo=new_york)


async def test_provider_declares_only_sleep(new_york):
    provider = HomeAssistantWearableProvider(_sleep_config(), _client([]), new_york)
    capabilities = await provider.get_capabilities()
    assert capabilities.capabilities == ["sleep"]
    assert await provider.get_heart_rate(
        datetime(2025, 6, 10, tzinfo=new_york), datetime(2025, 6, 11, tzinfo=new_york)
    ) == []
    assert await provider.get_hrv(
        datetime(2025, 6, 10, tzinfo=new_york), datetime(2025, 6, 11, tzinfo=new_york)
    ) == []


async def test_empty_sleep_sensors_produce_no_record(new_york):
    payload = _sleep_payload("", "0", "2025-06-10T13:49:36+00:00")
    provider = HomeAssistantWearableProvider(_sleep_config(), _client(payload), new_york)
    records = await provider.get_sleep(
        datetime(2025, 6, 10, tzinfo=new_york), datetime(2025, 6, 11, tzinfo=new_york)
    )
    assert records == []


# --------------------------------------------------------------------------
# Presence: one person, one block.
# --------------------------------------------------------------------------


async def test_a_person_and_its_device_tracker_do_not_draw_two_blocks(
    repository, example_config, monkeypatch, new_york
):
    from app.config.schema import HomePresenceRule
    from app.connectors.wearables.connector import WearableConnector
    from app.connectors.wearables.mock import MockWearableProvider
    from app.services.sync import SyncService

    example_config.home_assistant.entities.presence = [
        "person.user",
        "device_tracker.phone",
    ]
    example_config.feature_engineering.home_presence = HomePresenceRule(
        entity_priority=["person.user", "device_tracker.phone"]
    )

    payload = [
        [
            {
                "entity_id": "person.user",
                "state": "home",
                "attributes": {},
                "last_changed": "2025-06-10T04:00:00+00:00",
            }
        ],
        [
            {
                "entity_id": "device_tracker.phone",
                "state": "home",
                "attributes": {},
                "last_changed": "2025-06-10T04:00:00+00:00",
            }
        ],
    ]

    settings = _settings()
    service = SyncService(repository, settings, example_config)

    def connectors():
        return (
            HomeAssistantConnector(
                example_config.home_assistant, settings, new_york, client=_client(payload)
            ),
            WearableConnector(MockWearableProvider(new_york, seed=42)),
        )

    monkeypatch.setattr(service, "_connectors", connectors)
    timeline = await service.sync(
        force_refresh=True, now=datetime(2025, 6, 11, 9, 0, tzinfo=new_york)
    )

    presence = next(lane for lane in timeline.lanes if lane.id == "presence")
    blocks = [
        event for event in presence.events if (event.category or "").startswith("presence_")
    ]
    assert len(blocks) == 1, "two trackers describing one person must not stack"
    assert blocks[0].entity_id == "person.user"
    # The tracker that was not drawn is still recorded as evidence.
    assert "device_tracker.phone" in blocks[0].provenance.source_entity_ids


# --------------------------------------------------------------------------
# A step counter must not report the same walk the wearable already recorded.
# --------------------------------------------------------------------------


async def test_step_periods_do_not_duplicate_recorded_workouts(sync_service, fixed_now):
    """The mock day has both wearable workouts and a Home Assistant step counter."""
    timeline = await sync_service.sync(force_refresh=True, now=fixed_now)
    activity = next(lane for lane in timeline.lanes if lane.id == "activity")

    workouts = [event for event in activity.events if event.category != "walking_period"]
    walking = [event for event in activity.events if event.category == "walking_period"]
    assert workouts, "the mock wearable records workout sessions"

    for step_event in walking:
        for workout in workouts:
            overlaps = (
                step_event.start_time < (workout.end_time or workout.start_time)
                and (step_event.end_time or step_event.start_time) > workout.start_time
            )
            assert not overlaps, (
                f"'{step_event.label}' overlaps the recorded '{workout.label}'; "
                "explicit records win over counter-derived periods"
            )

    # The step-rate line still carries the movement, so nothing is lost.
    assert activity.series and activity.series[0].points
