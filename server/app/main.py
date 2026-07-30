"""FastAPI application factory.

Binds to 127.0.0.1 by default and restricts CORS to the local frontend. When
`frontend/dist` exists it is served from this same process, so the whole app
lives at one localhost URL.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import errors, routes
from .config.loader import get_config
from .config.settings import REPO_ROOT, get_settings
from .services.sync import SyncService
from .storage.repository import Repository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("yesterday")

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    config = get_config()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    repository = Repository(settings.database_url, settings.database_path)
    sync_service = SyncService(repository, settings, config)
    routes.configure(repository, sync_service)
    app.state.repository = repository
    app.state.sync_service = sync_service
    logger.info(
        "Yesterday API ready on %s (timezone %s, mock data %s)",
        settings.api_base_url,
        sync_service.tz.key,
        settings.use_mock_data,
    )

    # An MCP-backed wearable takes seconds to sign in. Warming it here means the
    # first page load does not wait on it.
    warm_up = asyncio.create_task(sync_service.warm_up())

    try:
        yield
    finally:
        warm_up.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Yesterday Timeline",
        version="0.1.0",
        summary="Local reconstruction of the previous day from Home Assistant and wearables",
        description=(
            "All processing happens on this machine. No personal sensor data leaves "
            "localhost."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    errors.register(app)
    app.include_router(routes.router)
    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA when it exists; otherwise point at the dev server."""
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        @app.get("/", include_in_schema=False)
        async def _no_build() -> dict[str, str]:
            settings = get_settings()
            return {
                "message": (
                    "The frontend has not been built yet. Run `npm run build` in "
                    "frontend/, or start the dev server with `npm run dev`."
                ),
                "devServer": settings.frontend_dev_url,
                "apiDocs": f"{settings.api_base_url}/docs",
            }
        return

    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def _index() -> FileResponse:
        return FileResponse(index)

    root = FRONTEND_DIST.resolve()

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def _spa(path: str) -> FileResponse:
        """Serve a real build artefact when there is one, else the SPA shell.

        Static files at the build root — favicon.ico, the manifest, the PNG
        icons — have to win over the shell, or the browser is handed HTML where
        it asked for an image and quietly shows no icon at all.
        """
        if path:
            candidate = (FRONTEND_DIST / path).resolve()
            # `path` is user-controlled and may contain "..", so confirm the
            # resolved file is still inside the build before serving it.
            if candidate.is_file() and candidate.is_relative_to(root):
                return FileResponse(candidate)
        return FileResponse(index)


app = create_app()


def run() -> None:
    """Console entry point: `yesterday-timeline-api`."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )


if __name__ == "__main__":  # pragma: no cover
    run()
