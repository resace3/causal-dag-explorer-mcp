"""Partial failure: one broken source must not lose the day."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.config.settings import Settings, reset_settings_cache
from app.connectors.activitywatch.connector import ActivityWatchConnector
from app.connectors.home_assistant.client import HomeAssistantClient
from app.connectors.home_assistant.connector import HomeAssistantConnector
from app.connectors.wearables.base import BaseWearableProvider, WearableCapabilities
from app.connectors.wearables.connector import WearableConnector
from app.services.sync import SyncService


def no_activitywatch(config, settings, tz) -> ActivityWatchConnector:
    """A connector that is switched off in configuration.

    These tests are about Home Assistant and the wearable failing. Leaving
    ActivityWatch enabled would have them reach for a real server on port 5600,
    which is present on a developer's machine and absent in CI — the same test
    exercising two different code paths depending on where it runs.
    """
    return ActivityWatchConnector(
        config.activitywatch.model_copy(update={"enabled": False}), settings, tz
    )


class _BrokenProvider(BaseWearableProvider):
    name = "broken"

    async def get_capabilities(self) -> WearableCapabilities:
        raise RuntimeError("the wearable API returned 500")


class _PartialProvider(BaseWearableProvider):
    """Declares sleep support but fails when asked for it."""

    name = "partial"

    async def get_capabilities(self) -> WearableCapabilities:
        return WearableCapabilities(provider="partial", capabilities=["sleep"])

    async def get_sleep(self, start, end):
        raise RuntimeError("sleep endpoint timed out")


async def test_home_assistant_offline_still_renders_wearable_lanes(
    repository, example_config, monkeypatch, fixed_now, new_york
):
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.test:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "token")
    monkeypatch.setenv("WEARABLE_PROVIDER", "mock")
    monkeypatch.setenv("LOCAL_TIMEZONE", "America/New_York")
    reset_settings_cache()

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    settings = Settings()
    service = SyncService(repository, settings, example_config)

    def connectors():
        home_assistant = HomeAssistantConnector(
            example_config.home_assistant,
            settings,
            new_york,
            client=HomeAssistantClient(
                "http://ha.test:8123", "token", transport=httpx.MockTransport(refuse)
            ),
        )
        from app.connectors.wearables.mock import MockWearableProvider

        return (
            home_assistant,
            WearableConnector(MockWearableProvider(new_york, seed=42)),
            no_activitywatch(example_config, settings, new_york),
        )

    monkeypatch.setattr(service, "_connectors", connectors)
    timeline = await service.sync(force_refresh=True, now=fixed_now)

    lanes = {lane.id: lane for lane in timeline.lanes}
    assert lanes["activity"].available, "wearable lanes must survive a Home Assistant outage"
    assert lanes["sleep"].available
    assert not lanes["environment"].available
    assert "could not be reached" in lanes["environment"].unavailable_reason
    assert any("could not be reached" in error for error in timeline.summary.errors)
    assert "Wearable data is still displayed" in " ".join(timeline.summary.errors)


async def test_broken_wearable_provider_is_reported_not_raised(
    repository, example_config, monkeypatch, fixed_now, new_york
):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    reset_settings_cache()
    service = SyncService(repository, Settings(USE_MOCK_DATA=True), example_config)

    def connectors():
        home_assistant = HomeAssistantConnector(
            example_config.home_assistant, service.settings, new_york
        )
        return (
            home_assistant,
            WearableConnector(_BrokenProvider()),
            no_activitywatch(example_config, service.settings, new_york),
        )

    monkeypatch.setattr(service, "_connectors", connectors)
    timeline = await service.sync(force_refresh=True, now=fixed_now)

    lanes = {lane.id: lane for lane in timeline.lanes}
    assert lanes["environment"].available, "Home Assistant lanes must still render"
    assert any("500" in error for error in timeline.summary.errors)

    # Wearable-only lanes go dark and say why.
    assert not lanes["hrv"].available
    assert not lanes["readiness"].available
    assert not lanes["temperature"].available

    # Heart rate survives on the Home Assistant daily resting value alone — but
    # only as a point, never as a fabricated curve.
    heart_rate = lanes["heart_rate"]
    assert heart_rate.available
    assert heart_rate.series == []
    assert all(event.event_type == "point" for event in heart_rate.events)
    assert all("daily" in event.label.lower() for event in heart_rate.events)


async def test_a_failing_metric_degrades_only_that_metric(
    repository, example_config, monkeypatch, fixed_now, new_york
):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    reset_settings_cache()
    service = SyncService(repository, Settings(USE_MOCK_DATA=True), example_config)

    def connectors():
        home_assistant = HomeAssistantConnector(
            example_config.home_assistant, service.settings, new_york
        )
        return (
            home_assistant,
            WearableConnector(_PartialProvider()),
            no_activitywatch(example_config, service.settings, new_york),
        )

    monkeypatch.setattr(service, "_connectors", connectors)
    timeline = await service.sync(force_refresh=True, now=fixed_now)

    assert any("sleep" in warning for warning in timeline.summary.warnings)
    lanes = {lane.id: lane for lane in timeline.lanes}
    assert lanes["presence"].available

    # The configured environmental fallback takes over, and says so: a
    # bed-occupancy sensor measures time in bed, which is not sleep.
    sleep = lanes["sleep"]
    assert sleep.available
    event = sleep.events[0]
    assert event.measured_or_derived == "derived"
    assert event.label == "Time in bed"
    assert event.provenance.transformation_rule.endswith("from_bed_occupancy")
    assert "no wearable sleep record" in event.provenance.notes[0].lower()


async def test_sync_is_cached_until_forced(sync_service, fixed_now):
    first = await sync_service.sync(force_refresh=True, now=fixed_now)
    cached = await sync_service.sync(now=fixed_now)
    assert cached.generated_at == first.generated_at
    forced = await sync_service.sync(force_refresh=True, now=fixed_now)
    assert forced.generated_at >= first.generated_at


async def test_baselines_use_stored_history_when_enough_exists(sync_service, fixed_now):
    """After several syncs the baseline should come from history, not one day."""
    from datetime import timedelta

    for offset in range(3):
        await sync_service.sync(force_refresh=True, now=fixed_now - timedelta(days=offset))

    day = sync_service.yesterday(now=fixed_now).day
    baselines = sync_service.repository.compute_baselines(day, window_days=30)
    assert "heart_rate" in baselines
    assert baselines["heart_rate"].source == "stored_history"
    assert baselines["heart_rate"].days >= 2


@pytest.mark.parametrize("moment", [datetime(2025, 3, 10, 5, 0), datetime(2025, 11, 3, 5, 0)])
async def test_sync_works_across_daylight_saving_transitions(
    sync_service, new_york, moment
):
    timeline = await sync_service.sync(
        force_refresh=True, now=moment.replace(tzinfo=new_york)
    )
    assert timeline.day_length_hours in (23.0, 25.0)
    assert timeline.lanes
    # Compare real elapsed time. Subtracting two datetimes that share a
    # ZoneInfo uses their wall-clock fields and would always report 24 hours.
    elapsed_hours = (
        timeline.day_end.astimezone(timezone.utc) - timeline.day_start.astimezone(timezone.utc)
    ).total_seconds() / 3600
    assert elapsed_hours == pytest.approx(timeline.day_length_hours)
    assert timeline.day_start.utcoffset() != timeline.day_end.utcoffset()
