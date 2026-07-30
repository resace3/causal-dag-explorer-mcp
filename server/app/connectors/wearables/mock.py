"""Deterministic mock wearable provider.

Given a fixed `MOCK_DATA_SEED` this produces byte-identical output for the same
local date, which makes the timeline reproducible in tests and screenshots.

The shape of the day is intentionally realistic rather than tidy: it contains a
main sleep period that crosses midnight, a short nap, three activity sessions,
an elevated heart-rate stretch inside each workout, a single nightly HRV value,
a skin-temperature curve, and a heart-rate gap where the watch was charging.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .base import (
    ALL_CAPABILITIES,
    ActivityRecord,
    BaseWearableProvider,
    HeartRatePoint,
    HRVPoint,
    ReadinessRecord,
    SleepStage,
    TemperaturePoint,
    WearableCapabilities,
    WearableSleepRecord,
)

DEVICE_NAME = "Mock Band 3"
PROVIDER_NAME = "mock"

# The watch is off the wrist while charging: this becomes a visible gap.
CHARGING_GAP_START = time(15, 5)
CHARGING_GAP_END = time(16, 35)


def _jitter(rng: random.Random, spread: float) -> float:
    return rng.uniform(-spread, spread)


class DayPlan:
    """Everything the mock generates for one local calendar date.

    The Home Assistant mock imports this too, so bed occupancy, lights and
    presence line up with the wearable's sleep and workout records.
    """

    def __init__(self, day: date, tz: ZoneInfo, seed: int) -> None:
        self.day = day
        self.tz = tz
        self.rng = random.Random(seed * 100_003 + day.toordinal())

        def at(d: date, hour: int, minute: int) -> datetime:
            return datetime.combine(d, time(hour, minute), tzinfo=tz)

        previous = day - timedelta(days=1)

        bed_shift = round(_jitter(self.rng, 22))
        wake_shift = round(_jitter(self.rng, 18))
        self.sleep_start = at(previous, 23, 10) + timedelta(minutes=bed_shift)
        self.sleep_end = at(day, 7, 2) + timedelta(minutes=wake_shift)

        nap_shift = round(_jitter(self.rng, 25))
        self.nap_start = at(day, 13, 40) + timedelta(minutes=nap_shift)
        self.nap_end = self.nap_start + timedelta(minutes=25)

        self.activities: list[tuple[datetime, datetime, str, str]] = [
            (
                at(day, 7, 15) + timedelta(minutes=round(_jitter(self.rng, 8))),
                at(day, 8, 0) + timedelta(minutes=round(_jitter(self.rng, 8))),
                "strength_training",
                "Morning workout",
            ),
            (
                at(day, 12, 30) + timedelta(minutes=round(_jitter(self.rng, 12))),
                at(day, 13, 10) + timedelta(minutes=round(_jitter(self.rng, 12))),
                "walk",
                "Walk",
            ),
            (
                at(day, 17, 30) + timedelta(minutes=round(_jitter(self.rng, 10))),
                at(day, 18, 15) + timedelta(minutes=round(_jitter(self.rng, 10))),
                "running",
                "Evening run",
            ),
        ]

        self.gap_start = at(day, CHARGING_GAP_START.hour, CHARGING_GAP_START.minute)
        self.gap_end = at(day, CHARGING_GAP_END.hour, CHARGING_GAP_END.minute)

        self.resting_hr = 55 + self.rng.uniform(-2.5, 2.5)
        self.hrv_rmssd = 58 + self.rng.uniform(-9, 9)
        self.hrv_baseline = 61.5
        self.readiness_base = 74 + self.rng.uniform(-8, 8)
        self.skin_temp_base = 93.4 + self.rng.uniform(-0.5, 0.5)

    # -- helpers ---------------------------------------------------------

    def asleep_at(self, moment: datetime) -> bool:
        if self.sleep_start <= moment < self.sleep_end:
            return True
        return self.nap_start <= moment < self.nap_end

    def activity_at(self, moment: datetime) -> tuple[datetime, datetime, str, str] | None:
        for record in self.activities:
            if record[0] <= moment < record[1]:
                return record
        return None

    def in_charging_gap(self, moment: datetime) -> bool:
        return self.gap_start <= moment < self.gap_end

    def heart_rate_at(self, moment: datetime) -> float:
        activity = self.activity_at(moment)
        if activity is not None:
            start, end, kind, _label = activity
            span = max((end - start).total_seconds(), 1.0)
            progress = (moment - start).total_seconds() / span
            peak = {"strength_training": 148.0, "walk": 104.0, "running": 162.0}[kind]
            # Warm-up ramp, plateau, cool-down.
            shape = math.sin(min(max(progress, 0.0), 1.0) * math.pi) ** 0.55
            value = self.resting_hr + 14 + (peak - self.resting_hr - 14) * shape
            return value + self.rng.uniform(-3.0, 3.0)

        if self.asleep_at(moment):
            span = max((self.sleep_end - self.sleep_start).total_seconds(), 1.0)
            progress = (moment - self.sleep_start).total_seconds() / span
            dip = math.sin(min(max(progress, 0.0), 1.0) * math.pi)
            return self.resting_hr + 4 - 5.0 * dip + self.rng.uniform(-1.6, 1.6)

        minute_of_day = moment.hour * 60 + moment.minute
        diurnal = 8.0 * math.sin((minute_of_day - 300) / 1440 * 2 * math.pi)
        return self.resting_hr + 14 + diurnal + self.rng.uniform(-3.5, 3.5)

    def skin_temperature_at(self, moment: datetime) -> float:
        minute_of_day = moment.hour * 60 + moment.minute
        # Skin temperature rises during sleep and drops through the morning.
        curve = -1.15 * math.cos((minute_of_day + 300) / 1440 * 2 * math.pi)
        boost = 0.55 if self.asleep_at(moment) else 0.0
        if self.activity_at(moment) is not None:
            boost += 0.4
        return self.skin_temp_base + curve + boost + self.rng.uniform(-0.09, 0.09)


class MockWearableProvider(BaseWearableProvider):
    """Implements the full `WearableProvider` protocol with synthetic data."""

    name = PROVIDER_NAME

    def __init__(self, tz: ZoneInfo, seed: int = 42, device: str = DEVICE_NAME) -> None:
        self.tz = tz
        self.seed = seed
        self.device = device
        self._plans: dict[date, DayPlan] = {}

    def plan_for(self, day: date) -> DayPlan:
        if day not in self._plans:
            self._plans[day] = DayPlan(day, self.tz, self.seed)
        return self._plans[day]

    def _plans_covering(self, start: datetime, end: datetime) -> list[DayPlan]:
        first = (start.astimezone(self.tz) - timedelta(days=1)).date()
        last = (end.astimezone(self.tz) + timedelta(days=1)).date()
        days = []
        cursor = first
        while cursor <= last:
            days.append(self.plan_for(cursor))
            cursor += timedelta(days=1)
        return days

    async def get_capabilities(self) -> WearableCapabilities:
        return WearableCapabilities(
            provider=PROVIDER_NAME,
            device=self.device,
            capabilities=list(ALL_CAPABILITIES),
            status="mock_data",
            detail=(
                "Synthetic data generated locally with seed "
                f"{self.seed}. No wearable account is connected."
            ),
        )

    async def get_sleep(self, start: datetime, end: datetime) -> list[WearableSleepRecord]:
        records: list[WearableSleepRecord] = []
        for plan in self._plans_covering(start, end):
            if plan.sleep_end > start and plan.sleep_start < end:
                records.append(self._build_sleep_record(plan))
            if plan.nap_end > start and plan.nap_start < end:
                records.append(
                    WearableSleepRecord(
                        id=f"mock-nap-{plan.day.isoformat()}",
                        start=plan.nap_start,
                        end=plan.nap_end,
                        is_main_sleep=False,
                        efficiency=0.86,
                        time_in_bed_minutes=(plan.nap_end - plan.nap_start).total_seconds() / 60,
                        awake_minutes=3.0,
                        stages=[
                            SleepStage(stage="light", start=plan.nap_start, end=plan.nap_end)
                        ],
                        device=self.device,
                        metadata={"nap": True},
                    )
                )
        records.sort(key=lambda record: record.start)
        return records

    def _build_sleep_record(self, plan: DayPlan) -> WearableSleepRecord:
        rng = random.Random(self.seed * 7 + plan.day.toordinal())
        stages: list[SleepStage] = []
        cursor = plan.sleep_start
        cycle = ["light", "deep", "light", "rem"]
        index = 0
        while cursor < plan.sleep_end:
            stage = cycle[index % len(cycle)]
            minutes = {"light": 35, "deep": 30, "rem": 25}[stage] + rng.randint(-7, 7)
            if index and index % 4 == 0:
                stages.append(
                    SleepStage(
                        stage="awake",
                        start=cursor,
                        end=min(cursor + timedelta(minutes=5), plan.sleep_end),
                    )
                )
                cursor = min(cursor + timedelta(minutes=5), plan.sleep_end)
                if cursor >= plan.sleep_end:
                    break
            stage_end = min(cursor + timedelta(minutes=minutes), plan.sleep_end)
            stages.append(SleepStage(stage=stage, start=cursor, end=stage_end))
            cursor = stage_end
            index += 1

        total_minutes = (plan.sleep_end - plan.sleep_start).total_seconds() / 60
        awake_minutes = sum(
            (stage.end - stage.start).total_seconds() / 60
            for stage in stages
            if stage.stage == "awake"
        )
        efficiency = round((total_minutes - awake_minutes) / total_minutes, 3)
        return WearableSleepRecord(
            id=f"mock-sleep-{plan.day.isoformat()}",
            start=plan.sleep_start,
            end=plan.sleep_end,
            is_main_sleep=True,
            efficiency=efficiency,
            score=round(72 + efficiency * 20 + rng.uniform(-4, 4), 1),
            time_in_bed_minutes=round(total_minutes, 1),
            awake_minutes=round(awake_minutes, 1),
            stages=stages,
            device=self.device,
            metadata={"stage_count": len(stages)},
        )

    async def get_heart_rate(self, start: datetime, end: datetime) -> list[HeartRatePoint]:
        points: list[HeartRatePoint] = []
        step = timedelta(minutes=5)
        cursor = start.astimezone(self.tz).replace(second=0, microsecond=0)
        cursor -= timedelta(minutes=cursor.minute % 5)
        while cursor < end:
            plan = self.plan_for(cursor.date())
            if cursor >= start and not plan.in_charging_gap(cursor):
                activity = plan.activity_at(cursor)
                context = "workout" if activity else ("sleep" if plan.asleep_at(cursor) else None)
                points.append(
                    HeartRatePoint(
                        timestamp=cursor,
                        bpm=round(plan.heart_rate_at(cursor), 1),
                        context=context,
                    )
                )
            cursor += step
        return points

    async def get_hrv(self, start: datetime, end: datetime) -> list[HRVPoint]:
        """One nightly value per main sleep period — never an invented hourly curve."""
        points: list[HRVPoint] = []
        for plan in self._plans_covering(start, end):
            midpoint = plan.sleep_start + (plan.sleep_end - plan.sleep_start) / 2
            if start <= midpoint < end:
                points.append(
                    HRVPoint(
                        timestamp=midpoint,
                        value=round(plan.hrv_rmssd, 1),
                        metric="rmssd",
                        unit="ms",
                        window_start=plan.sleep_start,
                        window_end=plan.sleep_end,
                        baseline=plan.hrv_baseline,
                        baseline_window_days=30,
                    )
                )
        return points

    async def get_activity(self, start: datetime, end: datetime) -> list[ActivityRecord]:
        records: list[ActivityRecord] = []
        for plan in self._plans_covering(start, end):
            rng = random.Random(self.seed * 13 + plan.day.toordinal())
            for activity_start, activity_end, kind, label in plan.activities:
                if activity_end <= start or activity_start >= end:
                    continue
                minutes = (activity_end - activity_start).total_seconds() / 60
                profile = {
                    "strength_training": (0.0, 118, 96, 6.4),
                    "walk": (95.0, 62, 78, 3.6),
                    "running": (165.0, 172, 118, 11.2),
                }[kind]
                steps_per_min, distance_per_min, calories_per_min_scale, _ = profile
                average_hr = {
                    "strength_training": 121,
                    "walk": 98,
                    "running": 148,
                }[kind] + rng.uniform(-6, 6)
                records.append(
                    ActivityRecord(
                        id=f"mock-activity-{plan.day.isoformat()}-{kind}",
                        activity_type=kind,
                        label=label,
                        start=activity_start,
                        end=activity_end,
                        steps=int(steps_per_min * minutes) if steps_per_min else None,
                        distance_meters=round(distance_per_min * minutes, 1)
                        if distance_per_min
                        else None,
                        average_heart_rate=round(average_hr, 1),
                        max_heart_rate=round(average_hr + rng.uniform(12, 26), 1),
                        active_calories=round(calories_per_min_scale * minutes / 10, 1) * 10,
                        device=self.device,
                        detection="workout_record",
                        metadata={"auto_detected": kind != "strength_training"},
                    )
                )
        records.sort(key=lambda record: record.start)
        return records

    async def get_temperature(self, start: datetime, end: datetime) -> list[TemperaturePoint]:
        points: list[TemperaturePoint] = []
        step = timedelta(minutes=15)
        cursor = start.astimezone(self.tz).replace(second=0, microsecond=0)
        cursor -= timedelta(minutes=cursor.minute % 15)
        while cursor < end:
            plan = self.plan_for(cursor.date())
            if cursor >= start and not plan.in_charging_gap(cursor):
                points.append(
                    TemperaturePoint(
                        timestamp=cursor,
                        value=round(plan.skin_temperature_at(cursor), 2),
                        unit="°F",
                        measurement="skin_temperature",
                    )
                )
            cursor += step
        return points

    async def get_readiness(self, start: datetime, end: datetime) -> list[ReadinessRecord]:
        records: list[ReadinessRecord] = []
        for plan in self._plans_covering(start, end):
            rng = random.Random(self.seed * 29 + plan.day.toordinal())
            for hour in range(0, 24, 3):
                stamp = datetime.combine(plan.day, time(hour, 0), tzinfo=self.tz)
                if not (start <= stamp < end):
                    continue
                # Highest after sleep, decaying with time awake, dented by hard efforts.
                hours_awake = max(0.0, (stamp - plan.sleep_end).total_seconds() / 3600)
                score = plan.readiness_base + 14 - min(hours_awake, 16) * 1.35
                for activity_start, _activity_end, kind, _label in plan.activities:
                    if stamp > activity_start and kind == "running":
                        score -= 6
                score += rng.uniform(-2.5, 2.5)
                records.append(
                    ReadinessRecord(
                        timestamp=stamp,
                        score=round(max(1.0, min(99.0, score)), 1),
                        metric="readiness_score",
                        scale_min=0,
                        scale_max=100,
                        contributors={
                            "resting_heart_rate": round(plan.resting_hr, 1),
                            "hrv_rmssd": round(plan.hrv_rmssd, 1),
                            "prior_sleep_hours": round(
                                (plan.sleep_end - plan.sleep_start).total_seconds() / 3600, 2
                            ),
                        },
                        origin="derived",
                    )
                )
        records.sort(key=lambda record: record.timestamp)
        return records
