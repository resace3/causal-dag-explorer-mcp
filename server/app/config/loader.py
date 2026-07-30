"""Load and validate `config.yaml`, reporting actionable errors."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import ValidationError

from .schema import AppConfig, ConfigError
from .settings import get_settings


def _format_validation_error(error: ValidationError, path: Path) -> str:
    lines = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "<root>"
        lines.append(f"  - {location}: {item['msg']}")
    joined = "\n".join(lines)
    return f"{path.name} is not a valid configuration file:\n{joined}"


def load_config(path: Path | None = None) -> AppConfig:
    settings = get_settings()
    config_path = Path(path) if path is not None else settings.resolved_config_path()

    if not config_path.exists():
        raise ConfigError(
            f"No configuration file found at {config_path}. Copy config.example.yaml "
            "to config.yaml to get started.",
            path=str(config_path),
        )

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - message formatting only
        raise ConfigError(f"{config_path.name} contains invalid YAML: {exc}", str(config_path))

    if not isinstance(raw, dict):
        raise ConfigError(
            f"{config_path.name} must contain a YAML mapping at the top level.",
            str(config_path),
        )

    try:
        config = AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc, config_path), str(config_path)) from exc

    return config


def resolve_timezone(config: AppConfig) -> ZoneInfo:
    """`LOCAL_TIMEZONE` wins over `config.yaml`; both are validated."""
    settings = get_settings()
    name = settings.local_timezone or config.timezone or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(
            f"'{name}' is not a recognised IANA timezone. Set LOCAL_TIMEZONE to a value "
            "such as America/New_York or Europe/Berlin.",
        ) from exc


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()


def reset_config_cache() -> None:
    get_config.cache_clear()
