"""Read-only client for the Phone Usage Collector add-on.

The add-on serves the same query API on two ports: 8099 with a bearer token,
and 8098 through Home Assistant Ingress. This talks to 8099, because Ingress
authenticates with a session cookie minted from an admin credential and the
timeline holds a long-lived token that Supervisor endpoints refuse.

Nothing here writes. The add-on's `POST /v1/events` ingest route exists for the
phone and is not implemented.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class PhoneUsageError(RuntimeError):
    """A connector failure that must reach the UI verbatim."""

    def __init__(self, message: str, *, kind: str = "error") -> None:
        super().__init__(message)
        self.kind = kind


class PhoneUsageUnreachableError(PhoneUsageError):
    def __init__(self, message: str) -> None:
        super().__init__(message, kind="unreachable")


class PhoneUsageClient:
    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _unreachable(self, detail: str) -> PhoneUsageUnreachableError:
        return PhoneUsageUnreachableError(
            f"Could not reach the phone-usage add-on at {self.base_url} ({detail}). "
            "It publishes this port on the Home Assistant host itself, so it is "
            "reachable only from that network — a laptop on mobile data or another "
            "Wi-Fi cannot see it, and the Nabu Casa remote URL does not proxy it. "
            "Check PHONE_USAGE_URL, and that you are on the same network as Home "
            "Assistant."
        )

    def _timeouts(self) -> httpx.Timeout:
        """Give up on *connecting* quickly, but allow a slow answer.

        A day of segments is a large reply and deserves the full budget. Failing
        to reach the host at all does not: off the home network every sync would
        otherwise stall for the whole timeout before saying so, and syncs run on
        a timer.
        """
        return httpx.Timeout(self._timeout, connect=min(3.0, self._timeout))

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=self._timeouts(), transport=self._transport
            ) as client:
                response = await client.get(url, params=params, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise self._unreachable(f"no response within {self._timeout:.0f}s") from exc
        except httpx.HTTPError as exc:
            # The type name, never str(exc): httpx.ConnectError stringifies to
            # nothing at all, which rendered as an empty pair of brackets and
            # read like the message itself was broken.
            raise self._unreachable(type(exc).__name__) from exc

        if response.status_code in (401, 403):
            raise PhoneUsageError(
                "The phone-usage add-on rejected the token. Set PHONE_USAGE_TOKEN in "
                ".env to the add-on's configured `token`."
            )
        if response.status_code >= 400:
            raise PhoneUsageError(
                f"The phone-usage add-on returned {response.status_code} for {path}."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise PhoneUsageError(
                f"The phone-usage add-on returned a non-JSON body for {path}."
            ) from exc

    async def health(self) -> dict[str, Any]:
        payload = await self._get("/v1/health")
        return payload if isinstance(payload, dict) else {}

    async def status(self) -> dict[str, Any]:
        payload = await self._get("/v1/status")
        return payload if isinstance(payload, dict) else {}

    async def timeline(self, day: date) -> list[dict[str, Any]]:
        """Foreground segments for one local calendar day."""
        payload = await self._get("/v1/timeline", {"date": day.isoformat()})
        segments = payload.get("segments") if isinstance(payload, dict) else None
        return [item for item in segments if isinstance(item, dict)] if segments else []

    async def apps(self, day: date, *, current_window: bool) -> list[dict[str, Any]]:
        """Per-app minutes, from the system's own daily buckets.

        `current_window` selects the single open bucket rather than buckets that
        *started* on `day`. Android's daily buckets do not begin at midnight, so
        for a day still in progress `?date=` matches the wrong thing — usually
        nothing at all, occasionally two overlapping ~24-hour periods summed
        into one date.
        """
        params = {"window": "current"} if current_window else {"date": day.isoformat()}
        payload = await self._get("/v1/apps", params)
        apps = payload.get("apps") if isinstance(payload, dict) else None
        return [item for item in apps if isinstance(item, dict)] if apps else []

    async def summary(self, day: date) -> dict[str, Any]:
        payload = await self._get("/v1/summary", {"date": day.isoformat()})
        return payload if isinstance(payload, dict) else {}
