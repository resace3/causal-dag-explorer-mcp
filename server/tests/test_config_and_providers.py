"""Configuration validation and the wearable provider abstraction."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from app.config.loader import load_config, resolve_timezone
from app.config.schema import ConfigError
from app.config.settings import Settings
from app.connectors.wearables.base import WearableProvider, WearableProviderError
from app.connectors.wearables.json_file import JsonFileWearableProvider
from app.connectors.wearables.mock import MockWearableProvider
from app.connectors.wearables.registry import available_providers, build_provider


def test_example_config_is_valid(example_config):
    assert example_config.home_assistant.entities.presence == ["person.user"]
    assert example_config.feature_engineering.light_category.thresholds["bright"].min_lux == 300
    assert example_config.wearable.provider == "mock"


def test_missing_config_file_reports_the_path(tmp_path):
    with pytest.raises(ConfigError) as error:
        load_config(tmp_path / "absent.yaml")
    assert "absent.yaml" in str(error.value)


def test_malformed_yaml_is_reported(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("home_assistant: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert "invalid YAML" in str(error.value)


def test_unknown_key_is_rejected_with_its_location(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("home_assistant:\n  entities:\n    bogus: [x]\n", encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert "home_assistant.entities.bogus" in str(error.value)


def test_overlapping_light_bands_are_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "feature_engineering:\n"
        "  light_category:\n"
        "    thresholds:\n"
        "      dim:\n"
        "        min_lux: 50\n"
        "        max_lux: 5\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert "min_lux must be below max_lux" in str(error.value)


def test_invalid_timezone_is_reported(example_config, monkeypatch):
    monkeypatch.setenv("LOCAL_TIMEZONE", "Mars/Olympus_Mons")
    from app.config.settings import reset_settings_cache

    reset_settings_cache()
    with pytest.raises(ConfigError) as error:
        resolve_timezone(example_config)
    assert "not a recognised IANA timezone" in str(error.value)


def test_registry_lists_the_implemented_providers():
    assert available_providers() == [
        "auto",
        "garmin_mcp",
        "google_health_mcp",
        "home_assistant",
        "json_file",
        "mock",
    ]


def test_mock_data_env_var_overrides_the_configured_provider(example_config, new_york):
    example_config.wearable.provider = "json_file"
    settings = Settings(USE_MOCK_DATA=True, LOCAL_TIMEZONE="America/New_York")
    provider = build_provider(example_config, settings, new_york)
    assert isinstance(provider, MockWearableProvider)


def test_unknown_provider_name_is_reported(example_config, new_york):
    example_config.wearable.provider = "mock"
    settings = Settings(USE_MOCK_DATA=False, WEARABLE_PROVIDER="oura")
    with pytest.raises(ValueError) as error:
        build_provider(example_config, settings, new_york)
    assert "Unknown wearable provider 'oura'" in str(error.value)
    assert "auto, garmin_mcp, google_health_mcp, home_assistant, json_file, mock" in str(error.value)


def test_mock_provider_satisfies_the_protocol(new_york):
    assert isinstance(MockWearableProvider(new_york, seed=1), WearableProvider)


async def test_json_file_provider_reads_an_export(tmp_path, new_york):
    start = datetime(2025, 6, 10, 7, 0, tzinfo=new_york)
    payload = {
        "provider": "apple-health-export",
        "device": "Apple Watch Series 9",
        "capabilities": ["sleep", "heart_rate"],
        "heart_rate": [
            {"timestamp": start.isoformat(), "bpm": 62},
            {"timestamp": (start + timedelta(hours=1)).isoformat(), "bpm": 71},
        ],
        "sleep": [
            {
                "id": "s1",
                "start": (start - timedelta(hours=8)).isoformat(),
                "end": start.isoformat(),
                "isMainSleep": True,
            }
        ],
    }
    path = tmp_path / "wearable.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    provider = JsonFileWearableProvider(path)
    capabilities = await provider.get_capabilities()
    assert capabilities.provider == "apple-health-export"
    assert capabilities.capabilities == ["sleep", "heart_rate"]

    points = await provider.get_heart_rate(start - timedelta(hours=1), start + timedelta(hours=2))
    assert [point.bpm for point in points] == [62, 71]

    # A provider that declares no HRV must return nothing, not fabricate a value.
    assert await provider.get_hrv(start, start + timedelta(hours=2)) == []


async def test_json_file_provider_reports_a_missing_file(tmp_path):
    provider = JsonFileWearableProvider(tmp_path / "absent.json")
    with pytest.raises(WearableProviderError) as error:
        await provider.get_capabilities()
    assert "config.yaml" in str(error.value)


async def test_json_file_provider_reports_a_bad_record(tmp_path, new_york):
    path = tmp_path / "wearable.json"
    path.write_text(
        json.dumps({"capabilities": ["heart_rate"], "heart_rate": [{"bpm": 62}]}),
        encoding="utf-8",
    )
    provider = JsonFileWearableProvider(path)
    with pytest.raises(WearableProviderError) as error:
        await provider.get_heart_rate(
            datetime(2025, 6, 10, tzinfo=new_york), datetime(2025, 6, 11, tzinfo=new_york)
        )
    assert "heart_rate[0].timestamp" in str(error.value)
