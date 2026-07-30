"""Structured JSON errors with actionable messages."""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse

from ..config.schema import ConfigError
from ..connectors.home_assistant.client import HomeAssistantError
from ..connectors.wearables.base import WearableProviderError


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.hint = hint


def _payload(code: str, message: str, hint: str | None = None) -> dict:
    body = {"error": {"code": code, "message": message}}
    if hint:
        body["error"]["hint"] = hint
    return body


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content=_payload(exc.code, exc.message, exc.hint)
    )


async def config_error_handler(_request: Request, exc: ConfigError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_payload(
            "invalid_configuration",
            str(exc),
            "Fix config.yaml (or copy config.example.yaml over it) and refresh.",
        ),
    )


async def home_assistant_error_handler(
    _request: Request, exc: HomeAssistantError
) -> JSONResponse:
    codes = {
        "auth": status.HTTP_502_BAD_GATEWAY,
        "unreachable": status.HTTP_503_SERVICE_UNAVAILABLE,
        "rate_limit": status.HTTP_429_TOO_MANY_REQUESTS,
    }
    return JSONResponse(
        status_code=codes.get(exc.kind, status.HTTP_502_BAD_GATEWAY),
        content=_payload(f"home_assistant_{exc.kind}", str(exc)),
    )


async def wearable_error_handler(_request: Request, exc: WearableProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content=_payload("wearable_provider_error", str(exc)),
    )


def register(app) -> None:
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(ConfigError, config_error_handler)
    app.add_exception_handler(HomeAssistantError, home_assistant_error_handler)
    app.add_exception_handler(WearableProviderError, wearable_error_handler)
