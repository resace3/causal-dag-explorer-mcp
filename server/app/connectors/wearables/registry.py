"""Wearable provider registry — the extension point for new vendors.

To add Oura, Fitbit, Garmin, Apple Health or Health Connect:

1. Create `app/connectors/wearables/<vendor>.py` with a class that implements
   `WearableProvider` (subclass `BaseWearableProvider` and override only the
   metrics the vendor really exposes).
2. Register the factory in `_FACTORIES` below.
3. Add the provider name to the `Literal` in `app/config/schema.py::WearableConfig`.
4. Document any new environment variables in `.env.example` and the README.

Nothing else in the application needs to change: capability metadata flows to
the frontend automatically and lanes without a supporting capability are hidden.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from zoneinfo import ZoneInfo

from ...config.schema import AppConfig
from ...config.settings import REPO_ROOT, Settings
from ..home_assistant.client import HomeAssistantClient
from .base import WearableProvider
from .composite import CompositeWearableProvider
from .garmin_mcp import GarminMcpProvider
from .home_assistant_provider import HomeAssistantWearableProvider
from .json_file import JsonFileWearableProvider
from .mock import MockWearableProvider

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[AppConfig, Settings, ZoneInfo], WearableProvider]


def _build_mock(config: AppConfig, settings: Settings, tz: ZoneInfo) -> WearableProvider:
    return MockWearableProvider(
        tz=tz, seed=settings.mock_data_seed, device=config.wearable.device_name
    )


def _build_json_file(config: AppConfig, settings: Settings, tz: ZoneInfo) -> WearableProvider:
    raw_path = Path(config.wearable.json_file.path)
    path = raw_path if raw_path.is_absolute() else (REPO_ROOT / raw_path)
    return JsonFileWearableProvider(path)


def _build_home_assistant(
    config: AppConfig, settings: Settings, tz: ZoneInfo
) -> WearableProvider:
    client = None
    if settings.home_assistant_url and settings.home_assistant_token:
        client = HomeAssistantClient(
            settings.home_assistant_url,
            settings.home_assistant_token,
            timeout=settings.home_assistant_timeout_seconds,
            verify_ssl=settings.home_assistant_verify_ssl,
        )
    return HomeAssistantWearableProvider(config.wearable.home_assistant, client, tz)


def _build_garmin_mcp(
    config: AppConfig, settings: Settings, tz: ZoneInfo
) -> WearableProvider:
    garmin = config.wearable.garmin_mcp
    return GarminMcpProvider(garmin, config.mcp.server(garmin.mcp_server), tz)


def _build_auto(config: AppConfig, settings: Settings, tz: ZoneInfo) -> WearableProvider:
    """Try each configured route in order, per metric."""
    routes: list[tuple[str, WearableProvider]] = []
    for name in config.wearable.routes:
        factory = _FACTORIES.get(name)
        if factory is None or name == "auto":
            continue
        try:
            routes.append((name, factory(config, settings, tz)))
        except Exception as exc:  # noqa: BLE001 - a bad route must not block the rest
            logger.warning("Wearable route '%s' could not be built: %s", name, exc)
    if not routes:
        raise ValueError(
            "wearable.provider is 'auto' but none of wearable.routes could be built. "
            f"Configured routes: {config.wearable.routes}."
        )
    return CompositeWearableProvider(routes)


_FACTORIES: dict[str, ProviderFactory] = {
    "mock": _build_mock,
    "json_file": _build_json_file,
    "home_assistant": _build_home_assistant,
    "garmin_mcp": _build_garmin_mcp,
    "auto": _build_auto,
}


def available_providers() -> list[str]:
    return sorted(_FACTORIES)


def build_provider(config: AppConfig, settings: Settings, tz: ZoneInfo) -> WearableProvider:
    """Resolve the configured provider. `USE_MOCK_DATA=true` always wins."""
    if settings.use_mock_data:
        name = "mock"
    else:
        name = settings.wearable_provider or config.wearable.provider

    factory = _FACTORIES.get(name)
    if factory is None:
        raise ValueError(
            f"Unknown wearable provider '{name}'. Available providers: "
            f"{', '.join(available_providers())}."
        )
    return factory(config, settings, tz)
