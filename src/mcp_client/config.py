"""MCP server definitions: bundled ones from configs/mcp_servers.json plus the
ones the user adds at runtime (stored in SQLite).

Both use the standard ``mcpServers`` shape, with the DAXAGENT-specific fields
(display name, icon, OAuth endpoints, prompt text, auth type, persona access)
under a ``daxagent`` block per server. Everything else asks for a server by
name through the sync helpers below; ``refresh()`` reloads the runtime servers
from the database and is called at startup and after every add or remove.
"""

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

_CONFIG_PATH = Path(__file__).parent.parent.parent / "configs" / "mcp_servers.json"

_bundled: dict[str, dict[str, Any]] | None = None
_runtime: dict[str, dict[str, Any]] = {}
_flags: dict[str, bool] = {}


def _load_bundled() -> dict[str, dict[str, Any]]:
    global _bundled
    if _bundled is None:
        try:
            with open(_CONFIG_PATH) as f:
                _bundled = json.load(f).get("mcpServers", {})
        except FileNotFoundError:
            logger.warning(f"No MCP config at {_CONFIG_PATH}; no bundled servers")
            _bundled = {}
        except json.JSONDecodeError as e:
            logger.error(f"MCP config is not valid JSON ({e}); no bundled servers")
            _bundled = {}
        logger.info(f"Loaded {len(_bundled)} bundled MCP server(s): {', '.join(_bundled) or 'none'}")
    return _bundled


def _config() -> dict[str, dict[str, Any]]:
    """Bundled and runtime servers, keyed by name; runtime wins on a clash. A bundled one removed in Settings is gone."""
    bundled = {name: c for name, c in _load_bundled().items() if not _flags.get(f"removed:{name}")}
    return {**bundled, **_runtime}


async def refresh() -> None:
    """Reload runtime-added servers and the on/off flags from the database."""
    global _runtime, _flags
    from src.database import load_mcp_server_flags, load_mcp_servers

    try:
        _runtime = await load_mcp_servers()
        _flags = await load_mcp_server_flags()
    except Exception as e:
        logger.warning(f"Could not load runtime MCP servers: {e}")
        _runtime = {}
    if _runtime:
        logger.info(f"Loaded {len(_runtime)} runtime MCP server(s): {', '.join(_runtime)}")


async def add_server(name: str, config: dict[str, Any]) -> None:
    """Persist a runtime server and make it visible immediately."""
    from src.database import save_mcp_server

    await save_mcp_server(name, config)
    _runtime[name] = config


async def remove_server(name: str) -> bool:
    """Forget a runtime server. Bundled servers cannot be removed, only disconnected."""
    from src.database import delete_mcp_server

    removed = await delete_mcp_server(name)
    _runtime.pop(name, None)
    return removed


async def remove_bundled(server: str) -> None:
    """Remove a bundled server from this app (its config file stays as shipped; adding its URL brings it back)."""
    await _save_flag(f"removed:{server}", True)


def is_bundled(server: str) -> bool:
    return server in _load_bundled() and server not in _runtime


def server_names() -> list[str]:
    """Every configured server name."""
    return list(_config())


def server_url(server: str) -> str:
    """The server's endpoint URL; MCP_URL_<NAME> overrides it per deployment (e.g. the hosted app's User's Context), and a
    server may name its own variable (`url_env` in its config block)."""
    return (os.getenv(f"MCP_URL_{server.upper().replace('-', '_')}") or os.getenv(options(server).get("url_env", "")) or "").strip() or _config()[server]["url"]


def options(server: str) -> dict[str, Any]:
    """The server's DAXAGENT block, or an empty dict when it has none."""
    return _config().get(server, {}).get("daxagent", {})


def auth_type(server: str) -> str:
    """``oauth``, ``bearer``, ``api_key`` (custom header) or ``none``."""
    return options(server).get("auth", "oauth" if options(server).get("oauth") else "none")


def auth_header_name(server: str) -> str:
    """Header that carries a stored token: Authorization (bearer) or a custom one (api_key)."""
    return options(server).get("header", "x-api-key" if auth_type(server) == "api_key" else "Authorization")


def oauth_endpoints(server: str) -> dict[str, str]:
    """The server's OAuth endpoints.

    Raises:
        KeyError: when the server declares no OAuth block, which means it
            cannot be signed in to.
    """
    endpoints = options(server).get("oauth")
    if not endpoints:
        raise KeyError(f"MCP server '{server}' has no oauth configuration")
    return endpoints


def personas_for(server: str) -> list[str] | None:
    """Personas named for the server, or None (session.offered says what that means). For a bundled server the
    choice made in Settings wins: a marker switch plus one switch per agent, so its config file stays as shipped."""
    if _flags.get(f"agents:{server}"):
        prefix = f"persona:{server}:"
        return [k[len(prefix):] for k, on in _flags.items() if on and k.startswith(prefix)]
    return options(server).get("personas")


async def set_personas(server: str, personas: list[str]) -> None:
    """Settings' choice of agents for a bundled server (user-added ones keep it in their own config)."""
    prefix = f"persona:{server}:"
    for name in {k[len(prefix):] for k in _flags if k.startswith(prefix)} | set(personas):
        await _save_flag(prefix + name, name in personas)
    await _save_flag(f"agents:{server}", True)


def wants_specialist(server: str) -> bool:
    """The server's own sub-agent switch: on unless opted out (Settings for a bundled server, else its config)."""
    return _flags.get(f"specialist:{server}", options(server).get("specialist", True) is not False)


async def set_specialist(server: str, on: bool) -> None:
    await _save_flag(f"specialist:{server}", on)


def is_reserved(server: str) -> bool:
    """Reserved servers (Data Axle) are used by the sales personas directly and get no specialist."""
    return options(server).get("reserved") is True


def is_enabled(server: str) -> bool:
    """The user's switch for the server; on by default."""
    if server in _flags:
        return _flags[server]
    return options(server).get("enabled", True) is not False


async def set_enabled(server: str, enabled: bool) -> None:
    await _save_flag(server, enabled)


def in_mode(server: str, mode: str) -> bool:
    """The user's per-mode switch ("chat" or "task") for the server; defaults to the server's `modes` (both)."""
    return _flags.get(f"{mode}:{server}", mode in options(server).get("modes", ("chat", "task")))


async def set_mode(server: str, mode: str, on: bool) -> None:
    await _save_flag(f"{mode}:{server}", on)


async def _save_flag(key: str, on: bool) -> None:
    global _flags_version
    from src.database import save_mcp_server_flag

    await save_mcp_server_flag(key, on)
    _flags[key] = on
    _flags_version += 1


_flags_version = 0  # bumped on every switch change or tool re-list, so open sessions rebuild their tool list


def flags_version() -> int:
    return _flags_version


def tools_changed() -> None:
    """A server's tools were re-listed: open sessions rebuild their tool table before their next turn."""
    global _flags_version
    _flags_version += 1


def enabled_servers() -> list[str]:
    return [name for name in server_names() if is_enabled(name)]


def reserved_servers() -> list[str]:
    return [name for name in enabled_servers() if is_reserved(name)]


def specialist_eligible(server: str) -> bool:
    """Servers that get their own sub-agent: enabled, not reserved, not opted out."""
    return is_enabled(server) and in_mode(server, "task") and not is_reserved(server) and wants_specialist(server)
