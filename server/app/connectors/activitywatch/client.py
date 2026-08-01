"""Minimal ActivityWatch REST client.

ActivityWatch runs a local server on port 5600 with no authentication — it is
reachable only from this machine. Four read-only endpoints are used:
`GET /api/0/info` (reachability), `GET /api/0/buckets/` (which watchers are
running), and `POST /api/0/query/` (the query2 language, which is how AFK
filtering and event flooding are meant to be done).

Nothing here writes: ActivityWatch's REST API can create buckets and post
events, and none of those endpoints are implemented.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ActivityWatchError(RuntimeError):
    """A connector failure that must reach the UI verbatim."""

    def __init__(self, message: str, *, kind: str = "error") -> None:
        super().__init__(message)
        self.kind = kind


class ActivityWatchUnreachableError(ActivityWatchError):
    def __init__(self, message: str) -> None:
        super().__init__(message, kind="unreachable")


class ActivityWatchClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Content-Type": "application/json"},
            timeout=self._timeout,
            transport=self._transport,
        )

    def _unreachable(self, detail: str) -> ActivityWatchUnreachableError:
        return ActivityWatchUnreachableError(
            f"ActivityWatch could not be reached at {self.base_url} ({detail}). "
            "Check that the ActivityWatch app is running, or set ACTIVITYWATCH_URL."
        )

    async def _get(self, path: str) -> Any:
        try:
            async with self._client() as client:
                response = await client.get(path)
                if response.status_code >= 400:
                    raise ActivityWatchError(
                        f"ActivityWatch returned HTTP {response.status_code} for {path}."
                    )
                return response.json()
        except httpx.TimeoutException as exc:
            raise self._unreachable(f"no response within {self._timeout:.0f}s") from exc
        except httpx.HTTPError as exc:
            raise self._unreachable(type(exc).__name__) from exc

    async def info(self) -> dict[str, Any]:
        payload = await self._get("/api/0/info")
        return payload if isinstance(payload, dict) else {}

    async def buckets(self) -> dict[str, dict[str, Any]]:
        """Every bucket, keyed by id. One bucket is one watcher on one host."""
        payload = await self._get("/api/0/buckets/")
        if not isinstance(payload, dict):
            raise ActivityWatchError("Unexpected bucket listing from ActivityWatch.")
        return {key: value for key, value in payload.items() if isinstance(value, dict)}

    async def query(
        self, statements: list[str], start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Run one query2 program over a single time period.

        query2 is the only interface that applies `flood` (which closes the
        sub-second holes between heartbeats) and `filter_period_intersect`
        (which is how "while not away from the keyboard" is expressed). Reading
        the raw event endpoint instead would mean reimplementing both here.
        """
        body = {
            "query": statements,
            "timeperiods": [f"{start.isoformat()}/{end.isoformat()}"],
        }
        try:
            async with self._client() as client:
                response = await client.post("/api/0/query/", json=body)
                if response.status_code >= 400:
                    raise ActivityWatchError(
                        f"ActivityWatch rejected a query (HTTP {response.status_code}): "
                        f"{response.text[:300]}"
                    )
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise self._unreachable(f"query timed out after {self._timeout:.0f}s") from exc
        except httpx.HTTPError as exc:
            raise self._unreachable(type(exc).__name__) from exc

        # One result per time period, and exactly one period is ever sent.
        if not isinstance(payload, list) or not payload:
            return []
        first = payload[0]
        if not isinstance(first, list):
            raise ActivityWatchError("Unexpected query result shape from ActivityWatch.")
        return [event for event in first if isinstance(event, dict)]
