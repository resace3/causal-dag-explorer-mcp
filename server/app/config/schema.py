"""Pydantic models describing `config.yaml`.

Everything that a feature-engineering rule can tune lives here so that
thresholds never get hardcoded into visualization code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ENTITY_GROUPS = (
    "presence",
    "motion",
    "temperature",
    "illuminance",
    "humidity",
    "sleep",
    "door",
    "device_use",
    "steps",
    "resting_heart_rate",
    "heart_rate",
    "location",
    "place",
)


class McpServerConfig(StrictModel):
    """How to launch a data-source MCP server over stdio.

    Leave `command` empty to reuse the definition already in your MCP client's
    configuration — that way credentials live in one place instead of two.
    """

    enabled: bool = True
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    discover_from_client: bool = True
    discovery_name: str | None = None
    """Server name to look for in the MCP client config; defaults to the key."""

    startup_timeout_seconds: float = 120.0


class McpConfig(StrictModel):
    servers: dict[str, McpServerConfig] = Field(default_factory=dict)

    def server(self, name: str) -> McpServerConfig:
        config = self.servers.get(name) or McpServerConfig()
        if config.discovery_name is None:
            config = config.model_copy(update={"discovery_name": name})
        return config


class HomeAssistantEntities(StrictModel):
    presence: list[str] = Field(default_factory=list)
    motion: list[str] = Field(default_factory=list)
    temperature: list[str] = Field(default_factory=list)
    illuminance: list[str] = Field(default_factory=list)
    humidity: list[str] = Field(default_factory=list)
    sleep: list[str] = Field(default_factory=list)
    """Bed-occupancy style binary sensors, used only as a sleep fallback."""

    door: list[str] = Field(default_factory=list)
    """Door / window contact sensors."""

    device_use: list[str] = Field(default_factory=list)
    """Binary sensors that indicate the user is actively using a device."""

    steps: list[str] = Field(default_factory=list)
    """Cumulative daily step counters (they reset to zero at midnight)."""

    resting_heart_rate: list[str] = Field(default_factory=list)
    """Once-a-day resting heart rate, not a continuous signal."""

    heart_rate: list[str] = Field(default_factory=list)
    """A genuinely continuous heart-rate sensor, if one is exposed."""

    location: list[str] = Field(default_factory=list)
    """Device trackers. Only the zone/state is read — never the coordinates."""

    place: list[str] = Field(default_factory=list)
    """Geocoded-location sensors, used for a human-readable place name."""

    def all_entity_ids(self) -> list[str]:
        seen: list[str] = []
        for name in ENTITY_GROUPS:
            for entity_id in getattr(self, name):
                if entity_id not in seen:
                    seen.append(entity_id)
        return seen

    def domain_for(self, entity_id: str) -> str | None:
        for name in ENTITY_GROUPS:
            if entity_id in getattr(self, name):
                return name
        return None


class WearableSleepEntities(StrictModel):
    """Daily sleep-summary sensors published by a wearable integration.

    Fitbit, Withings and Google Fit integrations all expose the night's sleep as
    a handful of once-a-day sensors rather than a stage-by-stage record. The
    provider reconstructs one interval from these and says so in its provenance.
    """

    start_time: str | None = None
    """Sensor whose state is a local `HH:MM` clock time, e.g. `02:11`."""

    time_in_bed_minutes: str | None = None
    minutes_asleep: str | None = None
    minutes_awake: str | None = None
    efficiency: str | None = None
    awakenings: str | None = None
    minutes_to_fall_asleep: str | None = None

    def entity_ids(self) -> list[str]:
        values = [
            self.start_time,
            self.time_in_bed_minutes,
            self.minutes_asleep,
            self.minutes_awake,
            self.efficiency,
            self.awakenings,
            self.minutes_to_fall_asleep,
        ]
        return [value for value in dict.fromkeys(values) if value]


class HomeAssistantConfig(StrictModel):
    enabled: bool = True
    mcp_server: str = "ha-mcp"
    """Name of the Home Assistant MCP server, shown in the Data Sources panel.

    History is read over the REST API for speed; this records which MCP
    integration the same instance corresponds to.
    """

    entities: HomeAssistantEntities = Field(default_factory=HomeAssistantEntities)


class JsonFileProviderConfig(StrictModel):
    path: str = "./data/wearable.json"


class HomeAssistantWearableConfig(StrictModel):
    """Wearable data that reaches the timeline through Home Assistant."""

    device_name: str = "Wearable (via Home Assistant)"
    sleep: WearableSleepEntities = Field(default_factory=WearableSleepEntities)

    def entity_ids(self) -> list[str]:
        return self.sleep.entity_ids()


class GarminMcpConfig(StrictModel):
    """Wearable data read from the Garmin MCP server."""

    device_name: str = "Garmin"
    mcp_server: str = "garmin"
    """Key under `mcp.servers`, and the name looked up in the MCP client config."""

    include_stress_as_readiness: bool = True
    """Garmin publishes Body Battery / training readiness rather than a
    generic readiness score; when neither exists the lane stays hidden."""


class WearableConfig(StrictModel):
    provider: Literal["mock", "json_file", "home_assistant", "garmin_mcp", "auto"] = "mock"
    device_name: str = "Mock Wearable"
    json_file: JsonFileProviderConfig = Field(default_factory=JsonFileProviderConfig)
    home_assistant: HomeAssistantWearableConfig = Field(
        default_factory=HomeAssistantWearableConfig
    )
    garmin_mcp: GarminMcpConfig = Field(default_factory=GarminMcpConfig)

    routes: list[Literal["garmin_mcp", "home_assistant", "json_file", "mock"]] = Field(
        default_factory=lambda: ["garmin_mcp", "home_assistant"]
    )
    """Used when provider is `auto`: routes are tried in this order, per metric.

    The first route with data for a metric supplies it. Metrics are never
    blended between routes.
    """


class LightBand(StrictModel):
    min_lux: float | None = None
    max_lux: float | None = None


class LightCategoryRule(StrictModel):
    rule_version: str = "1.0.0"
    entity_priority: list[str] = Field(default_factory=list)
    min_duration_minutes: float = 15.0
    thresholds: dict[str, LightBand] = Field(
        default_factory=lambda: {
            "dark": LightBand(max_lux=5),
            "dim": LightBand(min_lux=5, max_lux=50),
            "moderate": LightBand(min_lux=50, max_lux=300),
            "bright": LightBand(min_lux=300),
        }
    )

    @model_validator(mode="after")
    def _check_bands(self) -> "LightCategoryRule":
        if not self.thresholds:
            raise ValueError("light_category.thresholds must define at least one band")
        for name, band in self.thresholds.items():
            if band.min_lux is None and band.max_lux is None:
                raise ValueError(
                    f"light_category.thresholds.{name} needs min_lux and/or max_lux"
                )
            if (
                band.min_lux is not None
                and band.max_lux is not None
                and band.min_lux >= band.max_lux
            ):
                raise ValueError(
                    f"light_category.thresholds.{name}: min_lux must be below max_lux"
                )
        return self

    def classify(self, lux: float) -> str | None:
        """Return the band name whose range contains `lux`."""
        ordered = sorted(
            self.thresholds.items(),
            key=lambda item: (item[1].min_lux if item[1].min_lux is not None else float("-inf")),
        )
        for name, band in ordered:
            low = band.min_lux if band.min_lux is not None else float("-inf")
            high = band.max_lux if band.max_lux is not None else float("inf")
            if low <= lux < high:
                return name
        return None


class WorkoutSessionRule(StrictModel):
    rule_version: str = "1.1.0"
    prefer_wearable_records: bool = True
    allow_heart_rate_only_inference: bool = False
    min_duration_minutes: float = 5.0


class SleepIntervalRule(StrictModel):
    rule_version: str = "1.1.0"
    prefer_wearable_records: bool = True
    environmental_fallback: bool = True
    min_nap_minutes: float = 10.0
    main_sleep_minimum_minutes: float = 180.0


class HomePresenceRule(StrictModel):
    rule_version: str = "1.0.0"
    home_states: list[str] = Field(default_factory=lambda: ["home"])
    away_states: list[str] = Field(default_factory=lambda: ["not_home", "away"])
    min_duration_minutes: float = 2.0

    entity_priority: list[str] = Field(default_factory=list)
    """Which tracker wins when several report presence.

    A person entity and the device tracker behind it describe the same thing;
    drawing both stacks two identical blocks on top of each other. The first
    entity here that produced data is used, and the rest are recorded as
    corroborating sources in the event's provenance.
    """


class PhoneLocationRule(StrictModel):
    """How much of a phone's location to show.

    The timeline never stores or displays coordinates. By default it shows the
    zone name from the device tracker and the locality (town/city) from a
    geocoded sensor — enough to see where the day happened without putting a
    street address on screen. Turning on `include_street_address` is a
    deliberate, recorded choice.
    """

    rule_version: str = "1.0.0"
    min_duration_minutes: float = 10.0
    include_street_address: bool = False
    merge_within_minutes: float = 15.0
    """GPS drift between neighbouring addresses is merged rather than drawn as
    a series of separate places."""


class ElevatedHeartRateRule(StrictModel):
    rule_version: str = "1.0.0"
    baseline_window_days: int = 30
    sd_threshold: float = 1.5
    min_duration_minutes: float = 8.0


class TemperatureDeviationRule(StrictModel):
    rule_version: str = "1.0.0"
    sd_threshold: float = 1.5
    min_duration_minutes: float = 30.0


class SustainedInactivityRule(StrictModel):
    rule_version: str = "1.0.0"
    min_duration_minutes: float = 150.0


class DataGapRule(StrictModel):
    rule_version: str = "1.0.0"
    max_gap_minutes: float = 20.0

    stale_after_minutes: float = 180.0
    """How long a Home Assistant numeric state stays believable.

    Home Assistant records state *changes*, not samples: a sensor that has not
    changed in ten minutes is not missing, it is steady. Only after this long
    without an update is the value treated as unknown rather than held.
    """


class StepActivityRule(StrictModel):
    """Turns a cumulative daily step counter into an interpretable rate."""

    rule_version: str = "1.0.0"
    bucket_minutes: float = 30.0
    active_steps_per_minute: float = 60.0
    """At or above this rate a bucket is labelled a sustained walking period."""

    min_active_minutes: float = 20.0


class DeviceUseRule(StrictModel):
    rule_version: str = "1.0.0"
    min_session_minutes: float = 2.0
    merge_within_minutes: float = 5.0


class FeatureEngineeringConfig(StrictModel):
    light_category: LightCategoryRule = Field(default_factory=LightCategoryRule)
    workout_session: WorkoutSessionRule = Field(default_factory=WorkoutSessionRule)
    sleep_interval: SleepIntervalRule = Field(default_factory=SleepIntervalRule)
    home_presence: HomePresenceRule = Field(default_factory=HomePresenceRule)
    elevated_heart_rate: ElevatedHeartRateRule = Field(default_factory=ElevatedHeartRateRule)
    temperature_deviation: TemperatureDeviationRule = Field(
        default_factory=TemperatureDeviationRule
    )
    sustained_inactivity: SustainedInactivityRule = Field(
        default_factory=SustainedInactivityRule
    )
    step_activity: StepActivityRule = Field(default_factory=StepActivityRule)
    phone_location: PhoneLocationRule = Field(default_factory=PhoneLocationRule)
    device_use: DeviceUseRule = Field(default_factory=DeviceUseRule)
    data_gap: DataGapRule = Field(default_factory=DataGapRule)


class LaneSetting(StrictModel):
    id: str
    visible: bool = True


class AppConfig(StrictModel):
    """Root of `config.yaml`."""

    timezone: str | None = None
    mcp: McpConfig = Field(default_factory=McpConfig)
    home_assistant: HomeAssistantConfig = Field(default_factory=HomeAssistantConfig)
    wearable: WearableConfig = Field(default_factory=WearableConfig)
    feature_engineering: FeatureEngineeringConfig = Field(
        default_factory=FeatureEngineeringConfig
    )
    lanes: list[LaneSetting] = Field(default_factory=list)

    def lane_visibility(self) -> dict[str, bool]:
        return {lane.id: lane.visible for lane in self.lanes}


class ConfigError(ValueError):
    """Raised when `config.yaml` cannot be parsed or validated."""

    def __init__(self, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path
