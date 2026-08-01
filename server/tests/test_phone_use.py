"""Phone use and the TikTok row.

The rule under test is mostly one idea: Android's "last used app" sensor holds
its value after the screen goes off, so every run has to be cut against the
screen-on signal. Most of what follows is that invariant, approached from the
angles that would break it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.connectors.wearables.connector import WearablePayload
from app.feature_engineering.context import RuleContext
from app.feature_engineering.rules import phone_use, presence, tiktok
from app.models.raw import RawRecord
from app.normalization.normalizer import normalize
from app.services.day import day_window

DAY = date(2025, 6, 10)
TIKTOK = "com.zhiliaoapp.musically"
LAUNCHER = "com.android.launcher3"


def _at(new_york, hour: float) -> datetime:
    return datetime(2025, 6, 10, tzinfo=new_york) + timedelta(hours=hour)


def _record(stream: str, entity_id: str, moment: datetime, value: str) -> RawRecord:
    return RawRecord(
        id=RawRecord.make_id("home_assistant", stream, f"{entity_id}|{moment.isoformat()}"),
        source="home_assistant",
        stream=stream,
        entity_id=entity_id,
        device="Test Phone",
        timestamp=moment,
        value=value,
        attributes={"raw_state": value, "unavailable": False},
    )


def screen(new_york, *changes: tuple[float, str]) -> list[RawRecord]:
    """`(hour, "on" | "off")` transitions for the interactive sensor."""
    return [
        _record("device_use", "binary_sensor.phone_interactive", _at(new_york, hour), state)
        for hour, state in changes
    ]


def apps(new_york, *changes: tuple[float, str]) -> list[RawRecord]:
    """`(hour, package)` changes for the last-used-app sensor."""
    return [
        _record("app_usage", "sensor.phone_last_used_app", _at(new_york, hour), package)
        for hour, package in changes
    ]


def _context(records, new_york, sync_service, *, available=True):
    window = day_window(DAY, new_york)
    start = window.start - timedelta(hours=14)
    end = window.end + timedelta(hours=12)
    return RuleContext(
        window=window,
        fetch_start=start,
        fetch_end=end,
        tz=new_york,
        config=sync_service.config.feature_engineering,
        normalized=normalize(records, start, end),
        wearable=WearablePayload(),
        home_assistant_available=available,
    )


def _minutes(events) -> float:
    return round(sum(event.metadata["durationMinutes"] for event in events), 1)


# --------------------------------------------------------------------------
# Screen-on sessions
# --------------------------------------------------------------------------


def test_screen_on_stretches_become_sessions(new_york, sync_service):
    records = screen(new_york, (9, "on"), (9.5, "off"), (14, "on"), (14.25, "off"))
    lane = phone_use.build_lane(_context(records, new_york, sync_service))

    sessions = [event for event in lane.events if event.category == "phone_on"]
    assert lane.available
    assert [event.label for event in sessions] == ["Phone in use · 30m", "Phone in use · 15m"]
    assert _minutes(sessions) == 45.0


def test_a_brief_lock_does_not_split_one_session(new_york, sync_service):
    # The example config merges across gaps of up to five minutes.
    records = screen(
        new_york, (20, "on"), (20.25, "off"), (20.3, "on"), (20.75, "off")
    )
    lane = phone_use.build_lane(_context(records, new_york, sync_service))

    sessions = [event for event in lane.events if event.category == "phone_on"]
    assert len(sessions) == 1
    assert sessions[0].metadata["unlockCount"] == 2
    # The locked three minutes are inside the session, so they are counted.
    assert sessions[0].metadata["durationMinutes"] == 45.0


def test_a_screen_that_only_blinked_is_not_reported_as_no_screen(new_york, sync_service):
    """The sensor is working; sending someone to check it would waste their time."""
    records = screen(new_york, (9, "on"), (9.005, "off"))
    lane = phone_use.build_lane(_context(records, new_york, sync_service))

    assert not lane.available
    assert "no stretch reached" in lane.unavailable_reason
    assert "min_session_minutes" in lane.unavailable_reason


def test_presence_no_longer_draws_screen_use(new_york, sync_service):
    """The signal moved to its own lane; two rows drawing it would double it."""
    records = screen(new_york, (9, "on"), (10, "off"))
    context = _context(records, new_york, sync_service)

    assert [
        event for event in presence.build_lane(context).events if event.category == "device_use"
    ] == []


# --------------------------------------------------------------------------
# Applications, clipped to the screen
# --------------------------------------------------------------------------


def test_an_app_spell_is_cut_at_the_screen_going_off(new_york, sync_service):
    """The whole reason this rule exists.

    TikTok is the last app of the evening and the sensor never changes again,
    so the raw run reaches to the end of the fetch window. What is drawn is the
    eighteen minutes the screen was on: three of them still on the home screen
    the phone was woken to, then fifteen in the app.
    """
    records = [
        *screen(new_york, (22, "on"), (22.3, "off")),
        *apps(new_york, (21, LAUNCHER), (22.05, TIKTOK)),
    ]
    lane = phone_use.build_lane(_context(records, new_york, sync_service))

    spells = [event for event in lane.events if event.category == "phone_app"]
    assert [event.label for event in spells] == ["Home screen", "TikTok"]
    assert _minutes(spells) == 18.0
    assert spells[-1].metadata["durationMinutes"] == 15.0
    assert spells[-1].end_time == _at(new_york, 22.3)


def test_one_run_across_two_screen_windows_becomes_two_spells(new_york, sync_service):
    records = [
        *screen(new_york, (13, "on"), (13.5, "off"), (16, "on"), (16.5, "off")),
        *apps(new_york, (13, TIKTOK)),
    ]
    lane = phone_use.build_lane(_context(records, new_york, sync_service))

    spells = [event for event in lane.events if event.category == "phone_app"]
    assert len(spells) == 2
    assert _minutes(spells) == 60.0


def test_app_spells_are_withheld_without_a_screen_sensor(new_york, sync_service):
    """No screen signal is not a licence to draw the unclipped run."""
    records = apps(new_york, (21, TIKTOK))
    context = _context(records, new_york, sync_service)
    lane = phone_use.build_lane(context)

    assert [event for event in lane.events if event.category == "phone_app"] == []
    assert any("screen" in warning for warning in context.warnings)


def test_an_unavailable_state_is_not_an_app(new_york, sync_service):
    """A hole in the sensor is not an application called "unavailable"."""
    hole = _record(
        "app_usage", "sensor.phone_last_used_app", _at(new_york, 9), "unavailable"
    )
    hole.value = None
    hole.attributes["unavailable"] = True

    records = [
        *screen(new_york, (9, "on"), (10, "off")),
        hole,
        *apps(new_york, (9.5, TIKTOK)),
    ]
    lane = phone_use.build_lane(_context(records, new_york, sync_service))

    spells = [event for event in lane.events if event.category == "phone_app"]
    assert [event.label for event in spells] == ["TikTok"]


@pytest.mark.parametrize(
    ("package", "expected"),
    [
        (TIKTOK, "TikTok"),
        ("com.ss.android.ugc.trill", "TikTok"),
        ("com.android.launcher3", "Home screen"),
        ("com.example.someapp", "Someapp"),
        ("SingleWord", "SingleWord"),
    ],
)
def test_package_names_are_given_readable_labels(package, expected):
    assert phone_use.app_label(package) == expected


def test_the_package_is_kept_even_when_the_label_is_friendly(new_york, sync_service):
    records = [
        *screen(new_york, (9, "on"), (10, "off")),
        *apps(new_york, (9, TIKTOK)),
    ]
    lane = phone_use.build_lane(_context(records, new_york, sync_service))

    spell = next(event for event in lane.events if event.category == "phone_app")
    assert spell.metadata["package"] == TIKTOK
    assert spell.provenance.transformation_rule == "phone_use.app_session"
    assert spell.provenance.raw_record_ids


# --------------------------------------------------------------------------
# The TikTok row
# --------------------------------------------------------------------------


def test_only_the_configured_packages_reach_the_row(new_york, sync_service):
    records = [
        *screen(new_york, (19, "on"), (20, "off")),
        *apps(new_york, (19, "com.whatsapp"), (19.25, TIKTOK), (19.75, "com.android.chrome")),
    ]
    lane = tiktok.build_lane(_context(records, new_york, sync_service))

    assert [event.label for event in lane.events] == ["TikTok"]
    assert lane.events[0].metadata["durationMinutes"] == 30.0


def test_a_glance_at_another_app_is_not_counted_as_tiktok(new_york, sync_service):
    """Two spells either side of a short break stay two spells.

    Filtering to the tracked package before merging would let the runs join
    across the home screen and quietly relabel that minute — on a row whose
    only job is to say how long was spent in one app.
    """
    records = [
        *screen(new_york, (19, "on"), (20, "off")),
        *apps(new_york, (19, TIKTOK), (19.25, LAUNCHER), (19.35, TIKTOK)),
    ]
    lane = tiktok.build_lane(_context(records, new_york, sync_service))

    assert len(lane.events) == 2
    assert _minutes(lane.events) == 54.0  # 15 + 39, never the 60 of the window


def test_the_row_says_so_when_the_app_was_not_opened(new_york, sync_service):
    records = [
        *screen(new_york, (9, "on"), (10, "off")),
        *apps(new_york, (9, "com.whatsapp")),
    ]
    lane = tiktok.build_lane(_context(records, new_york, sync_service))

    assert not lane.available
    assert "was in front while the screen was on" in lane.unavailable_reason


def test_the_row_is_withheld_rather_than_guessed_without_a_screen_sensor(
    new_york, sync_service
):
    lane = tiktok.build_lane(_context(apps(new_york, (21, TIKTOK)), new_york, sync_service))

    assert not lane.available
    assert "screen" in lane.unavailable_reason
    assert "device_use" in lane.unavailable_reason


def test_tiktok_time_is_also_inside_the_phone_row(new_york, sync_service):
    """The two rows are one stretch at two grains, and say so."""
    records = [
        *screen(new_york, (19, "on"), (20, "off")),
        *apps(new_york, (19, TIKTOK)),
    ]
    context = _context(records, new_york, sync_service)

    spell = next(
        event
        for event in phone_use.build_lane(context).events
        if event.category == "phone_app"
    )
    row = tiktok.build_lane(context).events[0]

    assert (spell.start_time, spell.end_time) == (row.start_time, row.end_time)
    assert "also drawn in the Phone Use lane" in row.metadata["note"]


# --------------------------------------------------------------------------
# Wired into the day
# --------------------------------------------------------------------------


@pytest.fixture
async def timeline(sync_service, fixed_now):
    return await sync_service.sync(force_refresh=True, now=fixed_now)


async def test_both_rows_are_built_from_the_mock_day(timeline):
    lanes = {lane.id: lane for lane in timeline.lanes}

    phone = lanes["phone_use"]
    assert phone.available
    assert {event.category for event in phone.events} == {"phone_on", "phone_app"}

    # Every spell falls inside a screen-on stretch, end to end.
    sessions = [
        (event.start_time, event.end_time)
        for event in phone.events
        if event.category == "phone_on"
    ]
    for spell in (event for event in phone.events if event.category == "phone_app"):
        assert any(
            start <= spell.start_time and spell.end_time <= end for start, end in sessions
        ), f"{spell.label} at {spell.start_time} escaped its session"
