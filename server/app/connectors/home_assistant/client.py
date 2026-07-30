"""Minimal Home Assistant REST client.

Only the two read-only endpoints the timeline needs are implemented:
`GET /api/` (reachability) and `GET /api/history/period/...` (state history).
The token is read from the environment and never logged or returned by the API.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class HomeAssistantError(RuntimeError):
    """Base class for connector failures that must reach the UI verbatim."""

    def __init__(self, message: str, *, kind: str = "error") -> None:
        super().__init__(message)
        self.kind = kind


class HomeAssistantAuthError(HomeAssistantError):
    def __init__(self, message: str) -> None:
        super().__init__(message, kind="auth")


class HomeAssistantUnreachableError(HomeAssistantError):
    def __init__(self, message: str) -> None:
        super().__init__(message, kind="unreachable")


class HomeAssistantRateLimitError(HomeAssistantError):
    def __init__(self, message: str) -> None:
        super().__init__(message, kind="rate_limit")


class HomeAssistantClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 15.0,
        verify_ssl: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            timeout=self._timeout,
            verify=self._verify_ssl,
            transport=self._transport,
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise HomeAssistantAuthError(
                "Home Assistant rejected the access token (HTTP "
                f"{response.status_code}). Create a new long-lived token in your "
                "Home Assistant profile and set HOME_ASSISTANT_TOKEN."
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "a few")
            raise HomeAssistantRateLimitError(
                f"Home Assistant is rate limiting requests. Retry after {retry_after} seconds."
            )
        if response.status_code >= 400:
            raise HomeAssistantError(
                f"Home Assistant returned HTTP {response.status_code} for {response.request.url.path}."
            )

    async def ping(self) -> str:
        """Return the API greeting, or raise a specific connector error."""
        try:
            async with self._client() as client:
                response = await client.get("/api/")
                self._raise_for_status(response)
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise HomeAssistantUnreachableError(
                f"Home Assistant did not respond within {self._timeout:.0f}s at {self.base_url}."
            ) from exc
        except httpx.HTTPError as exc:
            raise HomeAssistantUnreachableError(
                f"Home Assistant could not be reached at {self.base_url}. "
                "Check HOME_ASSISTANT_URL and that the instance is running."
            ) from exc
        return str(payload.get("message", "ok"))

    async def get_history(
        self,
        entity_ids: list[str],
        start: datetime,
        end: datetime,
    ) -> list[list[dict[str, Any]]]:
        """State history for `entity_ids` over [start, end).

        Returns Home Assistant's native shape: one list of state dicts per entity.
        """
        if not entity_ids:
            return []
        params = {
            "filter_entity_id": ",".join(entity_ids),
            "end_time": end.isoformat(),
            "minimal_response": "false",
            "significant_changes_only": "false",
        }
        path = f"/api/history/period/{start.isoformat()}"
        try:
            async with self._client() as client:
                response = await client.get(path, params=params)
                self._raise_for_status(response)
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise HomeAssistantUnreachableError(
                f"Home Assistant history request timed out after {self._timeout:.0f}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise HomeAssistantUnreachableError(
                f"Home Assistant could not be reached at {self.base_url} while reading history."
            ) from exc

        if not isinstance(payload, list):
            raise HomeAssistantError("Unexpected history payload from Home Assistant.")
        return [group for group in payload if isinstance(group, list)]
