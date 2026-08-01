"""SQLite persistence and personal-baseline computation."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import Session, SQLModel, create_engine, select

from ..feature_engineering.context import Baseline
from ..feature_engineering.provenance import mean_and_sd
from ..models.raw import RawRecord
from ..models.timeline import DayTimeline, TimelineEvent
from .models import (
    DayTimelineRow,
    CausalEdgeOverrideRow,
    CustomLaneRow,
    KnownSourceRow,
    LaneConfigRow,
    SourceSelectionRow,
    RawRecordRow,
    SyncRunRow,
    TimelineEventRow,
)

logger = logging.getLogger(__name__)

# Streams that support a personal baseline.
BASELINE_STREAMS = ("heart_rate", "skin_temperature", "hrv", "readiness")

# Days of raw records to keep. Older rows are pruned on each sync.
RETENTION_DAYS = 90


class Repository:
    def __init__(self, database_url: str, path: Path | None = None) -> None:
        self.database_url = database_url
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(database_url, echo=False, connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            yield session

    # -- raw records -----------------------------------------------------

    def save_raw_records(self, day: date, records: list[RawRecord]) -> int:
        if not records:
            return 0
        day_key = day.isoformat()
        with self.session() as session:
            session.exec(delete(RawRecordRow).where(RawRecordRow.day == day_key))
            for record in records:
                value_number = record.value if isinstance(record.value, (int, float)) else None
                value_text = record.value if isinstance(record.value, str) else None
                session.merge(
                    RawRecordRow(
                        id=record.id,
                        day=day_key,
                        source=record.source,
                        stream=record.stream,
                        entity_id=record.entity_id,
                        device=record.device,
                        timestamp=record.timestamp,
                        end_timestamp=record.end_timestamp,
                        value_number=float(value_number) if value_number is not None else None,
                        value_text=value_text,
                        unit=record.unit,
                        attributes=record.attributes,
                    )
                )
            session.commit()
        self._prune(day)
        return len(records)

    def _prune(self, day: date) -> None:
        cutoff = (day - timedelta(days=RETENTION_DAYS)).isoformat()
        with self.session() as session:
            session.exec(delete(RawRecordRow).where(RawRecordRow.day < cutoff))
            session.commit()

    def get_raw_record(self, record_id: str) -> RawRecordRow | None:
        with self.session() as session:
            return session.get(RawRecordRow, record_id)

    def get_raw_records(self, record_ids: list[str]) -> list[RawRecordRow]:
        if not record_ids:
            return []
        with self.session() as session:
            statement = select(RawRecordRow).where(RawRecordRow.id.in_(record_ids))
            return list(session.exec(statement).all())

    # -- baselines -------------------------------------------------------

    def compute_baselines(self, day: date, window_days: int) -> dict[str, Baseline]:
        """Personal baselines from stored history, excluding the day on screen.

        Falls back to nothing when history is too thin; rules then compute a
        same-day baseline and say so in their provenance.
        """
        start = (day - timedelta(days=window_days)).isoformat()
        end = day.isoformat()
        baselines: dict[str, Baseline] = {}

        with self.session() as session:
            for stream in BASELINE_STREAMS:
                statement = select(RawRecordRow).where(
                    RawRecordRow.stream == stream,
                    RawRecordRow.day >= start,
                    RawRecordRow.day < end,
                    RawRecordRow.value_number.is_not(None),
                )
                rows = list(session.exec(statement).all())
                values = [row.value_number for row in rows if row.value_number is not None]
                if len(values) < 30:
                    continue
                days = len({row.day for row in rows})
                mean, sd = mean_and_sd(values)
                baselines[stream] = Baseline(
                    stream=stream,
                    mean=mean,
                    sd=sd,
                    sample_count=len(values),
                    days=days,
                    source="stored_history",
                )
        return baselines

    # -- timelines -------------------------------------------------------

    def save_timeline(self, timeline: DayTimeline) -> None:
        payload = timeline.model_dump(mode="json", by_alias=True)
        with self.session() as session:
            session.merge(
                DayTimelineRow(
                    day=timeline.date,
                    generated_at=timeline.generated_at,
                    payload=payload,
                )
            )
            session.exec(delete(TimelineEventRow).where(TimelineEventRow.day == timeline.date))
            for lane in timeline.lanes:
                for event in lane.events:
                    session.merge(
                        TimelineEventRow(
                            id=event.id,
                            day=timeline.date,
                            lane_id=lane.id,
                            payload=event.model_dump(mode="json", by_alias=True),
                        )
                    )
            session.commit()

    def get_timeline(self, day: date) -> DayTimeline | None:
        with self.session() as session:
            row = session.get(DayTimelineRow, day.isoformat())
            if row is None:
                return None
            return DayTimeline.model_validate(row.payload)

    def stored_days(self) -> list[dict]:
        """Every day that already has a processed timeline, newest first."""
        with self.session() as session:
            rows = session.exec(
                select(DayTimelineRow).order_by(DayTimelineRow.day.desc())
            ).all()

        days: list[dict] = []
        for row in rows:
            payload = row.payload or {}
            summary = payload.get("summary") or {}
            days.append(
                {
                    "date": row.day,
                    "generated_at": row.generated_at,
                    "event_count": summary.get("normalizedEventCount", 0),
                    "coverage": (summary.get("coverage") or {}).get("overallFraction"),
                    "lanes_with_data": sum(
                        1 for lane in payload.get("lanes", []) if lane.get("available")
                    ),
                }
            )
        return days

    def get_event(self, event_id: str) -> tuple[TimelineEvent, str, str] | None:
        """Returns (event, lane_id, day) for a stored event id."""
        with self.session() as session:
            row = session.get(TimelineEventRow, event_id)
            if row is None:
                return None
            return TimelineEvent.model_validate(row.payload), row.lane_id, row.day

    # -- sync runs -------------------------------------------------------

    def start_sync(self, day: date) -> int:
        with self.session() as session:
            row = SyncRunRow(day=day.isoformat(), started_at=datetime.now().astimezone())
            session.add(row)
            session.commit()
            session.refresh(row)
            return int(row.id or 0)

    def finish_sync(self, run_id: int, status: str, summary: dict) -> None:
        with self.session() as session:
            row = session.get(SyncRunRow, run_id)
            if row is None:
                return
            row.status = status
            row.completed_at = datetime.now().astimezone()
            row.summary = summary
            session.add(row)
            session.commit()

    def last_sync(self, day: date | None = None) -> SyncRunRow | None:
        with self.session() as session:
            statement = select(SyncRunRow).order_by(SyncRunRow.started_at.desc())
            if day is not None:
                statement = statement.where(SyncRunRow.day == day.isoformat())
            return session.exec(statement).first()

    # -- lane visibility -------------------------------------------------

    def get_lane_config(self) -> dict[str, bool]:
        with self.session() as session:
            rows = session.exec(select(LaneConfigRow)).all()
            return {row.lane_id: row.visible for row in rows}

    def set_lane_visibility(self, updates: dict[str, bool]) -> dict[str, bool]:
        with self.session() as session:
            for lane_id, visible in updates.items():
                session.merge(
                    LaneConfigRow(
                        lane_id=lane_id,
                        visible=visible,
                        updated_at=datetime.now().astimezone(),
                    )
                )
            session.commit()
        return self.get_lane_config()

    # -- causal edge overrides -------------------------------------------

    def get_edge_overrides(self) -> list[CausalEdgeOverrideRow]:
        with self.session() as session:
            return list(session.exec(select(CausalEdgeOverrideRow)).all())

    def set_edge_override(
        self,
        *,
        source: str,
        target: str,
        action: str,
        rationale: str = "",
        strength: str = "plausible",
        lag: str | None = None,
    ) -> None:
        with self.session() as session:
            session.merge(
                CausalEdgeOverrideRow(
                    source=source,
                    target=target,
                    action=action,
                    rationale=rationale,
                    strength=strength,
                    lag=lag,
                    updated_at=datetime.now().astimezone(),
                )
            )
            session.commit()

    def clear_edge_override(self, *, source: str, target: str) -> bool:
        """Drop an override, restoring whatever the knowledge base says."""
        with self.session() as session:
            row = session.get(CausalEdgeOverrideRow, (source, target))
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- custom rows ------------------------------------------------------

    def get_custom_lanes(self) -> list[CustomLaneRow]:
        with self.session() as session:
            rows = list(session.exec(select(CustomLaneRow)).all())
        return sorted(rows, key=lambda row: (row.position, row.created_at))

    def add_custom_lane(self, row: CustomLaneRow) -> CustomLaneRow:
        with self.session() as session:
            session.merge(row)
            session.commit()
        return row

    def delete_custom_lane(self, lane_id: str) -> bool:
        with self.session() as session:
            row = session.get(CustomLaneRow, lane_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- source selection --------------------------------------------------

    def get_source_selection(self) -> list[str] | None:
        """The chosen sources, or None when the config's own order applies."""
        with self.session() as session:
            row = session.get(SourceSelectionRow, "default")
            return list(row.sources) if row else None

    def set_source_selection(self, sources: list[str], known: list[str] | None = None) -> list[str]:
        """Store the chosen order, and which sources were on offer at the time.

        `known` is what makes a later "this source is not selected" readable: a
        source recorded here and left out was switched off, one that was never
        recorded simply did not exist yet.
        """
        with self.session() as session:
            session.merge(
                SourceSelectionRow(
                    id="default",
                    sources=list(sources),
                    updated_at=datetime.now().astimezone(),
                )
            )
            for source_id in known if known is not None else sources:
                session.merge(KnownSourceRow(id=source_id))
            session.commit()
        return sources

    def known_sources(self) -> set[str]:
        """Sources this install has offered at least once."""
        with self.session() as session:
            return {row.id for row in session.exec(select(KnownSourceRow)).all()}

    # -- maintenance -----------------------------------------------------

    def clear(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self.session() as session:
            for model, name in (
                (RawRecordRow, "raw_records"),
                (TimelineEventRow, "timeline_events"),
                (DayTimelineRow, "day_timelines"),
                (SyncRunRow, "sync_runs"),
            ):
                counts[name] = len(session.exec(select(model)).all())
                session.exec(delete(model))
            session.commit()
        return counts
