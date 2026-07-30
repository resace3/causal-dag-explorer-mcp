"""Data-source status reported to the sidebar and the `get_data_sources` tool.

Every source is an MCP integration. The sidebar lists the MCP servers the
timeline reads from — not internal abstractions — so what you see on screen
matches what you configured in your MCP client.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .timeline import CamelModel

SourceStatus = Literal["connected", "disconnected", "syncing", "error", "mock_data"]

#: How the timeline actually reaches the source behind an MCP integration.
Transport = Literal["mcp", "rest", "mock", "file"]


class DataSource(CamelModel):
    id: str
    name: str
    status: SourceStatus

    mcp_server: str | None = None
    """The MCP server this source corresponds to, as named in your MCP client."""

    transport: Transport = "mcp"
    """How data is fetched. `mcp` spawns the server; `rest` calls the same
    underlying instance directly. Shown in the UI so the route is never
    implied rather than stated."""

    provider: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    detail: str | None = None
    """Human-readable, actionable explanation of the current status."""

    last_sync: datetime | None = None
    entity_count: int | None = None
    has_data: bool = True
    """False when the source answered but had nothing for the displayed day."""


class DataSourceReport(CamelModel):
    sources: list[DataSource] = Field(default_factory=list)
    mock_data: bool = False
    checked_at: datetime | None = None
