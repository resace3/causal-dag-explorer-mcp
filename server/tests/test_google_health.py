"""Sleep and steps from Google Health, and the pinning that makes it the source.

Three things are being defended here. The connector must throw away the
hypnogram where it arrives, so a row that reports duration never quietly
carries a night's worth of stage data behind it. A pinned metric must not fall
through: the point of pinning to one source is that a day it missed is reported
missing, not answered by a different device. And steps must survive their own
volume — a night of sleep is one record, a day of steps is well over a
thousand, and the paging that suits the first silently truncates the second.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.config.schema import GoogleHealthMcpConfig, McpServerConfig, WearableConfig
from app.connectors.wearables import google_health_mcp
from app.connectors.wearables.base import (
    BaseWearableProvider,
    WearableCapabilities,
    WearableProviderError,
    WearableSleepRecord,
)
from app.connectors.wearables.composite import CompositeWearableProvider
from app.connectors.wearables.google_health_mcp import GoogleHealthMcpProvider


def _point(
    start: str,
    end: str,
    *,
    asleep: str = "467",
    in_period: str = "473",
    awake: str = "6",
    main: bool = True,
    nap: bool = False,
    identifier: str = "7078689973880976752",
) -> dict:
    """One dataPoint shaped like the live API, hypnogram included."""
    metadata: dict = {"stagesStatus": "SUCCEEDED", "processed": True}
    if main:
        metadata["mainSleep"] = True
    if nap:
        metadata["nap"] = True
    return {
        "name": f"users/1072695141783834959/dataTypes/sleep/dataPoints/{identifier}",
        "dataSource": {
            "recordingMethod": "DERIVED",
            "device": {"displayName": "Inspire 3"},
            "platform": "FITBIT",
        },
        "sleep": {
            "interval": {"startTime": start, "endTime": end},
            "type": "STAGES",
            "stages": [
                {"startTime": start, "endTime": end, "type": "LIGHT"},
                {"startTime": start, "endTime": end, "type": "DEEP"},
            ],
            "metadata": metadata,
            "summary": {
                "minutesInSleepPeriod": in_period,
                "minutesAsleep": asleep,
                "minutesAwake": awake,
            },
        },
    }


def _steps_point(start: str, end: str, count: str, *, device: str = "Inspire 3") -> dict:
    """One steps dataPoint shaped like the live API: a delta, not a total."""
    return {
        "dataSource": {
            "recordingMethod": "PASSIVELY_MEASURED",
            "device": {"displayName": device},
            "platform": "FITBIT",
        },
        "steps": {
            "interval": {"startTime": start, "endTime": end},
            "count": count,
        },
    }


class FakeSession:
    """Stands in for an MCP stdio session, and refuses anything unlisted."""

    def __init__(self, pages: list[dict], tools: list[str] | None = None) -> None:
        self.pages = pages
        self.tools = tools if tools is not None else ["google_health_list_data_points"]
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[str]:
        return sorted(self.tools)

    async def call_json(self, tool: str, arguments: dict):
        assert tool in google_health_mcp.ALLOWED_TOOLS, f"{tool} is not read-only"
        self.calls.append((tool, arguments))
        if tool == "google_health_connection_status":
            return {"ok": True, "token": {"has_refresh_token": True}}
        index = 0
        if arguments.get("page_token"):
            index = int(arguments["page_token"])
        return self.pages[index] if index < len(self.pages) else {"data": {"dataPoints": []}}


@pytest.fixture
def patched_session(monkeypatch):
    """Install a fake `open_session`, and hand back the session it yields."""
    holder: dict[str, FakeSession] = {}

    def install(session: FakeSession) -> FakeSession:
        holder["session"] = session

        class _Ctx:
            async def __aenter__(self_inner):
                return session

            async def __aexit__(self_inner, *exc):
                return False

        monkeypatch.setattr(
            google_health_mcp, "open_session", lambda *args, **kwargs: _Ctx()
        )
        return session

    return install


def _provider(new_york) -> GoogleHealthMcpProvider:
    return GoogleHealthMcpProvider(
        GoogleHealthMcpConfig(), McpServerConfig(command="noop"), new_york
    )


def _window(new_york) -> tuple[datetime, datetime]:
    start = datetime(2026, 7, 30, tzinfo=new_york)
    return start, start + timedelta(days=1)


# --------------------------------------------------------------------------
# Reduction at the boundary
# --------------------------------------------------------------------------


async def test_the_hypnogram_is_discarded_at_the_connector(patched_session, new_york):
    """The row reports duration, so the stages must not reach the data model."""
    patched_session(
        FakeSession([{"data": {"dataPoints": [_point("2026-07-30T04:26:00Z", "2026-07-30T12:30:00Z")]}}])
    )
    start, end = _window(new_york)

    records = await _provider(new_york).get_sleep(start, end)

    assert len(records) == 1
    assert records[0].stages == [], "a duration row must not carry a night of stages"
    # But the fact that stages existed is worth keeping, so nobody wonders.
    assert records[0].metadata["stagesRecorded"] is True


async def test_the_period_is_converted_to_local_time(patched_session, new_york):
    patched_session(
        FakeSession([{"data": {"dataPoints": [_point("2026-07-30T04:26:00Z", "2026-07-30T12:30:00Z")]}}])
    )
    start, end = _window(new_york)

    record = (await _provider(new_york).get_sleep(start, end))[0]

    # 04:26 UTC is 00:26 in New York, which is the day this night belongs to.
    assert (record.start.hour, record.start.minute) == (0, 26)
    assert (record.end.hour, record.end.minute) == (8, 30)
    assert record.metadata["minutesAsleep"] == 467.0
    assert record.time_in_bed_minutes == 473.0
    assert record.device == "Inspire 3"


async def test_a_night_that_began_before_the_window_still_counts(patched_session, new_york):
    """Sleep crosses midnight; containment would drop every real night."""
    patched_session(
        FakeSession([{"data": {"dataPoints": [_point("2026-07-30T03:00:00Z", "2026-07-30T11:00:00Z")]}}])
    )
    # A window starting at 06:00 local, well after the 23:00 start.
    start = datetime(2026, 7, 29, 23, 0, tzinfo=new_york)
    end = start + timedelta(hours=12)

    assert len(await _provider(new_york).get_sleep(start, end)) == 1


async def test_records_outside_the_window_are_dropped(patched_session, new_york):
    patched_session(
        FakeSession(
            [
                {
                    "data": {
                        "dataPoints": [
                            _point("2026-07-30T04:26:00Z", "2026-07-30T12:30:00Z"),
                            _point(
                                "2026-07-20T04:26:00Z",
                                "2026-07-20T12:30:00Z",
                                identifier="older",
                            ),
                        ]
                    }
                }
            ]
        )
    )
    start, end = _window(new_york)

    records = await _provider(new_york).get_sleep(start, end)

    assert [record.id for record in records] == ["7078689973880976752"]


async def test_an_explicit_nap_is_not_promoted_to_main_sleep(patched_session, new_york):
    """The API sets both flags on some short records; `nap` is the specific one."""
    patched_session(
        FakeSession(
            [
                {
                    "data": {
                        "dataPoints": [
                            _point(
                                "2026-07-30T04:39:00Z",
                                "2026-07-30T05:16:00Z",
                                asleep="33",
                                in_period="37",
                                main=True,
                                nap=True,
                            )
                        ]
                    }
                }
            ]
        )
    )
    start, end = _window(new_york)

    assert (await _provider(new_york).get_sleep(start, end))[0].is_main_sleep is False


async def test_paging_stops_once_it_reaches_past_the_window(patched_session, new_york):
    session = patched_session(
        FakeSession(
            [
                {
                    "data": {
                        "dataPoints": [_point("2026-08-02T05:21:00Z", "2026-08-02T13:14:00Z")],
                        "nextPageToken": "1",
                    }
                },
                {
                    "data": {
                        "dataPoints": [
                            _point(
                                "2026-07-30T04:26:00Z",
                                "2026-07-30T12:30:00Z",
                                identifier="wanted",
                            ),
                            # Reaches past the start of the window, so there is
                            # nothing older left to look for.
                            _point(
                                "2026-07-28T04:26:00Z",
                                "2026-07-28T12:30:00Z",
                                identifier="older",
                            ),
                        ],
                        "nextPageToken": "2",
                    }
                },
                {"data": {"dataPoints": [_point("2026-01-01T05:00:00Z", "2026-01-01T12:00:00Z")]}},
            ]
        )
    )
    start, end = _window(new_york)

    records = await _provider(new_york).get_sleep(start, end)

    assert [record.id for record in records] == ["wanted"]
    # The third page is never asked for: page two already reached the window.
    page_calls = [call for call in session.calls if call[0] == "google_health_list_data_points"]
    assert len(page_calls) == 2


async def test_prose_instead_of_json_is_no_data_rather_than_an_error(
    patched_session, new_york
):
    patched_session(FakeSession([None]))
    start, end = _window(new_york)

    assert await _provider(new_york).get_sleep(start, end) == []


async def test_it_claims_only_the_metrics_it_was_asked_for(patched_session, new_york):
    """Google Health carries heart rate, VO2 max, oxygen saturation and more.

    Each capability here was added because a row was pointed at it. Claiming the
    rest would make this provider start winning metrics that already have a
    source, which is exactly what pinning exists to prevent.
    """
    patched_session(FakeSession([{"data": {"dataPoints": []}}]))

    capabilities = await _provider(new_york).get_capabilities()

    assert capabilities.capabilities == ["sleep", "steps"]


async def test_a_server_without_the_data_point_tool_says_so(patched_session, new_york):
    patched_session(FakeSession([{"data": {"dataPoints": []}}], tools=["google_health_demo"]))

    with pytest.raises(WearableProviderError, match="list_data_points"):
        await _provider(new_york).get_capabilities()


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------


async def test_steps_arrive_as_deltas_with_their_interval(patched_session, new_york):
    patched_session(
        FakeSession(
            [
                {
                    "data": {
                        "dataPoints": [
                            _steps_point(
                                "2026-07-30T14:24:00Z", "2026-07-30T14:25:00Z", "37"
                            )
                        ]
                    }
                }
            ]
        )
    )
    start, end = _window(new_york)

    buckets = await _provider(new_york).get_steps(start, end)

    assert len(buckets) == 1
    assert buckets[0].count == 37
    assert (buckets[0].end - buckets[0].start) == timedelta(minutes=1)
    assert buckets[0].device == "Inspire 3"
    # Converted out of UTC, like every other stamp this connector reads.
    assert buckets[0].start.hour == 10


async def test_an_empty_first_page_does_not_end_the_walk(patched_session, new_york):
    """The live API answers the first steps page with a token and no points.

    Treating that as the end of the data reports a day with no movement on it,
    which is indistinguishable from a day spent sitting down.
    """
    session = patched_session(
        FakeSession(
            [
                {"data": {"dataPoints": [], "nextPageToken": "1"}},
                {
                    "data": {
                        "dataPoints": [
                            _steps_point(
                                "2026-07-30T14:24:00Z", "2026-07-30T14:25:00Z", "48"
                            )
                        ]
                    }
                },
            ]
        )
    )
    start, end = _window(new_york)

    buckets = await _provider(new_york).get_steps(start, end)

    assert [bucket.count for bucket in buckets] == [48]
    assert len(session.calls) == 2, "it must follow the token past the empty page"


async def test_steps_ask_for_a_page_big_enough_for_a_day_of_minutes(
    patched_session, new_york
):
    """A day is ~1440 buckets; the sleep page size would need fifteen pages."""
    session = patched_session(FakeSession([{"data": {"dataPoints": []}}]))
    start, end = _window(new_york)

    await _provider(new_york).get_steps(start, end)

    _tool, arguments = session.calls[0]
    assert arguments["data_type"] == "steps"
    assert arguments["page_size"] >= 1000


def _misaligned_phone(minute: int, count: str) -> dict:
    """A phone bucket: ragged, never lining up with the watch's whole minutes.

    This is what the live API actually returns for HEALTH_CONNECT — intervals of
    52 or 79 seconds starting mid-second — and it is why deduplicating by
    timestamp cannot work.
    """
    point = _steps_point(
        f"2026-07-30T14:{minute:02d}:19.679Z",
        f"2026-07-30T14:{minute + 1:02d}:38.360Z",
        count,
    )
    point["dataSource"]["platform"] = "HEALTH_CONNECT"
    point["dataSource"].pop("device")
    return point


async def test_two_devices_counting_the_same_feet_are_not_summed(
    patched_session, new_york
):
    """The bug this caught: 15,228 real steps reported as 22,312.

    A watch and a phone both count a walk. Their buckets do not share a start,
    so nothing deduplicates them, and the day is inflated by however much of it
    was walked carrying both.
    """
    watch = [
        _steps_point(f"2026-07-30T14:{m:02d}:00Z", f"2026-07-30T14:{m + 1:02d}:00Z", "100")
        for m in range(0, 10)
    ]
    phone = [_misaligned_phone(m, "60") for m in range(0, 6)]
    patched_session(FakeSession([{"data": {"dataPoints": watch + phone}}]))
    start, end = _window(new_york)

    buckets = await _provider(new_york).get_steps(start, end)

    assert sum(bucket.count for bucket in buckets) == 1000, "the watch alone, not the sum"
    assert {bucket.device for bucket in buckets} == {"Inspire 3"}


async def test_the_discarded_source_is_reported_not_silently_dropped(
    patched_session, new_york
):
    """Dropping thousands of steps without saying so is its own dishonesty."""
    watch = [
        _steps_point(f"2026-07-30T14:{m:02d}:00Z", f"2026-07-30T14:{m + 1:02d}:00Z", "100")
        for m in range(0, 10)
    ]
    phone = [_misaligned_phone(m, "60") for m in range(0, 6)]
    patched_session(FakeSession([{"data": {"dataPoints": watch + phone}}]))
    start, end = _window(new_york)

    buckets = await _provider(new_york).get_steps(start, end)

    discarded = buckets[0].metadata["chosenOver"]
    assert len(discarded) == 1
    assert discarded[0]["platform"] == "HEALTH_CONNECT"
    assert discarded[0]["steps"] == 360


async def test_the_source_that_saw_more_of_the_day_wins(patched_session, new_york):
    """So the watch wins when it was worn, and the phone when it was not."""
    watch = [
        _steps_point(f"2026-07-30T14:{m:02d}:00Z", f"2026-07-30T14:{m + 1:02d}:00Z", "100")
        for m in range(0, 2)
    ]
    phone = [_misaligned_phone(m, "10") for m in range(0, 8)]
    patched_session(FakeSession([{"data": {"dataPoints": watch + phone}}]))
    start, end = _window(new_york)

    buckets = await _provider(new_york).get_steps(start, end)

    assert {bucket.device for bucket in buckets} == {None}, "the phone covered more"
    assert buckets[0].metadata["chosenOver"][0]["device"] == "Inspire 3"


async def test_one_source_alone_reports_nothing_discarded(patched_session, new_york):
    patched_session(
        FakeSession(
            [
                {
                    "data": {
                        "dataPoints": [
                            _steps_point(
                                "2026-07-30T14:24:00Z", "2026-07-30T14:25:00Z", "37"
                            )
                        ]
                    }
                }
            ]
        )
    )
    start, end = _window(new_york)

    buckets = await _provider(new_york).get_steps(start, end)

    assert "chosenOver" not in buckets[0].metadata


async def test_a_bucket_belongs_to_the_day_it_started_in(patched_session, new_york):
    """Overlap would count a straddling minute into both days."""
    patched_session(
        FakeSession(
            [
                {
                    "data": {
                        "dataPoints": [
                            # 23:59 local on the 29th — before the window opens.
                            _steps_point(
                                "2026-07-30T03:59:00Z", "2026-07-30T04:00:00Z", "20"
                            ),
                            _steps_point(
                                "2026-07-30T04:00:00Z", "2026-07-30T04:01:00Z", "21"
                            ),
                        ]
                    }
                }
            ]
        )
    )
    start, end = _window(new_york)

    buckets = await _provider(new_york).get_steps(start, end)

    assert [bucket.count for bucket in buckets] == [21]


async def test_a_malformed_count_is_dropped_rather_than_guessed(
    patched_session, new_york
):
    patched_session(
        FakeSession(
            [
                {
                    "data": {
                        "dataPoints": [
                            _steps_point(
                                "2026-07-30T14:24:00Z", "2026-07-30T14:25:00Z", "many"
                            ),
                            _steps_point(
                                "2026-07-30T14:25:00Z", "2026-07-30T14:26:00Z", "12"
                            ),
                        ]
                    }
                }
            ]
        )
    )
    start, end = _window(new_york)

    buckets = await _provider(new_york).get_steps(start, end)

    assert [bucket.count for bucket in buckets] == [12]


# --------------------------------------------------------------------------
# Pinning
# --------------------------------------------------------------------------


class StubProvider(BaseWearableProvider):
    def __init__(self, name: str, records: list[WearableSleepRecord]) -> None:
        self.name = name
        self.records = records

    async def get_capabilities(self) -> WearableCapabilities:
        return WearableCapabilities(provider=self.name, capabilities=["sleep"])

    async def get_sleep(self, start, end):
        return list(self.records)


def _record(identifier: str) -> WearableSleepRecord:
    start = datetime(2026, 7, 30, 1, 0)
    return WearableSleepRecord(id=identifier, start=start, end=start + timedelta(hours=7))


async def test_a_pinned_metric_never_falls_through_to_another_route(new_york):
    """The whole reason for pinning: a missing night stays missing."""
    composite = CompositeWearableProvider(
        [
            ("google_health_mcp", StubProvider("google_health_mcp", [])),
            ("garmin_mcp", StubProvider("garmin_mcp", [_record("garmin")])),
        ],
        {"sleep": ["google_health_mcp"]},
    )
    await composite.get_capabilities()

    start = datetime(2026, 7, 30)
    assert await composite.get_sleep(start, start + timedelta(days=1)) == []


async def test_an_unpinned_metric_still_falls_through(new_york):
    composite = CompositeWearableProvider(
        [
            ("google_health_mcp", StubProvider("google_health_mcp", [])),
            ("garmin_mcp", StubProvider("garmin_mcp", [_record("garmin")])),
        ]
    )
    await composite.get_capabilities()

    start = datetime(2026, 7, 30)
    records = await composite.get_sleep(start, start + timedelta(days=1))

    assert [record.id for record in records] == ["garmin"]


async def test_the_pin_is_named_in_the_capability_detail(new_york):
    composite = CompositeWearableProvider(
        [("google_health_mcp", StubProvider("google_health_mcp", [_record("gh")]))],
        {"sleep": ["google_health_mcp"]},
    )

    capabilities = await composite.get_capabilities()

    assert "Pinned: sleep only from google_health_mcp" in (capabilities.detail or "")


def test_an_empty_pin_is_refused_rather_than_ignored():
    with pytest.raises(ValueError, match="metric_routes.sleep is empty"):
        WearableConfig(metric_routes={"sleep": []})
