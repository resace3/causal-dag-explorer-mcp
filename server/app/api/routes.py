"""Local API consumed by the React frontend and the MCP tools."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, status

from ..causal.dag import build_dag, observed_variables
from ..causal.edits import (
    CausalEditError,
    describe,
    effective_edges,
    suppressed_edges,
    user_strength,
    validate_addition,
)
from ..causal.grounding import ground
from ..causal.knowledge import EDGES as KNOWLEDGE_EDGES, VARIABLES
from ..config.loader import get_config, resolve_timezone
from ..config.settings import get_settings
from ..connectors.wearables.registry import available_providers
from ..models.sources import DataSourceReport
from ..models.timeline import DayTimeline
from ..services.projection import project
from ..services.sync import SyncService
from ..storage.repository import Repository
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["yesterday"])

_repository: Repository | None = None
_sync_service: SyncService | None = None


def configure(repository: Repository, sync_service: SyncService) -> None:
    """Wire singletons created during app startup."""
    global _repository, _sync_service
    _repository = repository
    _sync_service = sync_service


def get_repository() -> Repository:
    if _repository is None:  # pragma: no cover - guarded by app startup
        raise ApiError("not_ready", "Storage is not initialised yet.", status_code=503)
    return _repository


def get_sync_service() -> SyncService:
    if _sync_service is None:  # pragma: no cover - guarded by app startup
        raise ApiError("not_ready", "The sync service is not initialised yet.", status_code=503)
    return _sync_service


RepositoryDep = Annotated[Repository, Depends(get_repository)]
SyncDep = Annotated[SyncService, Depends(get_sync_service)]


@router.get("/health", summary="Liveness and build information")
async def health(sync: SyncDep) -> dict[str, Any]:
    settings = get_settings()
    window = sync.yesterday()
    return {
        "status": "ok",
        "version": "0.1.0",
        "localTimezone": sync.tz.key,
        "yesterday": window.iso_date,
        "mockData": settings.use_mock_data,
        "serverTime": datetime.now().astimezone().isoformat(),
    }


@router.get("/config", summary="Non-secret configuration the frontend needs")
async def read_config(sync: SyncDep) -> dict[str, Any]:
    settings = get_settings()
    config = get_config()
    window = sync.yesterday()
    light = config.feature_engineering.light_category
    return {
        "localTimezone": resolve_timezone(config).key,
        "yesterday": window.iso_date,
        "dayStart": window.start.isoformat(),
        "dayEnd": window.end.isoformat(),
        "dayLengthHours": round(window.length_hours, 2),
        "mockData": settings.use_mock_data,
        "mockSeed": settings.mock_data_seed if settings.use_mock_data else None,
        "wearableProvider": "mock" if settings.use_mock_data else config.wearable.provider,
        "availableWearableProviders": available_providers(),
        "homeAssistantConfigured": bool(settings.home_assistant_url),
        "configPath": str(settings.resolved_config_path()),
        "lightThresholds": {
            name: {"minLux": band.min_lux, "maxLux": band.max_lux}
            for name, band in light.thresholds.items()
        },
        "dataDirectory": str(settings.data_dir),
    }


@router.get("/data-sources", response_model=DataSourceReport, summary="Source status")
async def data_sources(sync: SyncDep) -> DataSourceReport:
    return await sync.data_sources()


@router.get("/yesterday", response_model=DayTimeline, summary="Yesterday's timeline")
async def yesterday(
    sync: SyncDep,
    lanes: Annotated[
        str | None, Query(description="Comma-separated lane ids to include")
    ] = None,
    sampling_interval_minutes: Annotated[
        float | None, Query(ge=0, le=180, alias="samplingIntervalMinutes")
    ] = None,
    include_raw_metadata: Annotated[bool, Query(alias="includeRawMetadata")] = True,
    include_provenance: Annotated[bool, Query(alias="includeProvenance")] = True,
) -> DayTimeline:
    timeline = await sync.get_or_sync()
    return project(
        timeline,
        lanes=lanes.split(",") if lanes else None,
        sampling_interval_minutes=sampling_interval_minutes,
        include_raw_metadata=include_raw_metadata,
        include_provenance=include_provenance,
    )


@router.post(
    "/yesterday/sync",
    response_model=DayTimeline,
    summary="Re-fetch and re-process the previous day",
)
async def sync_yesterday(
    sync: SyncDep,
    force_refresh: Annotated[bool, Body(embed=True, alias="forceRefresh")] = True,
) -> DayTimeline:
    return await sync.sync(force_refresh=force_refresh)


def _parse_day(value: str, sync: SyncService) -> date:
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ApiError(
            "invalid_date",
            f"'{value}' is not a valid date. Use YYYY-MM-DD, for example 2026-07-27.",
        ) from None
    if day > sync.today():
        raise ApiError(
            "future_date",
            f"{day.isoformat()} has not happened yet in {sync.tz.key}.",
            hint="Pick today or an earlier day.",
        )
    return day


@router.get("/days", summary="Days the calendar can offer, and which hold data")
async def days(
    sync: SyncDep,
    span: Annotated[int, Query(ge=1, le=400, description="How many days back to list")] = 45,
) -> dict[str, Any]:
    return {
        "localTimezone": sync.tz.key,
        "today": sync.today().isoformat(),
        "yesterday": sync.yesterday().iso_date,
        "days": sync.available_days(span_days=span),
    }


@router.get("/day/{day}", response_model=DayTimeline, summary="One local calendar day")
async def day_timeline(
    day: str,
    sync: SyncDep,
    lanes: Annotated[str | None, Query(description="Comma-separated lane ids")] = None,
    sampling_interval_minutes: Annotated[
        float | None, Query(ge=0, le=180, alias="samplingIntervalMinutes")
    ] = None,
    include_raw_metadata: Annotated[bool, Query(alias="includeRawMetadata")] = True,
    include_provenance: Annotated[bool, Query(alias="includeProvenance")] = True,
) -> DayTimeline:
    timeline = await sync.get_or_sync(day=_parse_day(day, sync))
    return project(
        timeline,
        lanes=lanes.split(",") if lanes else None,
        sampling_interval_minutes=sampling_interval_minutes,
        include_raw_metadata=include_raw_metadata,
        include_provenance=include_provenance,
    )


@router.post(
    "/day/{day}/sync",
    response_model=DayTimeline,
    summary="Re-fetch and re-process one local calendar day",
)
async def sync_day(
    day: str,
    sync: SyncDep,
    force_refresh: Annotated[bool, Body(embed=True, alias="forceRefresh")] = True,
) -> DayTimeline:
    return await sync.sync(force_refresh=force_refresh, day=_parse_day(day, sync))


@router.get("/dag/variables", summary="Variables available for a causal question")
async def dag_variables(sync: SyncDep, day: Annotated[str | None, Query()] = None) -> dict[str, Any]:
    """List candidate exposures and outcomes, and whether each was observed."""
    target = _parse_day(day, sync) if day else sync.yesterday().day
    timeline = sync.repository.get_timeline(target)
    available = {lane.id for lane in timeline.lanes if lane.available} if timeline else set()
    observed = observed_variables(available)

    return {
        "date": target.isoformat(),
        "variables": [
            {
                "id": variable.id,
                "label": variable.label,
                "description": variable.description,
                "measured": variable.measured,
                "lane": variable.lane,
                "unit": variable.unit,
                "observed": variable.id in observed,
            }
            for variable in sorted(VARIABLES.values(), key=lambda item: item.label)
        ],
    }


@router.post("/dag", summary="Build an expected causal graph (a hypothesis, not an estimate)")
async def causal_dag(
    sync: SyncDep,
    outcome: Annotated[str, Body(embed=True)],
    exposure: Annotated[str | None, Body(embed=True)] = None,
    day: Annotated[str | None, Body(embed=True)] = None,
) -> dict[str, Any]:
    target = _parse_day(day, sync) if day else sync.yesterday().day
    timeline = sync.repository.get_timeline(target)
    available = {lane.id for lane in timeline.lanes if lane.available} if timeline else set()

    edges = effective_edges(sync.repository.get_edge_overrides())
    try:
        dag = build_dag(outcome, exposure or None, observed_variables(available), edges=edges)
    except ValueError as exc:
        raise ApiError(
            "invalid_causal_question",
            str(exc),
            hint="Call GET /api/dag/variables for the list of known variables.",
        ) from None

    # Anchoring the graph to the day's clock is what turns it from an abstract
    # diagram into something checkable against what was actually recorded.
    placed = ground(dag, timeline).to_dict() if timeline is not None else None

    return {"date": target.isoformat(), **dag.to_dict(), "timeline": placed}


@router.get("/dag/edges", summary="Every causal edge in the model, with its origin")
async def list_causal_edges(repository: RepositoryDep) -> dict[str, Any]:
    overrides = repository.get_edge_overrides()
    edges = effective_edges(overrides)
    return {
        "edges": describe(edges),
        "suppressed": [item.to_dict() for item in suppressed_edges(overrides)],
        "note": (
            "Edges marked 'knowledge_base' come from published physiology. Edges "
            "marked 'user' were added here. Both are hypotheses; neither is an "
            "estimate from your data."
        ),
    }


@router.post("/dag/edges", summary="Add a causal edge to the model")
async def add_causal_edge(
    repository: RepositoryDep,
    source: Annotated[str, Body(embed=True)],
    target: Annotated[str, Body(embed=True)],
    rationale: Annotated[str | None, Body(embed=True)] = None,
    strength: Annotated[str | None, Body(embed=True)] = None,
) -> dict[str, Any]:
    overrides = repository.get_edge_overrides()
    edges = effective_edges(overrides)
    try:
        normalized = user_strength(strength)
        validate_addition(source, target, edges)
    except CausalEditError as exc:
        raise ApiError(
            "invalid_causal_edge",
            str(exc),
            hint="Call GET /api/dag/variables for the list of known variables.",
        ) from None

    repository.set_edge_override(
        source=source,
        target=target,
        action="add",
        rationale=(rationale or "").strip(),
        strength=normalized,
    )
    return {"added": {"source": source, "target": target}, "estimated": False}


@router.delete("/dag/edges/{source}/{target}", summary="Remove a causal edge from the model")
async def remove_causal_edge(source: str, target: str, repository: RepositoryDep) -> dict[str, Any]:
    overrides = repository.get_edge_overrides()
    added_by_user = any(
        o.source == source and o.target == target and o.action == "add" for o in overrides
    )
    in_knowledge_base = any(
        edge.source == source and edge.target == target for edge in KNOWLEDGE_EDGES
    )

    if added_by_user:
        # The user drew it, so removing it just drops their own override.
        repository.clear_edge_override(source=source, target=target)
        return {"removed": {"source": source, "target": target}, "restorable": False}

    if not in_knowledge_base:
        raise ApiError(
            "unknown_causal_edge",
            f"There is no edge {source} → {target} to remove.",
            status_code=status.HTTP_404_NOT_FOUND,
            hint="Call GET /api/dag/edges for the edges currently in the model.",
        )

    # A published prior is suppressed rather than deleted, so it can come back.
    repository.set_edge_override(source=source, target=target, action="remove")
    return {"removed": {"source": source, "target": target}, "restorable": True}


@router.post("/dag/edges/{source}/{target}/restore", summary="Restore a suppressed edge")
async def restore_causal_edge(
    source: str, target: str, repository: RepositoryDep
) -> dict[str, Any]:
    if not repository.clear_edge_override(source=source, target=target):
        raise ApiError(
            "no_such_override",
            f"No override is stored for {source} → {target}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return {"restored": {"source": source, "target": target}}


@router.get("/events/{event_id}", summary="Full metadata and provenance for one event")
async def event_details(event_id: str, repository: RepositoryDep) -> dict[str, Any]:
    found = repository.get_event(event_id)
    if found is None:
        raise ApiError(
            "event_not_found",
            f"No event with id '{event_id}' is stored for the current day.",
            status_code=status.HTTP_404_NOT_FOUND,
            hint="Run POST /api/yesterday/sync and retry with an id from the response.",
        )
    event, lane_id, day = found
    raw_ids = event.provenance.raw_record_ids if event.provenance else []
    rows = repository.get_raw_records(raw_ids[:50])
    return {
        "event": event.model_dump(mode="json", by_alias=True),
        "laneId": lane_id,
        "date": day,
        "rawRecordCount": len(raw_ids),
        "rawRecords": [
            {
                "id": row.id,
                "source": row.source,
                "stream": row.stream,
                "entityId": row.entity_id,
                "device": row.device,
                "timestamp": row.timestamp.isoformat(),
                "endTimestamp": row.end_timestamp.isoformat() if row.end_timestamp else None,
                "value": row.value_number if row.value_number is not None else row.value_text,
                "unit": row.unit,
            }
            for row in rows
        ],
    }


@router.get("/raw-records/{record_id}", summary="One raw record")
async def raw_record(record_id: str, repository: RepositoryDep) -> dict[str, Any]:
    row = repository.get_raw_record(record_id)
    if row is None:
        raise ApiError(
            "raw_record_not_found",
            f"No raw record with id '{record_id}' is stored.",
            status_code=status.HTTP_404_NOT_FOUND,
            hint="Raw records are retained for 90 days and cleared by `make clean-data`.",
        )
    return {
        "id": row.id,
        "date": row.day,
        "source": row.source,
        "stream": row.stream,
        "entityId": row.entity_id,
        "device": row.device,
        "timestamp": row.timestamp.isoformat(),
        "endTimestamp": row.end_timestamp.isoformat() if row.end_timestamp else None,
        "value": row.value_number if row.value_number is not None else row.value_text,
        "unit": row.unit,
        "attributes": row.attributes,
    }


@router.get("/lane-config", summary="Lane visibility preferences")
async def lane_config(repository: RepositoryDep) -> dict[str, Any]:
    config = get_config()
    stored = repository.get_lane_config()
    merged = {**config.lane_visibility(), **stored}
    return {"lanes": merged, "source": "config.yaml + local overrides"}


@router.patch("/lane-config", summary="Update lane visibility preferences")
async def update_lane_config(
    repository: RepositoryDep,
    lanes: Annotated[dict[str, bool], Body(embed=True)],
) -> dict[str, Any]:
    if not lanes:
        raise ApiError(
            "empty_update",
            "Provide at least one lane id to update, for example {\"lanes\": {\"hrv\": false}}.",
        )
    stored = repository.set_lane_visibility(lanes)
    config = get_config()
    return {"lanes": {**config.lane_visibility(), **stored}, "updated": sorted(lanes)}


@router.delete("/cache", summary="Delete all locally cached data")
async def clear_cache(repository: RepositoryDep) -> dict[str, Any]:
    counts = repository.clear()
    return {"cleared": counts, "message": "Local SQLite cache emptied."}
