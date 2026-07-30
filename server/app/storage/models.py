"""SQLite tables. All data stays on this machine.

Nothing here stores credentials. Raw records are kept so the details panel can
show the evidence behind a derived feature, and so personal baselines can span
more than one day. `make clean-data` (or `DELETE /api/cache`) removes the file.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class RawRecordRow(SQLModel, table=True):
    __tablename__ = "raw_records"

    id: str = Field(primary_key=True)
    day: str = Field(index=True)
    source: str = Field(index=True)
    stream: str = Field(index=True)
    entity_id: str | None = Field(default=None, index=True)
    device: str | None = None
    timestamp: datetime = Field(index=True)
    end_timestamp: datetime | None = None
    value_number: float | None = None
    value_text: str | None = None
    unit: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class TimelineEventRow(SQLModel, table=True):
    __tablename__ = "timeline_events"

    id: str = Field(primary_key=True)
    day: str = Field(index=True)
    lane_id: str = Field(index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class DayTimelineRow(SQLModel, table=True):
    __tablename__ = "day_timelines"

    day: str = Field(primary_key=True)
    generated_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class SyncRunRow(SQLModel, table=True):
    __tablename__ = "sync_runs"

    id: int | None = Field(default=None, primary_key=True)
    day: str = Field(index=True)
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "running"
    summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class LaneConfigRow(SQLModel, table=True):
    __tablename__ = "lane_config"

    lane_id: str = Field(primary_key=True)
    visible: bool = True
    updated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


Index("ix_raw_records_day_stream", RawRecordRow.day, RawRecordRow.stream)
