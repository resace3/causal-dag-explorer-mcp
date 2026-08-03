"""Synthetic foreground segments, shaped like the add-on's own payloads.

The mock emits both streams and keeps them *deliberately inconsistent* in the
way the real source is: the per-app daily totals are larger than the sum of the
segments for the same app, because the real totals carry task-root attribution
and the segments do not. A mock where the two agreed would make the rule's
whole reason for keeping them apart untestable.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ...models.raw import RawRecord

SOURCE_ID = "phone_usage"
STREAM_SEGMENT = "phone_segment"
STREAM_APP_DAILY = "phone_app_daily"
STREAM_DAY_SUMMARY = "phone_day_summary"

#: Real package names, so the display-name lookup is exercised rather than
#: bypassed. The last two open links in-app, which is where attribution bites.
MOCK_PACKAGES = (
    "com.zhiliaoapp.musically",
    "com.android.chrome",
    "com.reddit.frontpage",
    "com.google.android.youtube",
    "com.android.launcher3",
    "com.whatsapp",
)

#: How much more the task-root total is than the replayed segments, per app.
#: One for an app that hosts its own browser, one for an app that does not.
TASK_ROOT_UPLIFT = {
    "com.zhiliaoapp.musically": 2.4,
    "com.reddit.frontpage": 1.8,
}


def generate_segments(
    days: list[date],
    tz: ZoneInfo,
    seed: int,
    start: datetime,
    end: datetime,
) -> list[RawRecord]:
    records: list[RawRecord] = []

    for day in days:
        rng = random.Random(seed * 8191 + day.toordinal())
        minutes_by_package: dict[str, float] = {}
        segments: list[tuple[datetime, datetime, str]] = []

        cursor = datetime.combine(day, time(7, 30), tzinfo=tz)
        finish = datetime.combine(day, time(23, 15), tzinfo=tz)
        while cursor < finish:
            gap = timedelta(minutes=rng.randint(4, 55))
            cursor += gap
            if cursor >= finish:
                break
            # One pickup: a couple of apps in a row before the phone goes down.
            for _ in range(rng.randint(1, 4)):
                package = MOCK_PACKAGES[rng.randrange(len(MOCK_PACKAGES))]
                length = timedelta(seconds=rng.randint(15, 900))
                if cursor + length >= finish:
                    break
                segments.append((cursor, cursor + length, package))
                minutes_by_package[package] = (
                    minutes_by_package.get(package, 0.0) + length.total_seconds() / 60
                )
                cursor += length + timedelta(seconds=rng.randint(1, 4))

        for begin, over, package in segments:
            if over <= start or begin >= end:
                continue
            records.append(
                RawRecord(
                    id=RawRecord.make_id(
                        SOURCE_ID, STREAM_SEGMENT, f"{package}|{begin.isoformat()}"
                    ),
                    source=SOURCE_ID,
                    stream=STREAM_SEGMENT,
                    device="phone",
                    timestamp=begin,
                    end_timestamp=over,
                    value=package,
                    unit="seconds",
                    attributes={
                        "package": package,
                        "seconds": (over - begin).total_seconds(),
                        "attribution": "package",
                    },
                )
            )

        stamp = datetime.combine(day, time(0, 0), tzinfo=tz)
        for package, minutes in minutes_by_package.items():
            records.append(
                RawRecord(
                    id=RawRecord.make_id(
                        SOURCE_ID, STREAM_APP_DAILY, f"{day.isoformat()}|{package}"
                    ),
                    source=SOURCE_ID,
                    stream=STREAM_APP_DAILY,
                    device="phone",
                    timestamp=stamp,
                    value=round(minutes * TASK_ROOT_UPLIFT.get(package, 1.0), 1),
                    unit="minutes",
                    attributes={
                        "package": package,
                        "date": day.isoformat(),
                        "attribution": "task_root",
                    },
                )
            )

        screen_minutes = round(sum(minutes_by_package.values()), 1)
        records.append(
            RawRecord(
                id=RawRecord.make_id(SOURCE_ID, STREAM_DAY_SUMMARY, day.isoformat()),
                source=SOURCE_ID,
                stream=STREAM_DAY_SUMMARY,
                device="phone",
                timestamp=stamp,
                value=screen_minutes,
                unit="minutes",
                attributes={
                    "date": day.isoformat(),
                    "screen_on_minutes": screen_minutes,
                    "unlocks": rng.randint(18, 48),
                    "screen_wakes": rng.randint(50, 90),
                    "glances_without_unlock": rng.randint(12, 45),
                    "notification_interruptions": rng.randint(20, 80),
                    "app_switches": rng.randint(180, 520),
                },
            )
        )

    records.sort(key=lambda record: (record.stream, record.timestamp))
    return records
