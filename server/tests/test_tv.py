"""The television row.

The rule is two ideas. One: a media-title sensor holds its last value after
playback stops, so every run has to be cut against the on-signal — the same
invariant the phone row rests on, approached here from the angles that would
break it. Two: "the set was on" and "something was playing" are different
claims, and the row must not let the first pass for the second.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.connectors.wearables.connector import WearablePayload
from app.feature_engineering.context import RuleContext
from app.feature_engineering.rules import tv
from app.models.raw import RawRecord
from app.normalization.normalizer import normalize
from app.services.day import day_window

DAY = date(2025, 6, 10)


def _at(new_york, hour: float) -> datetime:
    return datetime(2025, 6, 10, tzinfo=new_york) + timedelta(hours=hour)


def _record(stream: str, entity_id: str, moment: datetime, value: str) -> RawRecord:
    return RawRecord(
        id=RawRecord.make_id("home_assistant", stream, f"{entity_id}|{moment.isoformat()}"),
        source="home_assistant",
        stream=stream,
        entity_id=entity_id,
        device="Living Room TV",
        timestamp=moment,
        value=value,
        attributes={"raw_state": value, "unavailable": False},
    )


def power(new_york, *changes: tuple[float, str]) -> list[RawRecord]:
    """`(hour, "on" | "off")` transitions for the in-use binary sensor."""
    return [
        _record("tv_use", "binary_sensor.tv_in_use", _at(new_york, hour), state)
        for hour, state in changes
    ]


def titles(new_york, *changes: tuple[float, str]) -> list[RawRecord]:
    return [
        _record("tv_title", "sensor.tv_now_playing", _at(new_york, hour), title)
        for hour, title in changes
    ]


def apps(new_york, *changes: tuple[float, str]) -> list[RawRecord]:
    return [
        _record("tv_app", "sensor.tv_current_app", _at(new_york, hour), app)
        for hour, app in changes
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


def _of(lane, category):
    return [event for event in lane.events if event.category == category]


# --------------------------------------------------------------------------
# On-stretches
# --------------------------------------------------------------------------


def test_on_stretches_become_sittings(new_york, sync_service):
    records = power(new_york, (19, "on"), (21, "off"), (22, "on"), (22.5, "off"))
    lane = tv.build_lane(_context(records, new_york, sync_service))

    sessions = _of(lane, "tv_on")
    assert lane.available
    assert [event.label for event in sessions] == ["TV on · 2h", "TV on · 30m"]
    assert _minutes(sessions) == 150.0


def test_a_brief_switch_off_does_not_split_one_sitting(new_york, sync_service):
    """The example config bridges gaps of up to ten minutes."""
    records = power(new_york, (19, "on"), (20, "off"), (20.1, "on"), (21, "off"))
    lane = tv.build_lane(_context(records, new_york, sync_service))

    sessions = _of(lane, "tv_on")
    assert len(sessions) == 1
    assert sessions[0].metadata["switchOnCount"] == 2
    # The six minutes off are inside the sitting, so they are counted.
    assert sessions[0].metadata["durationMinutes"] == 120.0


def test_a_set_that_only_blinked_is_not_reported_as_never_on(new_york, sync_service):
    """The sensor is working; sending someone to check it would waste their time."""
    records = power(new_york, (19, "on"), (19.01, "off"))
    lane = tv.build_lane(_context(records, new_york, sync_service))

    assert not lane.available
    assert "no stretch reached" in lane.unavailable_reason
    assert "min_session_minutes" in lane.unavailable_reason


def test_the_band_does_not_claim_anything_was_watched(new_york, sync_service):
    """A paused episode is powered on, and the row has to admit that."""
    lane = tv.build_lane(
        _context(power(new_york, (19, "on"), (21, "off")), new_york, sync_service)
    )
    session = _of(lane, "tv_on")[0]

    assert "Powered on is not the same as watched" in session.metadata["note"]
    for banned in ("watched", "watching", "viewing"):
        assert banned not in session.label.lower()


# --------------------------------------------------------------------------
# Programmes, clipped to the on-signal
# --------------------------------------------------------------------------


def test_a_programme_is_cut_at_the_set_going_off(new_york, sync_service):
    """The whole reason this rule exists.

    The last episode of the evening is still what the title sensor reports at
    three in the morning. What is drawn is the forty-two minutes the set was on.
    """
    records = [
        *power(new_york, (20, "on"), (21.5, "off")),
        *titles(new_york, (19, "Columbo"), (20.8, "King of the Hill")),
    ]
    lane = tv.build_lane(_context(records, new_york, sync_service))

    spells = _of(lane, "tv_playing")
    assert [event.label for event in spells] == ["Columbo", "King of the Hill"]
    assert _minutes(spells) == 90.0
    assert spells[-1].metadata["durationMinutes"] == 42.0
    assert spells[-1].end_time == _at(new_york, 21.5)


def test_one_title_across_two_sittings_becomes_two_spells(new_york, sync_service):
    records = [
        *power(new_york, (14, "on"), (14.5, "off"), (20, "on"), (20.5, "off")),
        *titles(new_york, (14, "Planet Earth III")),
    ]
    lane = tv.build_lane(_context(records, new_york, sync_service))

    spells = _of(lane, "tv_playing")
    assert len(spells) == 2
    assert _minutes(spells) == 60.0


def test_programmes_are_withheld_without_an_in_use_sensor(new_york, sync_service):
    """No on-signal is not a licence to draw the unclipped run."""
    context = _context(titles(new_york, (20, "Taskmaster")), new_york, sync_service)
    lane = tv.build_lane(context)

    assert not lane.available
    assert _of(lane, "tv_playing") == []
    assert any("was on" in warning for warning in context.warnings)
    assert "tv_use" in lane.unavailable_reason


def test_an_on_band_with_no_titles_says_the_recorder_is_why(new_york, sync_service):
    """An empty programme tier must not read as "nothing was playing"."""
    context = _context(power(new_york, (20, "on"), (22, "off")), new_york, sync_service)
    lane = tv.build_lane(context)

    assert lane.available
    assert _of(lane, "tv_playing") == []
    warning = next(w for w in context.warnings if "no sensor recorded what was playing" in w)
    assert "allowlist" in warning


def test_an_unavailable_state_is_not_a_programme(new_york, sync_service):
    """A hole in the sensor is not a show called "unavailable"."""
    hole = _record("tv_title", "sensor.tv_now_playing", _at(new_york, 19), "unavailable")
    hole.value = None
    hole.attributes["unavailable"] = True

    records = [
        *power(new_york, (19, "on"), (21, "off")),
        hole,
        *titles(new_york, (20, "Columbo")),
    ]
    lane = tv.build_lane(_context(records, new_york, sync_service))

    assert [event.label for event in _of(lane, "tv_playing")] == ["Columbo"]


def test_a_short_programme_is_not_named_but_its_time_is_still_in_the_band(
    new_york, sync_service
):
    """Below the threshold the caption is withheld, never the minutes."""
    records = [
        *power(new_york, (20, "on"), (21, "off")),
        *titles(new_york, (20, "Trailers"), (20.05, "Columbo")),
    ]
    lane = tv.build_lane(_context(records, new_york, sync_service))

    assert [event.label for event in _of(lane, "tv_playing")] == ["Columbo"]
    assert _of(lane, "tv_on")[0].metadata["durationMinutes"] == 60.0


# --------------------------------------------------------------------------
# Titles, apps, and which of the two a row is naming
# --------------------------------------------------------------------------


def test_the_app_annotates_the_title_rather_than_replacing_it(new_york, sync_service):
    records = [
        *power(new_york, (20, "on"), (21, "off")),
        *titles(new_york, (20, "King of the Hill")),
        *apps(new_york, (20, "Disney+")),
    ]
    lane = tv.build_lane(_context(records, new_york, sync_service))

    spell = _of(lane, "tv_playing")[0]
    assert spell.label == "King of the Hill"
    assert spell.metadata["app"] == "Disney+"
    assert spell.metadata["namedBy"] == "title"


def test_with_no_title_sensor_the_app_names_the_row_and_says_so(new_york, sync_service):
    """"Disney+" must never be allowed to pass for the name of a programme."""
    records = [
        *power(new_york, (20, "on"), (21, "off")),
        *apps(new_york, (20, "Netflix")),
    ]
    lane = tv.build_lane(_context(records, new_york, sync_service))

    spell = _of(lane, "tv_playing")[0]
    assert spell.label == "Netflix"
    assert spell.metadata["namedBy"] == "app"
    assert spell.metadata["title"] is None
    assert "names the app rather than the programme" in spell.metadata["note"]


def test_a_title_sensor_that_was_unavailable_all_day_falls_back_to_the_app(
    new_york, sync_service
):
    """Having rows is not the same as having names."""
    hole = _record("tv_title", "sensor.tv_now_playing", _at(new_york, 19), "unavailable")
    hole.value = None
    hole.attributes["unavailable"] = True

    records = [
        *power(new_york, (20, "on"), (21, "off")),
        hole,
        *apps(new_york, (20, "Netflix")),
    ]
    lane = tv.build_lane(_context(records, new_york, sync_service))

    spell = _of(lane, "tv_playing")[0]
    assert spell.label == "Netflix"
    assert spell.metadata["namedBy"] == "app"


def test_provenance_carries_the_thresholds_and_the_raw_records(new_york, sync_service):
    records = [
        *power(new_york, (20, "on"), (21, "off")),
        *titles(new_york, (20, "Columbo")),
    ]
    lane = tv.build_lane(_context(records, new_york, sync_service))

    spell = _of(lane, "tv_playing")[0]
    assert spell.provenance.transformation_rule == "tv.programme"
    assert spell.provenance.raw_record_ids
    assert spell.provenance.thresholds["min_programme_minutes"] == 4
    assert any("Clipped to the on-signal" in note for note in spell.provenance.notes)


def test_an_unreachable_home_assistant_says_so_rather_than_saying_the_tv_was_off(
    new_york, sync_service
):
    lane = tv.build_lane(_context([], new_york, sync_service, available=False))

    assert not lane.available
    assert "could not be reached" in lane.unavailable_reason


def test_a_configured_but_silent_sensor_is_not_confused_with_a_missing_one(
    new_york, sync_service
):
    """Nothing recorded all day is a fact about the day, not about the config."""
    records = power(new_york, (0, "off"))
    lane = tv.build_lane(_context(records, new_york, sync_service))

    assert not lane.available
    assert "not reported on at any point" in lane.unavailable_reason
    # It reported. Telling someone to go add it would waste their time.
    assert "config.yaml" not in lane.unavailable_reason


def test_a_day_with_no_records_at_all_does_not_blame_the_config_alone(
    new_york, sync_service
):
    """A day before the sensor existed, or before it reached the allowlist.

    Both are far likelier than a missing config entry on a row that was working
    yesterday, so the reason names all three rather than only the one that
    sends someone to edit a file that is already correct.
    """
    lane = tv.build_lane(_context([], new_york, sync_service))

    assert not lane.available
    assert "recorder is an allowlist" in lane.unavailable_reason
    assert "did not exist yet" in lane.unavailable_reason


# --------------------------------------------------------------------------
# Wired into the day
# --------------------------------------------------------------------------


async def test_the_row_is_built_from_the_mock_day(sync_service, fixed_now):
    timeline = await sync_service.sync(force_refresh=True, now=fixed_now)
    lane = next(item for item in timeline.lanes if item.id == "tv")

    assert lane.available
    assert {event.category for event in lane.events} == {"tv_on", "tv_playing"}

    # Every programme falls inside an on-stretch, end to end.
    sittings = [
        (event.start_time, event.end_time)
        for event in lane.events
        if event.category == "tv_on"
    ]
    for spell in (event for event in lane.events if event.category == "tv_playing"):
        assert any(
            start <= spell.start_time and spell.end_time <= end for start, end in sittings
        ), f"{spell.label} at {spell.start_time} escaped its sitting"
