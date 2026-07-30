"""A small stdio MCP client, so this app can consume other MCP servers.

The timeline is itself an MCP server, but its *data sources* are MCP servers
too: Home Assistant and Garmin both reach the user through an MCP integration.
This module spawns a configured server, runs one session, and calls read-only
tools on it.

Two rules are enforced here rather than left to callers:

* **Read-only.** `call_tool` refuses any tool whose name is not in the caller's
  declared allow-list. The Garmin MCP also exposes tools that create workouts
  and delete courses; nothing in this application may reach them.
* **One session per fetch.** Spawning a server costs seconds (`uvx` resolves a
  package on first run), so a sync opens one session and makes all of its calls
  inside it rather than reconnecting per metric.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from ..config.schema import McpServerConfig

logger = logging.getLogger(__name__)

# Where the common desktop MCP clients keep their server definitions. Reusing
# these means the user configures Garmin once, in the client they already use.
CLIENT_CONFIG_CANDIDATES = (
    Path.home() / ".claude.json",
    Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json",
    Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
    Path.home() / ".config" / "Claude" / "claude_desktop_config.json",
)

DEFAULT_STARTUP_TIMEOUT = 120.0
DEFAULT_CALL_TIMEOUT = 90.0


class McpClientError(RuntimeError):
    """Raised when a configured MCP server cannot be reached or used."""


class McpToolNotAllowed(McpClientError):
    """Raised when code tries to call a tool outside the read-only allow-list."""


def discover_server(name: str) -> dict[str, Any] | None:
    """Find `name` in an installed MCP client's configuration.

    Returns the raw server entry (`command`, `args`, `env`) or None. Secrets in
    the entry are passed straight to the subprocess and never logged.
    """
    for path in CLIENT_CONFIG_CANDIDATES:
        try:
            if not path or not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        servers = payload.get("mcpServers")
        if isinstance(servers, dict) and name in servers:
            entry = servers[name]
            if isinstance(entry, dict) and entry.get("command"):
                logger.info("Found MCP server '%s' in %s", name, path.name)
                return entry
    return None


def resolve_server(config: McpServerConfig) -> tuple[list[str], dict[str, str]] | None:
    """Work out how to launch a server: explicit config first, then discovery."""
    command = config.command
    args = list(config.args)
    env = dict(config.env)

    if not command and config.discover_from_client:
        entry = discover_server(config.discovery_name or "")
        if entry is None:
            return None
        command = entry.get("command")
        args = list(entry.get("args") or [])
        env = {**(entry.get("env") or {}), **env}

    if not command:
        return None
    if shutil.which(command) is None and not Path(command).exists():
        # `cmd`/`sh` always resolve; a bare package name may not.
        logger.warning("MCP server command '%s' was not found on PATH", command)
    return [command, *args], env


class McpStdioSession:
    """One live session with a spawned MCP server."""

    def __init__(self, name: str, session: Any, allowed_tools: frozenset[str]) -> None:
        self.name = name
        self._session = session
        self._allowed = allowed_tools
        self._tool_names: set[str] | None = None

    async def list_tools(self) -> list[str]:
        if self._tool_names is None:
            result = await asyncio.wait_for(self._session.list_tools(), timeout=60)
            self._tool_names = {tool.name for tool in result.tools}
        return sorted(self._tool_names)

    def supports(self, tool: str) -> bool:
        return self._tool_names is None or tool in self._tool_names

    async def call_json(
        self, tool: str, arguments: dict[str, Any], *, timeout: float = DEFAULT_CALL_TIMEOUT
    ) -> Any:
        """Call a read-only tool and parse its text content as JSON.

        Returns None when the server replied with prose rather than JSON — which
        these servers do for "no data for that date". That is a real answer, not
        an error, and callers treat it as "nothing recorded".
        """
        if tool not in self._allowed:
            raise McpToolNotAllowed(
                f"'{tool}' is not in the read-only allow-list for the {self.name} MCP server."
            )
        if not self.supports(tool):
            return None

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool, arguments), timeout=timeout
            )
        except asyncio.TimeoutError as exc:
            raise McpClientError(
                f"The {self.name} MCP server did not answer '{tool}' within {timeout:.0f}s."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - surfaced as a source error
            raise McpClientError(f"The {self.name} MCP server failed on '{tool}': {exc}") from exc

        if getattr(result, "is_error", False) or getattr(result, "isError", False):
            text = _text_of(result)
            raise McpClientError(f"{self.name}.{tool} returned an error: {text[:300]}")

        text = _text_of(result).strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None


def _text_of(result: Any) -> str:
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


@asynccontextmanager
async def open_session(
    name: str,
    config: McpServerConfig,
    allowed_tools: frozenset[str],
    *,
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
):
    """Spawn the configured server, initialize, and yield a session."""
    resolved = resolve_server(config)
    if resolved is None:
        raise McpClientError(
            f"No launch command for the '{name}' MCP server. Set mcp.servers.{name}.command "
            "in config.yaml, or install the server in your MCP client so it can be "
            "discovered automatically."
        )
    command, extra_env = resolved

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:  # pragma: no cover - the SDK is a hard dependency
        raise McpClientError(f"The MCP Python SDK is not installed: {exc}") from exc

    params = StdioServerParameters(
        command=command[0],
        args=command[1:],
        env={**os.environ, **extra_env},
    )

    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                try:
                    await asyncio.wait_for(session.initialize(), timeout=startup_timeout)
                except asyncio.TimeoutError as exc:
                    raise McpClientError(
                        f"The '{name}' MCP server did not start within "
                        f"{startup_timeout:.0f}s. Try running it once by hand so any "
                        "package download and sign-in are already done."
                    ) from exc
                yield McpStdioSession(name, session, allowed_tools)
    except McpClientError:
        raise
    except Exception as exc:  # noqa: BLE001 - reported as a source status
        raise McpClientError(f"Could not start the '{name}' MCP server: {exc}") from exc
