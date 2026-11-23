"""Obscura, the headless browser behind the Web Surfer: its MCP server runs beside the app when the binary is installed.

configs/mcp_servers.json points the "obscura" server at OBSCURA_PORT; without the binary the server stays unreachable and
the Web Surfer is not offered (orchestrator.NEEDS_MCP).
"""

import os
import socket
import subprocess
from pathlib import Path

from loguru import logger

OBSCURA_PORT = 8326
_process: subprocess.Popen | None = None


def start() -> None:
    """Start `obscura mcp --http` on OBSCURA_PORT, unless it is already listening or the binary is missing."""
    global _process
    binary = Path(os.getenv("OBSCURA_BIN") or Path.home() / ".daxagent" / "bin" / "obscura")
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", OBSCURA_PORT)) == 0:
            logger.info(f"Obscura already listening on {OBSCURA_PORT}")
            return
    if not binary.is_file():
        logger.info(f"Obscura not installed at {binary}; the Web Surfer stays off")
        return
    _process = subprocess.Popen([str(binary), "mcp", "--http", "--port", str(OBSCURA_PORT)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info(f"Obscura browser started on {OBSCURA_PORT} (pid {_process.pid})")


def stop() -> None:
    if _process and _process.poll() is None:
        _process.terminate()
