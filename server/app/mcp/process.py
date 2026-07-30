"""Start and reuse the local backend / frontend processes.

Every helper here is idempotent: it probes the port first and only spawns a
process when nothing is already answering, so calling `launch_yesterday_timeline`
repeatedly never produces duplicate servers.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from ..config.settings import REPO_ROOT, get_settings

logger = logging.getLogger(__name__)

SERVER_DIR = REPO_ROOT / "server"
FRONTEND_DIR = REPO_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"

_processes: dict[str, subprocess.Popen] = {}

STARTUP_TIMEOUT_SECONDS = 45.0
POLL_INTERVAL_SECONDS = 0.4


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def backend_health(base_url: str, timeout: float = 1.5) -> dict[str, Any] | None:
    try:
        response = httpx.get(f"{base_url}/api/health", timeout=timeout)
        if response.status_code == 200:
            return response.json()
    except httpx.HTTPError:
        return None
    return None


def frontend_built() -> bool:
    return (FRONTEND_DIST / "index.html").exists()


def _spawn(name: str, command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    logger.info("Starting %s: %s", name, " ".join(command))
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    _processes[name] = process
    return process


def ensure_backend() -> dict[str, Any]:
    """Start uvicorn if the API is not already answering."""
    settings = get_settings()
    base_url = settings.api_base_url

    health = backend_health(base_url)
    if health is not None:
        return {"started": False, "url": base_url, "health": health}

    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(SERVER_DIR) + (os.pathsep + existing if existing else "")

    _spawn(
        "backend",
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            settings.api_host,
            "--port",
            str(settings.api_port),
            "--log-level",
            "warning",
        ],
        SERVER_DIR,
        env,
    )

    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        health = backend_health(base_url)
        if health is not None:
            return {"started": True, "url": base_url, "health": health}
        process = _processes.get("backend")
        if process is not None and process.poll() is not None:
            raise RuntimeError(
                f"The backend exited with code {process.returncode} before becoming healthy. "
                f"Run `python -m uvicorn app.main:app` in {SERVER_DIR} to see the error."
            )
        time.sleep(POLL_INTERVAL_SECONDS)

    raise RuntimeError(
        f"The backend did not answer {base_url}/api/health within "
        f"{STARTUP_TIMEOUT_SECONDS:.0f}s."
    )


def ensure_frontend(*, prefer_dev_server: bool = False) -> dict[str, Any]:
    """Return the URL the user should open.

    When `frontend/dist` exists the backend already serves the SPA, so there is
    nothing to start. Otherwise the Vite dev server is launched.
    """
    settings = get_settings()

    if frontend_built() and not prefer_dev_server:
        return {
            "started": False,
            "url": settings.api_base_url,
            "mode": "static_build",
            "detail": "The built frontend is served by the backend process.",
        }

    dev_url = settings.frontend_dev_url
    if _port_open(settings.api_host, settings.frontend_port):
        return {
            "started": False,
            "url": dev_url,
            "mode": "dev_server",
            "detail": "A dev server was already listening on this port.",
        }

    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            "npm was not found on PATH and frontend/dist does not exist. Install Node.js "
            "18+ and run `npm install && npm run build` in the frontend directory."
        )
    if not (FRONTEND_DIR / "node_modules").exists():
        raise RuntimeError(
            f"Frontend dependencies are not installed. Run `npm install` in {FRONTEND_DIR}."
        )

    env = dict(os.environ)
    env["VITE_API_BASE_URL"] = settings.api_base_url
    _spawn(
        "frontend",
        [npm, "run", "dev", "--", "--port", str(settings.frontend_port), "--strictPort"],
        FRONTEND_DIR,
        env,
    )

    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if _port_open(settings.api_host, settings.frontend_port):
            return {
                "started": True,
                "url": dev_url,
                "mode": "dev_server",
                "detail": "Vite dev server started.",
            }
        process = _processes.get("frontend")
        if process is not None and process.poll() is not None:
            raise RuntimeError(
                f"The Vite dev server exited with code {process.returncode}. "
                f"Run `npm run dev` in {FRONTEND_DIR} to see the error."
            )
        time.sleep(POLL_INTERVAL_SECONDS)

    raise RuntimeError(f"The frontend dev server did not start on {dev_url} in time.")


def stop_all() -> list[str]:
    stopped = []
    for name, process in list(_processes.items()):
        if process.poll() is None:
            process.terminate()
            stopped.append(name)
        _processes.pop(name, None)
    return stopped


def open_in_browser(url: str) -> tuple[bool, str]:
    """Best-effort browser launch; never fails the tool call."""
    import webbrowser

    try:
        if webbrowser.open(url):
            return True, f"Opened {url} in the default browser."
    except Exception as exc:  # noqa: BLE001 - headless environments are normal
        return False, f"Could not open a browser automatically ({exc}). Open {url} manually."
    return False, f"No browser could be launched on this system. Open {url} manually."
