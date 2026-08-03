"""The Phone Use custom row, from the usage-stats add-on.

One idea runs through all of it: the add-on answers two different questions
about the same app and only one of the answers is a total. Segments know *when*
but credit an in-app browser to the browser; `/v1/apps` knows *how much* with
task-root attribution but has no timing. Mixing them up understates
browser-heavy apps several-fold, so the row draws one and quotes the other.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx
import pytest

from app.config.schema import PhoneUsageConfig
from app.config.settings import Settings
from app.connectors.phone_usage.client import PhoneUsageClient, PhoneUsageError
from app.connectors.phone_usage.connector import (
    STREAM_APP_DAILY,
    STREAM_DAY_SUMMARY,
    STREAM_SEGMENT,
    PhoneUsageConnector,
)
from app.connectors.wearables.connector import WearablePayload
from app.feature_engineering.context import RuleContext
from app.feature_engineering.rules import phone_use_custom
from app.models.raw import RawRecord
from app.normalization.normalizer import normalize
from app.services.day import day_window

DAY = date(2025, 6, 10)
TIKTOK = "com.zhiliaoapp.musically"
CHROME = "com.android.chrome"


def _at(new_york, hour: float) -> datetime:
    return datetime(2025, 6, 10, tzinfo=new_york) + timedelta(hours=hour)


def segment(new_york, package: str, start_hour: float, end_hour: float) -> RawRecord:
    begin, finish = _at(new_york, start_hour), _at(new_york, end_hour)
    return RawRecord(
        id=RawRecord.make_id("phone_usage", STREAM_SEGMENT, f"{package}|{begin.isoformat()}"),
        source="phone_usage",
        stream=STREAM_SEGMENT,
        device="phone",
        timestamp=begin,
        end_timestamp=finish,
        value=package,
        unit="seconds",
        attributes={"package": package, "attribution": "package"},
    )


def daily_total(new_york, package: str, minutes: float) -> RawRecord:
    stamp = _at(new_york, 0)
    return RawRecord(
        id=RawRecord.make_id("phone_usage", STREAM_APP_DAILY, f"2025-06-10|{package}"),
        source="phone_usage",
        stream=STREAM_APP_DAILY,
        device="phone",
        timestamp=stamp,
        value=minutes,
        unit="minutes",
        attributes={
            "package": package,
            "date": "2025-06-10",
            "attribution": "task_root",
        },
    )


def day_summary(new_york, **values) -> RawRecord:
    return RawRecord(
        id=RawRecord.make_id("phone_usage", STREAM_DAY_SUMMARY, "2025-06-10"),
        source="phone_usage",
        stream=STREAM_DAY_SUMMARY,
        device="phone",
        timestamp=_at(new_york, 0),
        value=values.get("screen_on_minutes"),
        unit="minutes",
        attributes={"date": "2025-06-10", **values},
    )


def _context(records, new_york, sync_service) -> RuleContext:
    window = day_window(DAY, new_york)
    start = window.start - timedelta(hours=14)
    end = window.end + timedelta(hours=12)
    return RuleContext(
        window=window,
        fetch_start=start,
        fetch_end=end,
        tz=new_york,
        config=sync_service.config.feature_engineering,
        normalized=normalize(records, start, end, now=end),
        wearable=WearablePayload(),
    )


def _of(lane, category):
    return [event for event in lane.events if event.category == category]


# --------------------------------------------------------------------------
# The two answers, kept apart
# --------------------------------------------------------------------------


def test_a_spell_quotes_the_authoritative_total_rather_than_summing_bars(
    new_york, sync_service
):
    """Adding the bars up gives 30 minutes; the system says 140. Both are shown."""
    records = [
        segment(new_york, TIKTOK, 19, 19.25),
        segment(new_york, TIKTOK, 20, 20.25),
        daily_total(new_york, TIKTOK, 140.0),
    ]
    lane = phone_use_custom.build_lane(_context(records, new_york, sync_service))

    spells = _of(lane, "phone_custom_app")
    assert [event.metadata["durationMinutes"] for event in spells] == [15.0, 15.0]
    for spell in spells:
        assert spell.metadata["authoritativeDailyMinutes"] == 140.0
        assert spell.metadata["attribution"] == "package"
        assert "will not reach it" in spell.metadata["note"]


def test_a_spell_without_a_daily_total_says_so_rather_than_implying_one(
    new_york, sync_service
):
    records = [segment(new_york, TIKTOK, 19, 19.5)]
    lane = phone_use_custom.build_lane(_context(records, new_york, sync_service))

    spell = _of(lane, "phone_custom_app")[0]
    assert spell.metadata["authoritativeDailyMinutes"] is None
    assert "No authoritative daily total" in spell.metadata["note"]


def test_totals_from_another_day_are_not_borrowed(new_york, sync_service):
    """`/v1/apps` is fetched per day; the wrong day's figure would be a lie."""
    other = daily_total(new_york, TIKTOK, 999.0)
    other.attributes["date"] = "2025-06-09"

    records = [segment(new_york, TIKTOK, 19, 19.5), other]
    lane = phone_use_custom.build_lane(_context(records, new_york, sync_service))

    assert _of(lane, "phone_custom_app")[0].metadata["authoritativeDailyMinutes"] is None


# --------------------------------------------------------------------------
# Pickups and spells
# --------------------------------------------------------------------------


def test_adjacent_segments_become_one_pickup(new_york, sync_service):
    records = [
        segment(new_york, TIKTOK, 19, 19.2),
        segment(new_york, CHROME, 19.2, 19.4),
    ]
    lane = phone_use_custom.build_lane(_context(records, new_york, sync_service))

    pickups = _of(lane, "phone_custom_on")
    assert len(pickups) == 1
    assert pickups[0].metadata["durationMinutes"] == 24.0
    assert pickups[0].metadata["segmentCount"] == 2


def test_a_long_gap_starts_a_second_pickup(new_york, sync_service):
    records = [
        segment(new_york, TIKTOK, 9, 9.2),
        segment(new_york, TIKTOK, 14, 14.2),
    ]
    lane = phone_use_custom.build_lane(_context(records, new_york, sync_service))

    assert len(_of(lane, "phone_custom_on")) == 2


def test_nothing_is_clipped_against_a_screen_sensor(new_york, sync_service):
    """The difference from the companion-app row: these segments end by themselves.

    No `device_use` entity is configured in this context at all, and the row
    still draws — where the other row would withhold everything.
    """
    records = [segment(new_york, TIKTOK, 19, 19.5)]
    lane = phone_use_custom.build_lane(_context(records, new_york, sync_service))

    assert lane.available
    spell = _of(lane, "phone_custom_app")[0]
    assert spell.end_time == _at(new_york, 19.5)
    assert any("nothing is clipped" in note for note in spell.provenance.notes) or any(
        "real end times" in note
        for note in _of(lane, "phone_custom_on")[0].provenance.notes
    )


def test_the_day_counts_survive_a_clipped_first_pickup(new_york, sync_service):
    """The fetch window opens fourteen hours early, so the first span is usually
    last night and is clipped away. Keying the counts to it loses them."""
    last_night = segment(new_york, TIKTOK, -5, -4.5)
    records = [
        last_night,
        segment(new_york, TIKTOK, 9, 9.5),
        day_summary(new_york, screen_on_minutes=180.0, unlocks=32),
    ]
    lane = phone_use_custom.build_lane(_context(records, new_york, sync_service))

    pickups = _of(lane, "phone_custom_on")
    assert pickups[0].metadata["dayCounts"]["unlocks"] == 32


def test_the_day_counts_ride_on_the_first_pickup_only(new_york, sync_service):
    records = [
        segment(new_york, TIKTOK, 9, 9.5),
        segment(new_york, CHROME, 14, 14.5),
        day_summary(new_york, screen_on_minutes=180.0, unlocks=32, glances_without_unlock=38),
    ]
    lane = phone_use_custom.build_lane(_context(records, new_york, sync_service))

    pickups = _of(lane, "phone_custom_on")
    assert pickups[0].metadata["dayCounts"]["unlocks"] == 32
    assert pickups[0].metadata["dayCounts"]["glancesWithoutUnlock"] == 38
    assert "whole day" in pickups[0].metadata["dayCounts"]["note"]
    assert "dayCounts" not in pickups[1].metadata


def test_an_empty_day_says_the_collector_may_simply_not_reach_back(
    new_york, sync_service
):
    lane = phone_use_custom.build_lane(_context([], new_york, sync_service))

    assert not lane.available
    assert "eight days" in lane.unavailable_reason


# --------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------


def _client(handler) -> PhoneUsageClient:
    return PhoneUsageClient(
        "http://addon:8099", "tok", transport=httpx.MockTransport(handler)
    )


async def test_today_is_asked_for_by_window_not_by_date(new_york, tmp_path):
    """Android's daily buckets do not start at midnight, so `?date=` misses today."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"apps": []})

    client = _client(handler)
    await client.apps(date(2025, 6, 10), current_window=True)
    await client.apps(date(2025, 6, 9), current_window=False)

    assert seen[0] == {"window": "current"}
    assert seen[1] == {"date": "2025-06-09"}


async def test_a_rejected_token_says_which_setting_to_fix():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "nope"})

    with pytest.raises(PhoneUsageError, match="PHONE_USAGE_TOKEN"):
        await _client(handler).status()


async def test_an_unreachable_addon_does_not_claim_the_phone_was_idle():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(PhoneUsageError, match="Could not reach"):
        await _client(handler).timeline(date(2025, 6, 10))


async def test_the_connector_drops_segments_outside_the_window(new_york, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/timeline":
            far = int(datetime(2020, 1, 1, tzinfo=new_york).timestamp() * 1000)
            near = int(_at(new_york, 12).timestamp() * 1000)
            return httpx.Response(
                200,
                json={
                    "segments": [
                        {"pkg": TIKTOK, "start": far, "end": far + 60_000},
                        {"pkg": TIKTOK, "start": near, "end": near + 60_000},
                    ]
                },
            )
        return httpx.Response(200, json={"apps": [], "date": "2025-06-10"})

    settings = Settings(
        PHONE_USAGE_URL="http://addon:8099", PHONE_USAGE_TOKEN="tok", USE_MOCK_DATA=False
    )
    connector = PhoneUsageConnector(
        PhoneUsageConfig(), settings, new_york, client=_client(handler)
    )
    window = day_window(DAY, new_york)
    result = await connector.fetch(window.start, window.end)

    segments = [record for record in result.records if record.stream == STREAM_SEGMENT]
    assert len(segments) == 1


async def test_a_segment_returned_for_two_days_is_stored_once(new_york):
    """A segment spanning midnight appears in both days' answers.

    The connector asks per local day, so without deduplication that segment is
    drawn twice and counted twice in the pickup above it.
    """
    near = int(_at(new_york, 12).timestamp() * 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/timeline":
            return httpx.Response(
                200, json={"segments": [{"pkg": TIKTOK, "start": near, "end": near + 60_000}]}
            )
        return httpx.Response(200, json={"apps": []})

    settings = Settings(
        PHONE_USAGE_URL="http://addon:8099", PHONE_USAGE_TOKEN="tok", USE_MOCK_DATA=False
    )
    connector = PhoneUsageConnector(
        PhoneUsageConfig(), settings, new_york, client=_client(handler)
    )
    window = day_window(DAY, new_york)
    result = await connector.fetch(window.start, window.end)

    assert len([r for r in result.records if r.stream == STREAM_SEGMENT]) == 1
