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
    "app_usage",
    "tv_use",
    "tv_app",
    "tv_title",
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

    app_usage: list[str] = Field(default_factory=list)
    """Sensors naming the application in front on a phone.

    The Home Assistant companion app's "last used app" sensor reports an Android
    package name. It holds that value after the screen goes off, so it is only
    ever read together with a `device_use` sensor — see `PhoneAppRule`.
    """

    tv_use: list[str] = Field(default_factory=list)
    """Binary sensors that are on while the television is on.

    "On" here is the television being powered on, which is not the same claim
    as something being watched: a paused episode and a menu left open both read
    as on. What was actually playing is the `tv_title` tier below.
    """

    tv_app: list[str] = Field(default_factory=list)
    """Sensors naming the app the television is showing (`Disney+`, `YouTube`).

    Low cardinality, so it reads as a handful of bands over a day rather than a
    caption per programme.
    """

    tv_title: list[str] = Field(default_factory=list)
    """Sensors naming what is playing — the episode or film title.

    Like the phone's last-used-app sensor, a media title holds its last value
    when playback stops, so it is only ever read alongside a `tv_use` sensor
    and clipped to it. See `TvRule`.
    """

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


class ActivityWatchConfig(StrictModel):
    """Computer use, read from a local ActivityWatch server.

    ActivityWatch records which application had focus and whether the keyboard
    and mouse were idle. That is the most revealing stream this application can
    read, so how much of it is kept is a deliberate, recorded choice — the same
    treatment `phone_location.include_street_address` gets.
    """

    enabled: bool = True
    mcp_server: str = "activitywatch"
    """Name of the ActivityWatch MCP server, shown in the MCPs panel.

    Events are read over the local REST API the MCP server itself wraps; this
    records which MCP integration the same server corresponds to.
    """

    detail: Literal["app", "domain", "full"] = "domain"
    """How much of each window and browser tab is kept.

    * `app` — the application name only (`chrome.exe`). Browsing is not read.
    * `domain` — plus the website a browser tab was on, reduced to its domain.
    * `full` — plus window titles and complete URLs.

    Window titles quote document names, message subjects and search queries, so
    `full` is off unless it is asked for. Every event records which level
    produced it.
    """

    hostname: str | None = None
    """Which machine's buckets to read, when one server collects several.

    Left unset, the alphabetically first host that has a window bucket is used
    and the others are named in a warning rather than silently merged — two
    machines' focus histories are not one timeline.
    """


class PhoneUsageConfig(StrictModel):
    """The Phone Usage Collector add-on, running on the Home Assistant host.

    A second, better-resolved view of the same phone the companion app reports.
    The companion app's sensors say which app was in front *now* and whether the
    screen is on; this add-on holds Android's own usage-stats event stream, so
    it has real foreground segments with start and end times, plus the counts
    that only the system knows — unlocks, glances that never became an unlock,
    notification interruptions, app switches.

    Its address and token live in `.env`, not here: the token is a credential,
    and this file is the one that gets shared.
    """

    enabled: bool = True

    device_id: str | None = None
    """Which collector to read when more than one phone reports.

    Left unset, every device's segments are drawn together, which for two phones
    would interleave two people's evenings into one row.
    """


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


RouteName = Literal["garmin_mcp", "google_health_mcp", "home_assistant", "json_file", "mock"]


class GoogleHealthMcpConfig(StrictModel):
    """Sleep read from the Google Health MCP server.

    Sleep only, deliberately. The same API carries steps, heart rate and more,
    all of which already have a source on this machine; a provider that claimed
    them would start winning metrics nobody pointed it at.
    """

    device_name: str = "Google Health"
    mcp_server: str = "google-health"
    """Key under `mcp.servers`, and the name looked up in the MCP client config."""


class WearableConfig(StrictModel):
    provider: Literal[
        "mock", "json_file", "home_assistant", "garmin_mcp", "google_health_mcp", "auto"
    ] = "mock"
    device_name: str = "Mock Wearable"
    json_file: JsonFileProviderConfig = Field(default_factory=JsonFileProviderConfig)
    home_assistant: HomeAssistantWearableConfig = Field(
        default_factory=HomeAssistantWearableConfig
    )
    garmin_mcp: GarminMcpConfig = Field(default_factory=GarminMcpConfig)
    google_health_mcp: GoogleHealthMcpConfig = Field(default_factory=GoogleHealthMcpConfig)

    routes: list[RouteName] = Field(
        default_factory=lambda: ["garmin_mcp", "home_assistant"]
    )
    """Used when provider is `auto`: routes are tried in this order, per metric.

    The first route with data for a metric supplies it. Metrics are never
    blended between routes.
    """

    metric_routes: dict[str, list[RouteName]] = Field(default_factory=dict)
    """Per-metric override of `routes`, for a metric that belongs to one source.

    A metric listed here uses exactly the routes named, in that order, and
    nothing else — so `sleep: [google_health_mcp]` means sleep comes from there
    or is reported missing, rather than quietly falling through to whichever
    other device also happens to guess at it. A week of nights that silently
    alternated between two wearables would look like one record of sleep and be
    two, which is the sort of thing this application exists not to do.

    Routes named here are built even when they are absent from `routes`.
    """

    @model_validator(mode="after")
    def _check_metric_routes(self) -> "WearableConfig":
        for metric, routes in self.metric_routes.items():
            if not routes:
                raise ValueError(
                    f"wearable.metric_routes.{metric} is empty. Remove the key to use "
                    "wearable.routes, or name at least one route."
                )
        return self


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
    """Screen-on stretches — the top tier of the Phone Use lane."""

    rule_version: str = "1.0.0"
    min_session_minutes: float = 2.0
    merge_within_minutes: float = 5.0


class PhoneAppRule(StrictModel):
    """Which application was in front on the phone.

    The companion app's "last used app" sensor holds its value after the screen
    goes off, so a package name can sit there all night. Every spell is
    intersected with the screen-on signal before it is drawn — without that, a
    phone put down at eleven reads as eight hours in whatever was open last.
    That makes the screen sensor a hard requirement, not a refinement: with no
    `device_use` entity the lane says so rather than drawing the unclipped runs.
    """

    rule_version: str = "1.0.0"

    min_app_minutes: float = 1.0
    """Shortest spell in one application worth naming. Below this the time is
    still inside the screen-on stretch above it, so nothing is lost."""

    merge_within_minutes: float = 2.0
    """Runs of the same application separated by less than this are one spell.
    Dropping to the home screen and straight back is not two sessions."""


class TrackedAppRule(StrictModel):
    """The TikTok row: one named application, followed on its own.

    Package names rather than a display name, because Android reports the
    package and TikTok ships under two of them depending on where the phone was
    set up. Everything this row draws also appears in the Phone Use lane above
    it — this is the same time seen twice, at two grains, not a second measurement.
    """

    rule_version: str = "1.0.0"

    packages: list[str] = Field(
        default_factory=lambda: ["com.zhiliaoapp.musically", "com.ss.android.ugc.trill"]
    )

    min_minutes: float = 0.5
    """Shorter than the application tier's minimum: a two-minute look at this
    one app is the whole point of the row, where a two-minute look at any app
    is noise."""

    merge_within_minutes: float = 2.0


class TvRule(StrictModel):
    """The television row: on-stretches, and what was playing inside them.

    The same two-tier shape as the phone, and the same trap underneath it. A
    media-title sensor keeps reporting the last thing it saw after playback
    stops, so an unclipped run reaches from the end of the evening to whenever
    the television is next switched on. Every spell is intersected with the
    on-signal before it is drawn, which makes `tv_use` a hard requirement for
    the title tier rather than a refinement.

    The two tiers make different claims and the row keeps them apart. The band
    says the television was *on*, which a paused episode and an idle home
    screen both satisfy. Only the spells inside it say something was playing.
    """

    rule_version: str = "1.0.0"

    min_session_minutes: float = 5.0
    """Shortest on-stretch worth drawing. A television woken by the remote and
    switched straight off is not an evening in front of it."""

    merge_within_minutes: float = 10.0
    """Off-stretches shorter than this do not end a session. A set turned off
    while someone answers the door is one sitting, not two."""

    min_programme_minutes: float = 4.0
    """Shortest spell on one title worth naming. Below this the time is still
    inside the on-stretch above it, so nothing goes missing — it is the caption
    that is withheld, not the minutes."""

    programme_merge_within_minutes: float = 3.0
    """Runs of the same title separated by less than this are one spell, which
    is what an ad break or a few seconds of buffering looks like."""


class PhoneUseCustomRule(StrictModel):
    """The Phone Use custom row, from the usage-stats add-on.

    Android emits a foreground event every time the front app changes, so a
    normal evening is hundreds of segments. These decide what counts as one
    pickup and what counts as a spell worth naming.

    No clipping threshold appears here, and that is the difference from the
    companion-app row: these segments have real end times, so there is nothing
    to cut them against. The other row needs a screen sensor because its source
    reports the last app indefinitely; this one does not.
    """

    rule_version: str = "1.0.0"

    min_session_minutes: float = 0.5
    """Shortest pickup worth drawing. Lower than the computer's, because
    picking a phone up for forty seconds is a real and frequent event."""

    merge_within_minutes: float = 3.0
    """Segments separated by less than this are one pickup. Below it the phone
    was still in hand between two apps."""

    min_app_minutes: float = 1.0
    """Shortest spell in one application worth naming. The time is still inside
    the pickup above it, so nothing is lost — only the caption."""

    app_merge_within_minutes: float = 1.0
    """Runs of the same application separated by less than this are one spell:
    a glance at the launcher and straight back is not two visits."""


class ComputerUseRule(StrictModel):
    """Turns per-second focus events into readable sessions.

    ActivityWatch writes an event every time the focused window changes, so a
    working hour is hundreds of events. Drawing them raw would be a smear; these
    thresholds decide what counts as one stretch at the machine and what counts
    as one spell in an application.
    """

    rule_version: str = "1.0.0"

    min_session_minutes: float = 5.0
    """Shortest stretch at the computer that counts as a session.

    Shorter stretches are still drawn and still carry their real duration —
    they are marked `brief` and left out of the session count. Discarding them
    would silently remove time the day has focus events for, which fragmented
    idle data produces constantly."""

    merge_within_minutes: float = 5.0
    """Idle stretches shorter than this do not end a session. Reading a page
    without touching the mouse registers as away; treating that as leaving the
    desk would cut every session into fragments."""

    min_app_minutes: float = 3.0
    """Shortest run in one application worth naming. Everything below is still
    counted in the session total, and the count of what was dropped is
    reported, so short spells are never silently missing."""

    min_site_minutes: float = 5.0
    """The same, for a browsing domain."""


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
    phone_app: PhoneAppRule = Field(default_factory=PhoneAppRule)
    tiktok: TrackedAppRule = Field(default_factory=TrackedAppRule)
    tv: TvRule = Field(default_factory=TvRule)
    phone_use_custom: PhoneUseCustomRule = Field(default_factory=PhoneUseCustomRule)
    computer_use: ComputerUseRule = Field(default_factory=ComputerUseRule)
    data_gap: DataGapRule = Field(default_factory=DataGapRule)


class LaneSetting(StrictModel):
    id: str
    visible: bool = True


class AppConfig(StrictModel):
    """Root of `config.yaml`."""

    timezone: str | None = None
    mcp: McpConfig = Field(default_factory=McpConfig)
    home_assistant: HomeAssistantConfig = Field(default_factory=HomeAssistantConfig)
    activitywatch: ActivityWatchConfig = Field(default_factory=ActivityWatchConfig)
    phone_usage: PhoneUsageConfig = Field(default_factory=PhoneUsageConfig)
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
