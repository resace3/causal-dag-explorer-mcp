"""Raw records: the untouched evidence behind every derived feature."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from pydantic import Field

from .timeline import CamelModel


class RawRecord(CamelModel):
    """One observation exactly as the connector received it."""

    id: str
    source: str
    """`home_assistant`, `wearable:mock`, ..."""
    stream: str
    """Logical stream name: `illuminance`, `heart_rate`, `sleep`, ..."""
    entity_id: str | None = None
    device: str | None = None
    timestamp: datetime
    end_timestamp: datetime | None = None
    value: float | str | None = None
    unit: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def make_id(source: str, stream: str, key: str) -> str:
        digest = hashlib.sha1(f"{source}|{stream}|{key}".encode()).hexdigest()[:16]
        return f"raw_{stream}_{digest}"


class NormalizedSample(CamelModel):
    """A numeric sample on a continuous stream, after unit/None cleanup."""

    raw_record_id: str
    stream: str
    source: str
    entity_id: str | None = None
    device: str | None = None
    timestamp: datetime
    value: float
    unit: str | None = None
    quality: float | None = None


class NormalizedState(CamelModel):
    """A categorical state that holds until the next change."""

    raw_record_ids: list[str] = Field(default_factory=list)
    stream: str
    source: str
    entity_id: str | None = None
    device: str | None = None
    start_time: datetime
    end_time: datetime
    state: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class NormalizedRecords(CamelModel):
    """Everything one sync produced, before feature engineering."""

    samples: list[NormalizedSample] = Field(default_factory=list)
    states: list[NormalizedState] = Field(default_factory=list)
    unavailable: list[NormalizedState] = Field(default_factory=list)
    """Periods a numeric sensor explicitly reported as unavailable.

    Distinct from mere silence: an `unavailable` state is *known* missing data
    and is always shown as a gap, however brief.
    """

    raw_records: list[RawRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def samples_for(self, stream: str) -> list[NormalizedSample]:
        return [sample for sample in self.samples if sample.stream == stream]

    def states_for(self, stream: str) -> list[NormalizedState]:
        return [state for state in self.states if state.stream == stream]

    def raw_for(self, stream: str) -> list[RawRecord]:
        return [record for record in self.raw_records if record.stream == stream]

    def unavailable_for(self, stream: str) -> list[NormalizedState]:
        return [period for period in self.unavailable if period.stream == stream]
