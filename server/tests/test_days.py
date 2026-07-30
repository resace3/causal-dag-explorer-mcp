"""Choosing which day to reconstruct."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import create_app


@pytest.fixture
def client(repository, sync_service):
    app = create_app()
    routes.configure(repository, sync_service)
    with TestClient(app) as test_client:
        routes.configure(repository, sync_service)
        yield test_client


def test_a_specific_day_can_be_reconstructed(client, sync_service):
    day = (sync_service.today() - timedelta(days=4)).isoformat()
    body = client.get(f"/api/day/{day}").json()

    assert body["date"] == day
    assert body["dayLengthHours"] == 24.0
    assert body["summary"]["rawRecordCount"] > 0
    assert any(lane["available"] for lane in body["lanes"])


def test_each_day_is_reconstructed_independently(client, sync_service):
    """Two different days must not share a timeline."""
    first = (sync_service.today() - timedelta(days=3)).isoformat()
    second = (sync_service.today() - timedelta(days=5)).isoformat()

    a = client.get(f"/api/day/{first}").json()
    b = client.get(f"/api/day/{second}").json()

    assert a["date"] == first
    assert b["date"] == second
    assert a["dayStart"] != b["dayStart"]


def test_a_future_day_is_refused(client, sync_service):
    future = (sync_service.today() + timedelta(days=1)).isoformat()
    response = client.get(f"/api/day/{future}")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "future_date"
    assert "has not happened yet" in body["error"]["message"]


def test_today_is_allowed(client, sync_service):
    """Today is incomplete, not invalid."""
    today = sync_service.today().isoformat()
    assert client.get(f"/api/day/{today}").status_code == 200


def test_a_malformed_date_is_rejected_with_the_expected_format(client):
    response = client.get("/api/day/last-tuesday")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_date"
    assert "YYYY-MM-DD" in body["error"]["message"]


def test_the_days_index_marks_what_is_stored(client, sync_service):
    day = (sync_service.today() - timedelta(days=2)).isoformat()
    client.get(f"/api/day/{day}")  # reconstruct it, so it becomes "stored"

    body = client.get("/api/days").json()
    assert body["today"] == sync_service.today().isoformat()
    assert body["yesterday"] == sync_service.yesterday().iso_date

    index = {row["date"]: row for row in body["days"]}
    assert index[day]["stored"] is True
    assert index[day]["hasData"] is True
    assert index[day]["eventCount"] > 0

    # A day nobody has looked at is listed but not marked as stored.
    untouched = (sync_service.today() - timedelta(days=40)).isoformat()
    if untouched in index:
        assert index[untouched]["stored"] is False


def test_the_days_index_never_offers_the_future(client, sync_service):
    body = client.get("/api/days").json()
    today = sync_service.today().isoformat()
    assert all(row["date"] <= today for row in body["days"])
    assert body["days"][0]["isToday"] is True


def test_yesterday_and_the_day_route_agree(client, sync_service):
    yesterday = sync_service.yesterday().iso_date
    from_alias = client.get("/api/yesterday").json()
    from_day = client.get(f"/api/day/{yesterday}").json()
    assert from_alias["date"] == from_day["date"] == yesterday


async def test_sync_accepts_an_explicit_day(sync_service):
    day = date(2025, 6, 4)
    timeline = await sync_service.sync(force_refresh=True, day=day)
    assert timeline.date == day.isoformat()
    assert timeline.summary.date_processed == day.isoformat()


async def test_a_stored_day_is_served_from_cache(sync_service):
    day = sync_service.today() - timedelta(days=6)
    first = await sync_service.sync(force_refresh=True, day=day)
    again = await sync_service.get_or_sync(day=day)
    assert again.generated_at == first.generated_at


async def test_a_day_synced_before_it_ended_is_refetched(sync_service, repository):
    """The snapshot of a day taken while it was still today is incomplete.

    Serving it forever is what makes the morning after show a day that stops at
    breakfast, so a stale partial has to be re-fetched rather than cached.
    """
    day = sync_service.today() - timedelta(days=3)
    window = sync_service.window_for(day)
    partial = await sync_service.sync(force_refresh=True, day=day)

    # Rewrite history: pretend this was captured at midday, mid-day.
    stored = repository.get_timeline(day)
    stored.generated_at = window.start + timedelta(hours=12)
    repository.save_timeline(stored)
    assert repository.get_timeline(day).generated_at < window.end

    refreshed = await sync_service.get_or_sync(day=day)
    assert refreshed.generated_at > partial.generated_at, (
        "a day captured before it ended must be re-fetched, not served from cache"
    )
    assert refreshed.generated_at >= window.end


async def test_a_complete_day_is_not_refetched_needlessly(sync_service):
    """The guard must not turn every cache hit into a network call."""
    day = sync_service.today() - timedelta(days=4)
    first = await sync_service.sync(force_refresh=True, day=day)
    for _ in range(3):
        again = await sync_service.get_or_sync(day=day)
        assert again.generated_at == first.generated_at


async def test_today_stays_cached_while_it_is_still_running(sync_service):
    """Today is always a partial snapshot, and must not re-sync on every poll.

    The page polls once a minute and a wearable fetch can spawn an MCP
    subprocess, so treating an in-progress day as stale would hammer the
    sources. Refresh is the way to ask for today's latest hours.
    """
    today = sync_service.today()
    first = await sync_service.sync(force_refresh=True, day=today)
    for _ in range(3):
        again = await sync_service.get_or_sync(day=today)
        assert again.generated_at == first.generated_at


async def test_available_days_counts_only_processed_days(sync_service):
    day = sync_service.today() - timedelta(days=7)
    await sync_service.sync(force_refresh=True, day=day)

    days = {row["date"]: row for row in sync_service.available_days(span_days=14)}
    assert days[day.isoformat()]["stored"] is True
    assert days[day.isoformat()]["eventCount"] > 0


async def test_a_day_across_a_dst_transition_is_still_correct(sync_service):
    """Picking a 23-hour day from the calendar must not assume 24 hours."""
    timeline = await sync_service.sync(force_refresh=True, day=date(2025, 3, 9))
    assert timeline.day_length_hours == pytest.approx(23.0)
    assert timeline.day_start.utcoffset() != timeline.day_end.utcoffset()


def test_the_sleep_highlight_quotes_unclipped_times(client, sync_service):
    """A clipped end paired with the full duration would misdescribe the night."""
    day = (sync_service.today() - timedelta(days=3)).isoformat()
    body = client.get(f"/api/day/{day}").json()

    sleep_lines = [line for line in body["highlights"] if line.startswith("Recorded sleep ran")]
    if not sleep_lines:
        pytest.skip("no main sleep in this generated day")

    line = sleep_lines[0]
    hours = float(line.split(", ")[-1].split(" hours")[0].rstrip(")").split()[-1])
    start_text, rest = line.removeprefix("Recorded sleep ran from ").split(" to ", 1)
    end_text = rest.split(",")[0]

    def minutes(text: str) -> int:
        clock, meridiem = text.split()
        hour, minute = (int(part) for part in clock.split(":"))
        hour = hour % 12 + (12 if meridiem == "PM" else 0)
        return hour * 60 + minute

    span = minutes(end_text) - minutes(start_text)
    if span < 0:
        span += 24 * 60
    # The quoted clock times must match the quoted duration.
    assert abs(span / 60 - hours) < 0.2, line
