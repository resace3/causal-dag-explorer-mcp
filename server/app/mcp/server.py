"""MCP server exposing the Yesterday timeline as tools.

The tools deliberately do not stream the full dataset through the model: the
localhost frontend fetches processed data straight from the local API. Tools
return compact summaries plus the URL, and `get_yesterday_timeline` supports
lane filtering and downsampling for the cases where the data really is needed.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

try:  # MCP Python SDK >= 2.0
    from mcp.server import MCPServer as _Server
except ImportError:  # pragma: no cover - SDK 1.x compatibility
    from mcp.server.fastmcp import FastMCP as _Server

from ..config.settings import get_settings
from . import process

logger = logging.getLogger(__name__)

mcp = _Server(
    "yesterday-timeline",
    instructions=(
        "Reconstructs the user's previous local calendar day from Home Assistant and "
        "wearable data and renders it as an hour-by-hour swimlane timeline in a local "
        "web app. Call launch_yesterday_timeline to start the app and get its URL. "
        "This version visualizes and describes timing only; it does not infer causal "
        "effects and does not recommend interventions."
    ),
)

REQUEST_TIMEOUT = 120.0


def _base_url() -> str:
    return get_settings().api_base_url


async def _request(method: str, path: str, **kwargs: Any) -> Any:
    process.ensure_backend()
    url = f"{_base_url()}{path}"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.request(method, url, **kwargs)
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = {"error": {"message": response.text[:400]}}
        return {"ok": False, "statusCode": response.status_code, **detail}
    return response.json()


def _summarize(timeline: dict[str, Any]) -> dict[str, Any]:
    """A compact description of a timeline payload, safe to hand to a model."""
    lanes = timeline.get("lanes", [])
    summary = timeline.get("summary", {})
    return {
        "date": timeline.get("date"),
        "localTimezone": timeline.get("localTimezone"),
        "dayStart": timeline.get("dayStart"),
        "dayEnd": timeline.get("dayEnd"),
        "dayLengthHours": timeline.get("dayLengthHours"),
        "mockData": timeline.get("mockData"),
        "lanes": [
            {
                "id": lane["id"],
                "label": lane["label"],
                "available": lane["available"],
                "unavailableReason": lane.get("unavailableReason"),
                "eventCount": len(lane.get("events", [])),
                "seriesCount": len(lane.get("series", [])),
                "seriesPointCount": sum(
                    len(series.get("points", [])) for series in lane.get("series", [])
                ),
                "sources": lane.get("sources", []),
            }
            for lane in lanes
        ],
        "coverage": summary.get("coverage", {}).get("overallFraction"),
        "warnings": summary.get("warnings", []),
        "errors": summary.get("errors", []),
        "highlights": timeline.get("highlights", []),
    }


@mcp.tool()
async def launch_yesterday_timeline(use_dev_server: bool = False) -> dict[str, Any]:
    """Start the local backend and frontend if they are not running, and return the URL.

    Idempotent: repeated calls reuse the running servers.

    Args:
        use_dev_server: Force the Vite dev server even when a production build exists.
    """
    try:
        backend = process.ensure_backend()
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}

    try:
        frontend = process.ensure_frontend(prefer_dev_server=use_dev_server)
    except RuntimeError as exc:
        return {
            "status": "partial",
            "backend_url": backend["url"],
            "url": None,
            "error": str(exc),
            "hint": (
                "The API is running and documented at "
                f"{backend['url']}/docs, but the web interface is unavailable."
            ),
        }

    return {
        "status": "running",
        "url": frontend["url"],
        "backend_url": backend["url"],
        "frontend_mode": frontend["mode"],
        "started_backend": backend["started"],
        "started_frontend": frontend["started"],
        "date": backend.get("health", {}).get("yesterday"),
        "local_timezone": backend.get("health", {}).get("localTimezone"),
        "mock_data": backend.get("health", {}).get("mockData"),
    }


@mcp.tool()
async def sync_yesterday_data(force_refresh: bool = False) -> dict[str, Any]:
    """Fetch and process the previous local calendar day from all configured sources.

    Args:
        force_refresh: Re-fetch even when a processed timeline is already cached.
    """
    timeline = await _request(
        "POST", "/api/yesterday/sync", json={"forceRefresh": force_refresh}
    )
    if isinstance(timeline, dict) and timeline.get("ok") is False:
        return timeline

    summary = timeline.get("summary", {})
    coverage = summary.get("coverage", {})
    return {
        "date_processed": summary.get("dateProcessed"),
        "local_timezone": summary.get("localTimezone"),
        "day_length_hours": summary.get("dayLengthHours"),
        "sources_checked": summary.get("sourcesChecked", []),
        "raw_record_count": summary.get("rawRecordCount"),
        "normalized_event_count": summary.get("normalizedEventCount"),
        "derived_feature_count": summary.get("derivedFeatureCount"),
        "series_point_count": summary.get("seriesPointCount"),
        "data_coverage": coverage.get("overallFraction"),
        "coverage_per_lane": coverage.get("perLane", {}),
        "missing_periods": coverage.get("missingPeriods", []),
        "warnings": summary.get("warnings", []),
        "errors": summary.get("errors", []),
        "mock_data": timeline.get("mockData"),
        "url": _base_url(),
    }


@mcp.tool()
async def get_yesterday_timeline(
    lanes: str | None = None,
    sampling_interval_minutes: float | None = None,
    include_raw_metadata: bool = False,
    include_provenance: bool = False,
    summary_only: bool = True,
) -> dict[str, Any]:
    """Return the normalized timeline for the previous day.

    Args:
        lanes: Comma-separated lane ids, e.g. "activity,sleep". Omit for all lanes.
        sampling_interval_minutes: Downsample continuous series to this spacing.
        include_raw_metadata: Include per-event metadata dictionaries.
        include_provenance: Include provenance records.
        summary_only: Return lane counts instead of the full payload (default).
    """
    params: dict[str, Any] = {
        "includeRawMetadata": str(include_raw_metadata).lower(),
        "includeProvenance": str(include_provenance).lower(),
    }
    if lanes:
        params["lanes"] = lanes
    if sampling_interval_minutes:
        params["samplingIntervalMinutes"] = sampling_interval_minutes

    timeline = await _request("GET", "/api/yesterday", params=params)
    if isinstance(timeline, dict) and timeline.get("ok") is False:
        return timeline

    if summary_only:
        return {
            **_summarize(timeline),
            "note": (
                "Lane summary only. Call again with summary_only=false for the full "
                f"payload, or open {_base_url()} to view the timeline."
            ),
        }
    return timeline


@mcp.tool()
async def get_day_timeline(
    date: str,
    lanes: str | None = None,
    summary_only: bool = True,
) -> dict[str, Any]:
    """Return the timeline for one specific local calendar day.

    Args:
        date: The day to reconstruct, as YYYY-MM-DD. Must not be in the future.
        lanes: Comma-separated lane ids, e.g. "activity,sleep". Omit for all.
        summary_only: Return lane counts instead of the full payload (default).
    """
    params: dict[str, Any] = {"includeRawMetadata": "false", "includeProvenance": "false"}
    if lanes:
        params["lanes"] = lanes

    timeline = await _request("GET", f"/api/day/{date}", params=params)
    if isinstance(timeline, dict) and timeline.get("ok") is False:
        return timeline
    if summary_only:
        return {
            **_summarize(timeline),
            "note": f"Lane summary only. Open {_base_url()} and pick {date} to view it.",
        }
    return timeline


@mcp.tool()
async def list_days() -> dict[str, Any]:
    """List the days the calendar can offer, and which already hold data."""
    return await _request("GET", "/api/days")


@mcp.tool()
async def get_expected_dag(
    outcome: str,
    exposure: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Build the expected causal graph for an outcome, as a hypothesis.

    This proposes structure; it never estimates an effect. Every edge is an
    assumption drawn from published physiology, and the response says so. Use it
    to see which confounders are unmeasurable with the connected sources, which
    mediators would absorb the effect if adjusted for, and which colliders must
    not be conditioned on.

    The `timeline` field anchors the graph to the day's clock: each occurrence
    is a real recorded moment, each link joins a cause to the first effect that
    followed it, and `unplacedEdges` lists the assumed links the day could not
    position. A missing link there means the day could not place it, never that
    the link was tested and rejected.

    Args:
        outcome: Variable id to explain, e.g. "sleep_duration".
        exposure: Optional variable id whose effect is in question.
        date: Which day's data availability to annotate against (YYYY-MM-DD).
    """
    body: dict[str, Any] = {"outcome": outcome}
    if exposure:
        body["exposure"] = exposure
    if date:
        body["day"] = date
    return await _request("POST", "/api/dag", json=body)


@mcp.tool()
async def list_causal_variables(date: str | None = None) -> dict[str, Any]:
    """List variables usable as an exposure or outcome, and whether each was observed.

    Args:
        date: Which day to check observation against (YYYY-MM-DD). Defaults to yesterday.
    """
    path = f"/api/dag/variables{f'?day={date}' if date else ''}"
    return await _request("GET", path)


@mcp.tool()
async def add_timeline_row(description: str, date: str | None = None) -> dict[str, Any]:
    """Add a row to the expanded timeline, described in words.

    The row is derived from streams the day already holds — for example
    "heart rate above 100", "step rate over 60", "sleep". A threshold produces
    intervals where the condition held; naming a stream alone plots it as it was
    recorded. The row is stored and appears on every day thereafter.

    The request is resolved against the streams that day actually has, so this
    reports back what it understood. If it could not be read, the response says
    why and lists the available streams rather than guessing.

    Args:
        description: What the row should show, e.g. "heart rate above 100".
        date: Which day to resolve stream names against (YYYY-MM-DD).
    """
    body: dict[str, Any] = {"prompt": description}
    if date:
        body["day"] = date
    return await _request("POST", "/api/rows", json=body)


@mcp.tool()
async def list_timeline_rows() -> dict[str, Any]:
    """List the custom rows added to the timeline, with the request behind each."""
    return await _request("GET", "/api/rows")


@mcp.tool()
async def remove_timeline_row(row_id: str) -> dict[str, Any]:
    """Remove a custom row.

    Args:
        row_id: An id from list_timeline_rows, e.g. "custom_heart_rate_above_100_bpm".
    """
    return await _request("DELETE", f"/api/rows/{row_id}")


@mcp.tool()
async def get_data_sources() -> dict[str, Any]:
    """Return the status and capabilities of every configured data source."""
    report = await _request("GET", "/api/data-sources")
    if isinstance(report, dict) and report.get("ok") is False:
        return report

    result: dict[str, Any] = {"mock_data": report.get("mockData")}
    for source in report.get("sources", []):
        result[source["id"]] = {
            "status": source["status"],
            "mcp_server": source.get("mcpServer"),
            "transport": source.get("transport"),
            "provider": source.get("provider"),
            "capabilities": source.get("capabilities", []),
            "detail": source.get("detail"),
            "entity_count": source.get("entityCount"),
            "has_data": source.get("hasData"),
            "last_sync": source.get("lastSync"),
        }
    return result


@mcp.tool()
async def get_event_details(event_id: str) -> dict[str, Any]:
    """Return complete metadata and provenance for one timeline event.

    Args:
        event_id: An event id from get_yesterday_timeline, e.g. "activity_mock-activity-...".
    """
    return await _request("GET", f"/api/events/{event_id}")


@mcp.tool()
async def refresh_timeline() -> dict[str, Any]:
    """Re-run synchronization and feature engineering, then report what changed.

    The open web page picks the new data up on its next poll, or immediately via
    its Refresh control.
    """
    result = await sync_yesterday_data(force_refresh=True)
    if isinstance(result, dict) and result.get("ok") is False:
        return result
    return {
        **result,
        "message": (
            "Timeline rebuilt. The web interface reloads it automatically within "
            "60 seconds, or immediately when Refresh is used."
        ),
    }


@mcp.tool()
async def open_timeline() -> dict[str, Any]:
    """Open the timeline in the default browser, or return the URL if that is not possible."""
    try:
        backend = process.ensure_backend()
        frontend = process.ensure_frontend()
        url = frontend["url"]
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}

    opened, message = process.open_in_browser(url)
    return {
        "status": "running",
        "url": url,
        "backend_url": backend["url"],
        "opened_browser": opened,
        "message": message,
    }


def main() -> None:
    """Console entry point: `yesterday-timeline-mcp`."""
    logging.basicConfig(level=logging.WARNING)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
