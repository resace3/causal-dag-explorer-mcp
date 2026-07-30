"""Shared input bundle passed to every feature-engineering rule."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..config.schema import FeatureEngineeringConfig
from ..connectors.wearables.connector import WearablePayload
from ..models.raw import NormalizedRecords
from ..models.timeline import TimelineEvent
from ..services.day import DayWindow


@dataclass(frozen=True)
class Baseline:
    """A personal reference range, never a clinical one.

    `source` records whether this came from stored history or only from the day
    being displayed, so the details panel can say which.
    """

    stream: str
    mean: float
    sd: float
    sample_count: int
    days: int
    source: str

    def z_score(self, value: float) -> float | None:
        if self.sd <= 0:
            return None
        return (value - self.mean) / self.sd

    def describe(self) -> str:
        if self.source == "stored_history":
            return f"{self.days}-day personal baseline ({self.sample_count} stored samples)"
        return f"personal baseline from the displayed day only ({self.sample_count} samples)"


@dataclass
class RuleContext:
    window: DayWindow
    """The local calendar day being reconstructed."""

    fetch_start: datetime
    fetch_end: datetime
    """The wider window fetched so intervals crossing midnight are complete."""

    tz: ZoneInfo
    config: FeatureEngineeringConfig
    normalized: NormalizedRecords
    wearable: WearablePayload
    home_assistant_available: bool = True
    baselines: dict[str, Baseline] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def max_gap(self) -> timedelta:
        return timedelta(minutes=self.config.data_gap.max_gap_minutes)

    @property
    def stale_gap(self) -> timedelta:
        """Gap threshold for sources that report changes rather than samples.

        Home Assistant only writes a row when a value changes, so a quiet sensor
        is steady, not missing. Use this instead of `max_gap` for HA streams.
        """
        return timedelta(minutes=self.config.data_gap.stale_after_minutes)

    def clip_to_day(
        self, start: datetime, end: datetime
    ) -> tuple[datetime, datetime, bool, bool] | None:
        """Clip an interval to the visible day.

        Returns `(start, end, continues_before, continues_after)`, or None when
        the interval does not intersect the day at all. Full timestamps are kept
        by callers for the details panel.
        """
        clipped = self.window.clip(start, end)
        if clipped is None:
            return None
        clipped_start, clipped_end = clipped
        return (
            clipped_start,
            clipped_end,
            start < self.window.start,
            end > self.window.end,
        )


def sort_events(events: list[TimelineEvent]) -> list[TimelineEvent]:
    return sorted(events, key=lambda event: (event.start_time, event.label))
