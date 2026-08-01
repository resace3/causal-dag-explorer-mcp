"""ActivityWatch: computer use, reduced at the boundary.

Three properties are worth pinning, because getting any of them wrong is the
kind of failure that looks fine on screen:

* **Reduction happens in the connector.** A window title or a URL the detail
  level does not permit must not exist anywhere downstream — not in a record,
  not in an event, not in the serialised lane. Trimming it at render time would
  still put it in the SQLite cache and in the API response.
* **Durations are not multiplied.** ActivityWatch's `flood` repeats a period
  once per heartbeat it absorbed, so a 45-minute idle stretch arrives nine
  times. Summing that reports a nine-hour day.
* **Time at the machine is never silently dropped.** Real idle data fragments
  into four-minute stretches split by six-minute breaks; a minimum that
  discarded them would show an empty evening for a day full of focus events.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import httpx
import pytest

from app.config.schema import ActivityWatchConfig
from app.config.settings import Settings
from app.connectors.activitywatch.client import ActivityWatchClient
from app.connectors.activitywatch.connector import (
    STREAM_AFK,
    STREAM_WEB,
    STREAM_WINDOW,
    ActivityWatchConnector,
)
from app.connectors.wearables.connector import WearablePayload
from app.feature_engineering.context import RuleContext
from app.feature_engineering.rules import computer_use
from app.normalization.normalizer import normalize
from app.services.day import day_window

DAY = date(2025, 6, 10)

BUCKETS = {
    "aw-watcher-afk_host": {"type": "afkstatus", "hostname": "host"},
    "aw-watcher-window_host": {"type": "currentwindow", "hostname": "host"},
    "aw-watcher-web-chrome": {"type": "web.tab.current", "hostname": "host"},
}


def _event(start: datetime, minutes: float, data: dict) -> dict:
    return {
        "timestamp": start.isoformat(),
        "duration": minutes * 60,
        "data": data,
    }


def _fake_server(afk=None, window=None, web=None, buckets=None):
    """An ActivityWatch server that answers query2 by which bucket was named."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/0/buckets/":
            return httpx.Response(200, json=buckets if buckets is not None else BUCKETS)
        if request.url.path == "/api/0/info":
            return httpx.Response(200, json={"version": "v0.13.2", "hostname": "host"})
        if request.url.path == "/api/0/query/":
            body = json.loads(request.content.decode())
            program = " ".join(body["query"])
            if "web-chrome" in program:
                return httpx.Response(200, json=[web or []])
            if "window_host" in program:
                return httpx.Response(200, json=[window or []])
            return httpx.Response(200, json=[afk or []])
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def live_settings(monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    return Settings(USE_MOCK_DATA=False)


def _connector(transport, settings, tz, **config):
    return ActivityWatchConnector(
        ActivityWatchConfig(**config),
        settings,
        tz,
        client=ActivityWatchClient("http://localhost:5600", transport=transport),
    )


def _day(new_york):
    window = day_window(DAY, new_york)
    return window, window.start - timedelta(hours=14), window.end + timedelta(hours=12)


def _context(records, new_york, sync_service, *, available=True, note=None):
    window, start, end = _day(new_york)
    return RuleContext(
        window=window,
        fetch_start=start,
        fetch_end=end,
        tz=new_york,
        config=sync_service.config.feature_engineering,
        normalized=normalize(records, start, end),
        wearable=WearablePayload(),
        activitywatch_available=available,
        activitywatch_note=note,
    )


# --------------------------------------------------------------------------
# Reduction at the boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("detail", "expect_title", "expect_web", "expect_url"),
    [
        ("app", False, False, False),
        ("domain", False, True, False),
        ("full", True, True, True),
    ],
)
async def test_detail_level_decides_what_is_ever_recorded(
    live_settings, new_york, detail, expect_title, expect_web, expect_url
):
    _window, start, _end = _day(new_york)
    moment = start + timedelta(hours=20)
    transport = _fake_server(
        afk=[_event(moment, 60, {"status": "not-afk"})],
        window=[_event(moment, 30, {"app": "chrome.exe", "title": "Bank statement — May"})],
        web=[
            _event(
                moment,
                30,
                {"url": "https://mail.example.com/inbox/message/9182", "title": "Re: results"},
            )
        ],
    )
    connector = _connector(transport, live_settings, new_york, detail=detail)

    result = await connector.fetch(start, start + timedelta(days=1))
    blob = json.dumps([record.model_dump(mode="json") for record in result.records])

    assert ("Bank statement" in blob) is expect_title
    assert any(record.stream == STREAM_WEB for record in result.records) is expect_web
    assert ("/inbox/message/9182" in blob) is expect_url
    # The domain survives every level that reads browsing at all.
    if expect_web:
        assert "mail.example.com" in blob


async def test_a_url_never_reaches_the_lane_unless_full_detail_is_asked_for(
    live_settings, new_york, sync_service
):
    _window, start, _end = _day(new_york)
    moment = day_window(DAY, new_york).start + timedelta(hours=10)
    transport = _fake_server(
        afk=[_event(moment, 90, {"status": "not-afk"})],
        window=[_event(moment, 90, {"app": "chrome.exe", "title": "Private thing"})],
        web=[_event(moment, 90, {"url": "https://example.org/a/secret/path", "title": "Secret"})],
    )
    connector = _connector(transport, live_settings, new_york, detail="domain")

    result = await connector.fetch(start, start + timedelta(days=2))
    lane = computer_use.build_lane(_context(result.records, new_york, sync_service))

    serialised = lane.model_dump_json()
    assert "/a/secret/path" not in serialised
    assert "Private thing" not in serialised
    assert "example.org" in serialised, "the domain is what the level does permit"


# --------------------------------------------------------------------------
# Duplicates
# --------------------------------------------------------------------------


async def test_repeated_flood_copies_do_not_multiply_the_day(live_settings, new_york):
    """`flood` returns one period once per heartbeat it absorbed."""
    _window, start, _end = _day(new_york)
    moment = day_window(DAY, new_york).start + timedelta(hours=9)
    copies = [_event(moment, 45, {"status": "not-afk"}) for _ in range(9)]
    # The last copy is the one that was still being extended when it ended.
    copies.append(_event(moment, 52, {"status": "not-afk"}))

    connector = _connector(
        _fake_server(afk=copies, window=[_event(moment, 45, {"app": "code.exe"})]),
        live_settings,
        new_york,
    )
    result = await connector.fetch(start, start + timedelta(days=2))

    afk = [record for record in result.records if record.stream == STREAM_AFK]
    assert len(afk) == 1, "ten copies of one period are one period"
    assert (afk[0].end_timestamp - afk[0].timestamp) == timedelta(minutes=52), (
        "the longest copy is the complete one"
    )


# --------------------------------------------------------------------------
# The lane
# --------------------------------------------------------------------------


async def test_short_stretches_at_the_machine_are_drawn_not_discarded(
    live_settings, new_york, sync_service
):
    """Fragmented idle data is the normal case, not an edge case."""
    window, start, _end = _day(new_york)
    first = window.start + timedelta(hours=17, minutes=14)
    afk = [
        _event(first, 4, {"status": "not-afk"}),
        _event(first + timedelta(minutes=9.5), 2.5, {"status": "not-afk"}),
        _event(first + timedelta(minutes=25), 4, {"status": "not-afk"}),
    ]
    connector = _connector(
        _fake_server(afk=afk, window=[_event(first, 4, {"app": "code.exe"})]),
        live_settings,
        new_york,
    )
    result = await connector.fetch(start, start + timedelta(days=2))
    lane = computer_use.build_lane(_context(result.records, new_york, sync_service))

    sessions = [event for event in lane.events if event.category == "at_computer"]
    assert len(sessions) == 3, "every stretch is drawn, however short"
    assert all(event.metadata["brief"] is True for event in sessions)
    total = sum(event.metadata["durationMinutes"] for event in sessions)
    assert total == pytest.approx(10.5, abs=0.2), "no recorded minute is lost"


async def test_idle_shorter_than_the_tolerance_does_not_split_a_session(
    live_settings, new_york, sync_service
):
    window, start, _end = _day(new_york)
    first = window.start + timedelta(hours=9)
    afk = [
        _event(first, 30, {"status": "not-afk"}),
        # Three minutes away, inside the five-minute tolerance.
        _event(first + timedelta(minutes=33), 30, {"status": "not-afk"}),
    ]
    connector = _connector(
        _fake_server(afk=afk, window=[_event(first, 30, {"app": "code.exe"})]),
        live_settings,
        new_york,
    )
    result = await connector.fetch(start, start + timedelta(days=2))
    lane = computer_use.build_lane(_context(result.records, new_york, sync_service))

    sessions = [event for event in lane.events if event.category == "at_computer"]
    assert len(sessions) == 1
    assert sessions[0].metadata["brief"] is False
    assert sessions[0].metadata["durationMinutes"] == pytest.approx(63, abs=0.2)


async def test_applications_are_named_and_carry_full_provenance(
    live_settings, new_york, sync_service
):
    window, start, _end = _day(new_york)
    first = window.start + timedelta(hours=13)
    windows = [
        _event(first, 20, {"app": "code.exe"}),
        # A glance away and back is one spell, not three.
        _event(first + timedelta(minutes=20), 0.5, {"app": "slack.exe"}),
        _event(first + timedelta(minutes=20.5), 25, {"app": "code.exe"}),
    ]
    connector = _connector(
        _fake_server(afk=[_event(first, 46, {"status": "not-afk"})], window=windows),
        live_settings,
        new_york,
    )
    result = await connector.fetch(start, start + timedelta(days=2))
    lane = computer_use.build_lane(_context(result.records, new_york, sync_service))

    apps = [event for event in lane.events if event.category == "app_session"]
    assert [event.label for event in apps] == ["Code", "Code"], (
        "an application is named as itself, with the .exe dropped for display"
    )
    assert all(event.metadata["recorded"] == "code.exe" for event in apps)
    for event in apps:
        assert event.provenance.transformation_rule == "computer_use.app_session"
        assert event.provenance.rule_version
        assert event.provenance.raw_record_ids


async def test_a_day_before_the_install_says_so_rather_than_going_blank(
    new_york, sync_service
):
    lane = computer_use.build_lane(_context([], new_york, sync_service))
    assert lane.available is False
    assert "recorded nothing" in lane.unavailable_reason
    assert "since it was installed" in lane.unavailable_reason


async def test_switched_off_reads_as_switched_off_not_as_no_data(new_york, sync_service):
    lane = computer_use.build_lane(
        _context(
            [],
            new_york,
            sync_service,
            available=False,
            note="ActivityWatch was not read for this day: Switched off in the MCPs panel.",
        )
    )
    assert lane.available is False
    assert "Switched off in the MCPs panel" in lane.unavailable_reason


async def test_no_idle_watcher_is_reported_rather_than_quietly_assumed(
    live_settings, new_york, sync_service
):
    """Without the AFK watcher, a window left open counts as use — say so."""
    window, start, _end = _day(new_york)
    first = window.start + timedelta(hours=11)
    connector = _connector(
        _fake_server(
            window=[_event(first, 40, {"app": "code.exe"})],
            buckets={"aw-watcher-window_host": {"type": "currentwindow", "hostname": "host"}},
        ),
        live_settings,
        new_york,
    )
    result = await connector.fetch(start, start + timedelta(days=2))
    assert any("no idle watcher" in warning for warning in result.warnings)

    context = _context(result.records, new_york, sync_service)
    lane = computer_use.build_lane(context)
    session = next(event for event in lane.events if event.category == "at_computer")
    assert session.data_quality == "medium"
    assert "no idle watcher" in session.metadata["note"]
    assert any("inferred from focus" in warning for warning in context.warnings)


# --------------------------------------------------------------------------
# Failure and configuration
# --------------------------------------------------------------------------


async def test_an_unreachable_server_names_the_fix_and_loses_no_other_lane(
    live_settings, new_york
):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    connector = _connector(httpx.MockTransport(refuse), live_settings, new_york)
    status, detail, capabilities = await connector.check_status()
    assert status == "error"
    assert "ActivityWatch app is running" in detail
    assert capabilities == []

    result = await connector.fetch(*_day(new_york)[1:])
    assert result.records == []
    assert result.errors
    assert "other lanes are unaffected" in result.errors[0]


async def test_capabilities_come_from_the_watchers_that_exist(live_settings, new_york):
    """The browser extension is often not installed; do not claim it."""
    connector = _connector(
        _fake_server(
            buckets={
                "aw-watcher-afk_host": {"type": "afkstatus", "hostname": "host"},
                "aw-watcher-window_host": {"type": "currentwindow", "hostname": "host"},
            }
        ),
        live_settings,
        new_york,
    )
    _status, _detail, capabilities = await connector.check_status()
    assert sorted(capabilities) == ["idle_detection", "window_activity"]


async def test_two_machines_are_not_merged_into_one_day(live_settings, new_york):
    buckets = {
        "aw-watcher-window_desktop": {"type": "currentwindow", "hostname": "desktop"},
        "aw-watcher-window_laptop": {"type": "currentwindow", "hostname": "laptop"},
    }
    connector = _connector(_fake_server(buckets=buckets), live_settings, new_york)
    result = await connector.fetch(*_day(new_york)[1:])
    assert any("two machines" in warning for warning in result.warnings)
    assert any("activitywatch.hostname" in warning for warning in result.warnings)


async def test_a_named_hostname_selects_one_machine(live_settings, new_york):
    buckets = {
        "aw-watcher-window_desktop": {"type": "currentwindow", "hostname": "desktop"},
        "aw-watcher-window_laptop": {"type": "currentwindow", "hostname": "laptop"},
    }
    connector = _connector(
        _fake_server(buckets=buckets), live_settings, new_york, hostname="laptop"
    )
    chosen, warnings = connector._select_buckets(buckets)
    assert chosen[STREAM_WINDOW] == "aw-watcher-window_laptop"
    assert warnings == []


async def test_mock_mode_never_contacts_a_server(new_york, monkeypatch):
    """`USE_MOCK_DATA` has to hold for this source too, or a demo install on a
    machine that happens to run ActivityWatch shows real activity."""

    def explode(request):  # pragma: no cover - reaching this is the failure
        raise AssertionError("mock mode contacted the ActivityWatch server")

    connector = _connector(
        httpx.MockTransport(explode), Settings(USE_MOCK_DATA=True), new_york
    )
    _window, start, end = _day(new_york)
    result = await connector.fetch(start, end)

    assert result.status == "mock_data"
    assert result.records
    assert {record.stream for record in result.records} == {
        STREAM_AFK,
        STREAM_WINDOW,
        STREAM_WEB,
    }


async def test_the_mock_day_is_reproducible(new_york):
    connector = _connector(None, Settings(USE_MOCK_DATA=True, MOCK_DATA_SEED=42), new_york)
    _window, start, end = _day(new_york)
    first = await connector.fetch(start, end)
    second = await connector.fetch(start, end)
    assert [record.id for record in first.records] == [record.id for record in second.records]
