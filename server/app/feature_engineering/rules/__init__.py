"""Feature-engineering rules.

Each module owns one lane and exposes `build_lane(context) -> Lane`. Thresholds
come from `config.yaml` via `context.config`; nothing is hardcoded here that a
user might reasonably want to tune.
"""

from . import (
    activity,
    heart_rate,
    hrv,
    light,
    location,
    presence,
    readiness,
    sleep,
    temperature,
)

__all__ = [
    "activity",
    "heart_rate",
    "hrv",
    "light",
    "location",
    "presence",
    "readiness",
    "sleep",
    "temperature",
]
