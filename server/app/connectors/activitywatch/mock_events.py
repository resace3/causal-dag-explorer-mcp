"""A deterministic computer-use day, so the interface can be explored offline.

Same contract as `home_assistant/mock_states.py`: the same seed always produces
the same day. The shapes match what ActivityWatch's query API returns —
`{"timestamp", "duration", "data"}` — so the connector's reduction and record
building run over mock data exactly as they do over real data, rather than
around it.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

AFK_BUCKET = "aw-watcher-afk_mock"
WINDOW_BUCKET = "aw-watcher-window_mock"
WEB_BUCKET = "aw-watcher-web-mock"

#: (application, plausible window titles). Titles only ever reach a record at
#: detail level `full`, but the mock has to offer them or that level would be
#: untestable against generated data.
APPS = [
    ("code.exe", ["timeline.py — yesterday-timeline", "sync.py — yesterday-timeline"]),
    ("chrome.exe", ["Pull requests", "Docs"]),
    ("slack.exe", ["general", "standup"]),
    ("Terminal", ["pytest", "git log"]),
    ("explorer.exe", ["Downloads"]),
]

SITES = ["github.com", "docs.python.org", "news.ycombinator.com", "mail.google.com"]

#: Local hours a mock day is spent at the machine. Deliberately not the whole
#: day: a computer that is off is not a gap in the data, and the lane has to
#: have somewhere to show that.
SESSIONS = ((9.25, 12.0), (13.5, 17.75), (20.5, 22.25))


def generate_events(
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    seed: int,
) -> list[tuple[str, str, dict[str, Any]]]:
    """`(stream, bucket_id, event)` triples covering `[start, end)`."""
    from .connector import STREAM_AFK, STREAM_WEB, STREAM_WINDOW

    events: list[tuple[str, str, dict[str, Any]]] = []
    day = start.astimezone(tz).date()
    last_day = end.astimezone(tz).date()

    while day <= last_day:
        midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
        rng = random.Random(f"{seed}|{day.isoformat()}")

        for index, (from_hour, to_hour) in enumerate(SESSIONS):
            session_start = midnight + timedelta(hours=from_hour + rng.uniform(-0.4, 0.4))
            session_end = midnight + timedelta(hours=to_hour + rng.uniform(-0.5, 0.5))
            if session_end <= session_start:
                continue

            events.append(
                (
                    STREAM_AFK,
                    AFK_BUCKET,
                    _event(session_start, session_end, {"status": "not-afk"}),
                )
            )
            # The stretch between this session and the next reads as away.
            if index + 1 < len(SESSIONS):
                next_start = midnight + timedelta(hours=SESSIONS[index + 1][0] - 0.4)
                if next_start > session_end:
                    events.append(
                        (
                            STREAM_AFK,
                            AFK_BUCKET,
                            _event(session_end, next_start, {"status": "afk"}),
                        )
                    )

            events.extend(_window_events(session_start, session_end, rng, STREAM_WINDOW, STREAM_WEB))

        day += timedelta(days=1)

    return [
        triple
        for triple in events
        if start <= _timestamp_of(triple) < end
    ]


def _window_events(
    session_start: datetime,
    session_end: datetime,
    rng: random.Random,
    window_stream: str,
    web_stream: str,
) -> list[tuple[str, str, dict[str, Any]]]:
    """Fill one session with application runs, and browsing inside the browser."""
    events: list[tuple[str, str, dict[str, Any]]] = []
    moment = session_start

    while moment < session_end:
        app, titles = APPS[rng.randrange(len(APPS))]
        run_end = min(moment + timedelta(minutes=rng.uniform(3, 34)), session_end)
        if run_end <= moment:
            break
        events.append(
            (
                window_stream,
                WINDOW_BUCKET,
                _event(moment, run_end, {"app": app, "title": titles[rng.randrange(len(titles))]}),
            )
        )

        if app == "chrome.exe":
            tab = moment
            while tab < run_end:
                tab_end = min(tab + timedelta(minutes=rng.uniform(2, 12)), run_end)
                if tab_end <= tab:
                    break
                site = SITES[rng.randrange(len(SITES))]
                events.append(
                    (
                        web_stream,
                        WEB_BUCKET,
                        _event(
                            tab,
                            tab_end,
                            {"url": f"https://{site}/some/path", "title": f"{site} — a page"},
                        ),
                    )
                )
                tab = tab_end

        moment = run_end

    return events


def _event(start: datetime, end: datetime, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": start.isoformat(),
        "duration": (end - start).total_seconds(),
        "data": data,
    }


def _timestamp_of(triple: tuple[str, str, dict[str, Any]]) -> datetime:
    return datetime.fromisoformat(triple[2]["timestamp"])
