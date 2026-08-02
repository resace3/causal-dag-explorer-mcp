"""Synthetic Home Assistant state history.

This produces Home Assistant's native `/api/history/period` payload shape so the
mock exercises exactly the same parsing path as a real instance — including
`unavailable` states, which become honest missing-data gaps in the timeline.

Timings are taken from the wearable mock's `DayPlan`, so bed occupancy, lamps
and presence agree with the sleep and workout records.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ...config.schema import HomeAssistantEntities
from ..wearables.mock import DayPlan

# The illuminance sensor drops off the mesh for a while each evening.
SENSOR_OUTAGE_START = time(20, 10)
SENSOR_OUTAGE_END = time(21, 0)


def _state(
    entity_id: str,
    state: str,
    moment: datetime,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stamp = moment.isoformat()
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes or {},
        "last_changed": stamp,
        "last_updated": stamp,
    }


def _friendly_name(entity_id: str) -> str:
    return entity_id.split(".", 1)[-1].replace("_", " ").title()


def _plans(start: datetime, end: datetime, tz: ZoneInfo, seed: int) -> dict[date, DayPlan]:
    plans: dict[date, DayPlan] = {}
    cursor = (start.astimezone(tz) - timedelta(days=1)).date()
    last = (end.astimezone(tz) + timedelta(days=1)).date()
    while cursor <= last:
        plans[cursor] = DayPlan(cursor, tz, seed)
        cursor += timedelta(days=1)
    return plans


def _illuminance_at(moment: datetime, plan: DayPlan, rng: random.Random) -> float:
    """Daylight through a window plus lamps in the evening."""
    minute = moment.hour * 60 + moment.minute
    sunrise, sunset = 6 * 60 + 15, 20 * 60 + 5
    if sunrise <= minute <= sunset:
        span = sunset - sunrise
        arc = math.sin((minute - sunrise) / span * math.pi)
        daylight = 1180 * arc**1.4
    else:
        daylight = 0.0

    if 18 * 60 <= minute < 22 * 60 + 40:
        lamps = 42.0
    elif 22 * 60 + 40 <= minute or minute < 6 * 60:
        lamps = 0.6
    else:
        lamps = 6.0

    if plan.asleep_at(moment):
        lamps = min(lamps, 0.4)

    return max(0.0, daylight + lamps + rng.uniform(-2.5, 2.5))


def _room_temperature_at(moment: datetime, offset: float, rng: random.Random) -> float:
    minute = moment.hour * 60 + moment.minute
    curve = 3.4 * math.sin((minute - 420) / 1440 * 2 * math.pi)
    return 68.6 + offset + curve + rng.uniform(-0.25, 0.25)


def _humidity_at(moment: datetime, rng: random.Random) -> float:
    minute = moment.hour * 60 + moment.minute
    curve = 5.0 * math.cos((minute - 300) / 1440 * 2 * math.pi)
    return 41.0 + curve + rng.uniform(-1.0, 1.0)


def _away_windows(plan: DayPlan) -> list[tuple[datetime, datetime]]:
    """Errands in the morning, and the evening run happens outdoors."""
    day = plan.day
    tz = plan.tz
    errand_start = datetime.combine(day, time(9, 12), tzinfo=tz)
    errand_end = datetime.combine(day, time(11, 48), tzinfo=tz)
    windows = [(errand_start, errand_end)]
    for activity_start, activity_end, kind, _label in plan.activities:
        if kind == "running":
            windows.append(
                (activity_start - timedelta(minutes=2), activity_end + timedelta(minutes=5))
            )
    return sorted(windows)


def _numeric_series(
    entity_id: str,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    step_minutes: int,
    unit: str,
    device_class: str,
    value_fn,
    plans: dict[date, DayPlan],
    rng: random.Random,
    *,
    outage: tuple[time, time] | None = None,
    precision: int = 1,
) -> list[dict[str, Any]]:
    attributes = {
        "unit_of_measurement": unit,
        "device_class": device_class,
        "friendly_name": _friendly_name(entity_id),
        "state_class": "measurement",
    }
    rows: list[dict[str, Any]] = []
    cursor = start.astimezone(tz).replace(second=0, microsecond=0)
    cursor -= timedelta(minutes=cursor.minute % step_minutes)
    outage_flag = False
    while cursor < end:
        if cursor >= start:
            plan = plans[cursor.date()]
            in_outage = False
            if outage is not None:
                local_time = cursor.timetz().replace(tzinfo=None)
                in_outage = outage[0] <= local_time < outage[1]
            if in_outage:
                if not outage_flag:
                    rows.append(_state(entity_id, "unavailable", cursor, attributes))
                    outage_flag = True
            else:
                outage_flag = False
                value = value_fn(cursor, plan, rng)
                rows.append(_state(entity_id, f"{value:.{precision}f}", cursor, attributes))
        cursor += timedelta(minutes=step_minutes)
    return rows


def _binary_series(
    entity_id: str,
    start: datetime,
    end: datetime,
    device_class: str,
    windows: list[tuple[datetime, datetime]],
    on_state: str = "on",
    off_state: str = "off",
) -> list[dict[str, Any]]:
    """Emit transitions only, the way Home Assistant records binary sensors."""
    attributes = {"device_class": device_class, "friendly_name": _friendly_name(entity_id)}
    rows = [_state(entity_id, off_state, start, attributes)]
    for window_start, window_end in sorted(windows):
        if window_end <= start or window_start >= end:
            continue
        on_at = max(window_start, start)
        off_at = min(window_end, end)
        if on_at >= off_at:
            continue
        rows.append(_state(entity_id, on_state, on_at, attributes))
        if off_at < end:
            rows.append(_state(entity_id, off_state, off_at, attributes))
    rows.sort(key=lambda row: row["last_changed"])
    return rows


def _motion_windows(
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    plans: dict[date, DayPlan],
    rng: random.Random,
    room: str,
) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    cursor = start.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    while cursor < end:
        plan = plans[cursor.date()]
        bedroom = "bedroom" in room
        for _ in range(rng.randint(0, 3)):
            offset = rng.randint(0, 59)
            moment = cursor + timedelta(minutes=offset)
            if moment < start or moment >= end:
                continue
            asleep = plan.asleep_at(moment)
            away = any(a <= moment < b for a, b in _away_windows(plan))
            if away:
                continue
            if asleep and not bedroom:
                continue
            if asleep and bedroom and rng.random() > 0.12:
                continue
            windows.append((moment, moment + timedelta(minutes=rng.randint(1, 4))))
        cursor += timedelta(hours=1)
    return windows


def _door_windows(
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    plans: dict[date, DayPlan],
    rng: random.Random,
) -> list[tuple[datetime, datetime]]:
    """A handful of brief openings while awake and at home."""
    windows: list[tuple[datetime, datetime]] = []
    cursor = start.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    while cursor < end:
        plan = plans[cursor.date()]
        if not plan.asleep_at(cursor) and rng.random() < 0.14:
            moment = cursor + timedelta(minutes=rng.randint(0, 59))
            if start <= moment < end and not any(
                a <= moment < b for a, b in _away_windows(plan)
            ):
                windows.append((moment, moment + timedelta(seconds=rng.randint(20, 90))))
        cursor += timedelta(hours=1)
    return windows


def _device_use_windows(
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    plans: dict[date, DayPlan],
    rng: random.Random,
) -> list[tuple[datetime, datetime]]:
    """Screen-on sessions clustered in the waking hours."""
    windows: list[tuple[datetime, datetime]] = []
    cursor = start.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    while cursor < end:
        plan = plans[cursor.date()]
        if not plan.asleep_at(cursor):
            for _ in range(rng.randint(0, 2)):
                moment = cursor + timedelta(minutes=rng.randint(0, 55))
                if start <= moment < end:
                    windows.append(
                        (moment, moment + timedelta(minutes=rng.randint(3, 22)))
                    )
        cursor += timedelta(hours=1)
    return sorted(windows)


#: Packages the mock phone moves between. Real Android package names, so the
#: display-name lookup in rules/phone_use.py is exercised rather than bypassed.
MOCK_APPS = (
    "com.android.launcher3",
    "com.whatsapp",
    "com.android.chrome",
    "com.google.android.apps.messaging",
    "com.google.android.youtube",
)

MOCK_TRACKED_APP = "com.zhiliaoapp.musically"


def _app_usage_series(
    entity_id: str,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    windows: list[tuple[datetime, datetime]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Which app was in front, changing only while the screen was on.

    The value deliberately persists after a window closes, all the way to the
    next one. That is exactly what the real sensor does, and it is why
    rules/phone_use.py clips every run against the screen — a mock that tidily
    reset to nothing overnight would never exercise the case that matters.
    """
    attributes = {"friendly_name": _friendly_name(entity_id)}
    rows = [_state(entity_id, MOCK_APPS[0], start, attributes)]

    for window_start, window_end in windows:
        first = max(window_start, start)
        last = min(window_end, end)
        if first >= last:
            continue
        hour = first.astimezone(tz).hour
        slices = rng.randint(1, 3)
        step = (last - first) / slices
        # The tracked app clusters in the evening, which is the shape the row
        # exists to show against sleep onset.
        tracked = (
            rng.randrange(slices)
            if rng.random() < (0.5 if 18 <= hour <= 23 else 0.12)
            else None
        )
        for index in range(slices):
            package = (
                MOCK_TRACKED_APP
                if index == tracked
                else MOCK_APPS[rng.randrange(len(MOCK_APPS))]
            )
            rows.append(_state(entity_id, package, first + step * index, attributes))

    rows.sort(key=lambda row: row["last_changed"])
    return rows


def _tv_windows(
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    plans: dict[date, DayPlan],
    rng: random.Random,
) -> list[tuple[datetime, datetime]]:
    """Evening sittings, occasionally an afternoon one."""
    windows: list[tuple[datetime, datetime]] = []
    for plan in plans.values():
        evening = datetime.combine(
            plan.day, time(rng.choice((19, 20)), rng.randrange(0, 50)), tzinfo=tz
        )
        windows.append((evening, evening + timedelta(minutes=rng.randint(55, 165))))
        if rng.random() < 0.35:
            afternoon = datetime.combine(
                plan.day, time(14, rng.randrange(0, 50)), tzinfo=tz
            )
            windows.append((afternoon, afternoon + timedelta(minutes=rng.randint(25, 70))))
    return sorted(
        (a, b) for a, b in windows if b > start and a < end and not plans[a.date()].asleep_at(a)
    )


#: What the mock set is showing. Titles, and the app each one streams from —
#: two sensors, because a title is high-cardinality and an app is not.
MOCK_PROGRAMMES = (
    ("King of the Hill", "Disney+"),
    ("The Great British Bake Off", "Netflix"),
    ("Planet Earth III", "BBC iPlayer"),
    ("Taskmaster", "YouTube"),
    ("Columbo", "Prime Video"),
)


def _tv_media_series(
    title_entity: str | None,
    app_entity: str | None,
    start: datetime,
    end: datetime,
    windows: list[tuple[datetime, datetime]],
    rng: random.Random,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Title and app states, changing only while the set was on.

    Both values deliberately persist after a window closes, all the way to the
    next sitting — which is exactly what a media-title sensor does, and why
    rules/tv.py clips every run against the on-signal. A mock that tidily blanked
    itself when the television went off would never exercise the case that
    matters.
    """
    first = MOCK_PROGRAMMES[0]
    titles = [_state(title_entity, first[0], start, {"friendly_name": _friendly_name(title_entity)})] if title_entity else []
    apps = [_state(app_entity, first[1], start, {"friendly_name": _friendly_name(app_entity)})] if app_entity else []

    for window_start, window_end in windows:
        begin = max(window_start, start)
        finish = min(window_end, end)
        if begin >= finish:
            continue
        # An episode or two per sitting, plus the odd very short one that falls
        # under the naming threshold and is meant to.
        count = rng.randint(1, 3)
        step = (finish - begin) / count
        for index in range(count):
            title, app = MOCK_PROGRAMMES[rng.randrange(len(MOCK_PROGRAMMES))]
            moment = begin + step * index
            if title_entity:
                titles.append(
                    _state(title_entity, title, moment, {"friendly_name": _friendly_name(title_entity)})
                )
            if app_entity:
                apps.append(
                    _state(app_entity, app, moment, {"friendly_name": _friendly_name(app_entity)})
                )

    titles.sort(key=lambda row: row["last_changed"])
    apps.sort(key=lambda row: row["last_changed"])
    return titles, apps


def _step_counter(
    entity_id: str,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    plans: dict[date, DayPlan],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """A cumulative daily counter that resets at local midnight."""
    attributes = {
        "unit_of_measurement": "steps",
        "state_class": "total_increasing",
        "friendly_name": _friendly_name(entity_id),
    }
    rows: list[dict[str, Any]] = []
    cursor = start.astimezone(tz).replace(second=0, microsecond=0)
    cursor -= timedelta(minutes=cursor.minute % 30)
    total = rng.randint(400, 900)  # carried over from before the window
    current_day = cursor.date()

    while cursor < end:
        if cursor.date() != current_day:
            current_day = cursor.date()
            total = 0
        plan = plans[cursor.date()]

        if plan.asleep_at(cursor):
            total += rng.randint(0, 6)
        elif plan.activity_at(cursor) is not None:
            kind = plan.activity_at(cursor)[2]
            total += rng.randint(1400, 2600) if kind != "strength_training" else rng.randint(200, 500)
        else:
            total += rng.randint(20, 260)

        if cursor >= start:
            rows.append(_state(entity_id, str(total), cursor, attributes))
        cursor += timedelta(minutes=30)
    return rows


def _daily_resting_heart_rate(
    entity_id: str,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    plans: dict[date, DayPlan],
) -> list[dict[str, Any]]:
    """One value published each morning, not a continuous signal."""
    attributes = {"unit_of_measurement": "bpm", "friendly_name": _friendly_name(entity_id)}
    rows: list[dict[str, Any]] = []
    for plan in plans.values():
        moment = datetime.combine(plan.day, time(9, 20), tzinfo=tz)
        if start <= moment < end:
            rows.append(_state(entity_id, str(round(plan.resting_hr)), moment, attributes))
    rows.sort(key=lambda row: row["last_changed"])
    return rows


def _zone_series(
    entity_id: str,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    plans: dict[date, DayPlan],
) -> list[dict[str, Any]]:
    """Device-tracker zone states. No coordinates are emitted, even in mock."""
    attributes = {
        "source_type": "gps",
        "friendly_name": _friendly_name(entity_id),
    }
    rows: list[dict[str, Any]] = [_state(entity_id, "home", start, attributes)]
    for plan in plans.values():
        for away_start, away_end in _away_windows(plan):
            if away_end <= start or away_start >= end:
                continue
            rows.append(
                _state(entity_id, "not_home", max(away_start, start), attributes)
            )
            if away_end < end:
                rows.append(_state(entity_id, "home", away_end, attributes))
    rows.sort(key=lambda row: row["last_changed"])
    return rows


def _place_series(
    entity_id: str,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    plans: dict[date, DayPlan],
) -> list[dict[str, Any]]:
    """Reverse-geocoded place names, with the town in the attributes."""
    def state(place: str, locality: str, moment: datetime) -> dict[str, Any]:
        return _state(
            entity_id,
            place,
            moment,
            {
                "friendly_name": _friendly_name(entity_id),
                "locality": locality,
                "administrative_area": "MA",
                "country": "United States",
            },
        )

    rows = [state("12 Example St, Springfield, MA 01101, USA", "Springfield", start)]
    for plan in plans.values():
        for index, (away_start, away_end) in enumerate(_away_windows(plan)):
            if away_end <= start or away_start >= end:
                continue
            elsewhere = "Riverton" if index % 2 == 0 else "Northfield"
            rows.append(
                state(
                    f"{40 + index * 7} Market St, {elsewhere}, MA 01102, USA",
                    elsewhere,
                    max(away_start, start),
                )
            )
            if away_end < end:
                rows.append(
                    state("12 Example St, Springfield, MA 01101, USA", "Springfield", away_end)
                )
    rows.sort(key=lambda row: row["last_changed"])
    return rows


def generate_history(
    entities: HomeAssistantEntities,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    seed: int,
) -> list[list[dict[str, Any]]]:
    """Return one list of state dicts per configured entity."""
    plans = _plans(start, end, tz, seed)
    groups: list[list[dict[str, Any]]] = []

    # One screen-on history for the whole phone, generated before the per-entity
    # loop: the interactive sensor and the last-used-app sensor describe the same
    # device, and drawing them from independent streams would produce a mock day
    # where apps were open while the screen was off.
    screen_windows = _device_use_windows(start, end, tz, plans, random.Random(seed * 7919 + 13))

    # The same reasoning for the television, one step further: its three sensors
    # describe one set, so the on-windows *and* the programme choices are made
    # once. Generated per-entity they would disagree, and the mock would show
    # Columbo streaming on Netflix while the set was off.
    tv_rng = random.Random(seed * 6151 + 29)
    tv_windows = _tv_windows(start, end, tz, plans, tv_rng)
    tv_titles, tv_apps = _tv_media_series(
        next(iter(entities.tv_title), None),
        next(iter(entities.tv_app), None),
        start,
        end,
        tv_windows,
        tv_rng,
    )

    for index, entity_id in enumerate(entities.all_entity_ids()):
        rng = random.Random(seed * 977 + index * 31 + hash(entity_id) % 10_000)
        domain = entities.domain_for(entity_id)
        rows: list[dict[str, Any]] = []

        if domain == "illuminance":
            rows = _numeric_series(
                entity_id, start, end, tz, 10, "lx", "illuminance",
                lambda moment, plan, r: _illuminance_at(moment, plan, r),
                plans, rng, outage=(SENSOR_OUTAGE_START, SENSOR_OUTAGE_END),
            )
        elif domain == "temperature":
            offset = -1.6 if "bedroom" in entity_id else 0.9
            rows = _numeric_series(
                entity_id, start, end, tz, 15, "°F", "temperature",
                lambda moment, plan, r, offset=offset: _room_temperature_at(moment, offset, r),
                plans, rng,
            )
        elif domain == "humidity":
            rows = _numeric_series(
                entity_id, start, end, tz, 30, "%", "humidity",
                lambda moment, plan, r: _humidity_at(moment, r),
                plans, rng, precision=0,
            )
        elif domain == "presence":
            away = [w for plan in plans.values() for w in _away_windows(plan)]
            rows = _binary_series(
                entity_id, start, end, "presence", away,
                on_state="not_home", off_state="home",
            )
        elif domain == "motion":
            rows = _binary_series(
                entity_id, start, end, "motion",
                _motion_windows(start, end, tz, plans, rng, entity_id),
            )
        elif domain == "sleep":
            occupancy = []
            for plan in plans.values():
                occupancy.append(
                    (plan.sleep_start - timedelta(minutes=12), plan.sleep_end + timedelta(minutes=4))
                )
            rows = _binary_series(entity_id, start, end, "occupancy", occupancy)
        elif domain == "door":
            rows = _binary_series(
                entity_id, start, end, "door", _door_windows(start, end, tz, plans, rng)
            )
        elif domain == "device_use":
            rows = _binary_series(entity_id, start, end, "connectivity", screen_windows)
        elif domain == "app_usage":
            rows = _app_usage_series(entity_id, start, end, tz, screen_windows, rng)
        elif domain == "tv_use":
            rows = _binary_series(entity_id, start, end, "running", tv_windows)
        elif domain == "tv_title":
            rows = [row for row in tv_titles if row["entity_id"] == entity_id]
        elif domain == "tv_app":
            rows = [row for row in tv_apps if row["entity_id"] == entity_id]
        elif domain == "steps":
            rows = _step_counter(entity_id, start, end, tz, plans, rng)
        elif domain == "resting_heart_rate":
            rows = _daily_resting_heart_rate(entity_id, start, end, tz, plans)
        elif domain == "location":
            rows = _zone_series(entity_id, start, end, tz, plans)
        elif domain == "place":
            rows = _place_series(entity_id, start, end, tz, plans)

        if rows:
            groups.append(rows)

    return groups
