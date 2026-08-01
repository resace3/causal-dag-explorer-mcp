"""What every connector hands back to the sync service.

Shared so that a second connector does not have to import from the first, and
so partial failure has one shape: a source that could not be read contributes a
status, a specific message and zero records, and the day is still reconstructed
from whatever else answered.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.raw import RawRecord
from ..models.sources import SourceStatus


@dataclass
class ConnectorResult:
    records: list[RawRecord] = field(default_factory=list)
    status: SourceStatus = "disconnected"
    detail: str | None = None
    capabilities: list[str] = field(default_factory=list)
    entity_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
