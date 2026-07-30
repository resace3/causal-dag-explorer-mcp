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


class CausalEdgeOverrideRow(SQLModel, table=True):
    """A user's edit to the causal knowledge base.

    Edits are stored as overrides rather than by rewriting `knowledge.py`, so
    the published priors stay intact and auditable: at any point you can see
    which arrows are the literature's and which are yours. `action` is "add"
    for an arrow the user drew, "remove" for a built-in one they rejected.
    """

    __tablename__ = "causal_edge_overrides"

    source: str = Field(primary_key=True)
    target: str = Field(primary_key=True)
    action: str = "add"
    rationale: str = ""
    strength: str = "plausible"
    lag: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class CustomLaneRow(SQLModel, table=True):
    """A row someone asked for, stored as a resolved definition.

    The original request is kept alongside the definition so the row can always
    explain itself, and so a future reader can see what was asked for rather
    than only what the app made of it.
    """

    __tablename__ = "custom_lanes"

    id: str = Field(primary_key=True)
    label: str
    prompt: str
    spec: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    position: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


Index("ix_raw_records_day_stream", RawRecordRow.day, RawRecordRow.stream)
