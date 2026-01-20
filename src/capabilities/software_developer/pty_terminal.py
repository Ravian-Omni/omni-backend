"""PTY-based terminal executor for native terminal experience.

This module provides a true terminal emulation using pseudo-terminals (PTY),
enabling full interactive shell support with proper keyboard handling,
ANSI escape sequences, and terminal resize support.

Supports:
- Unix systems using PTY (Linux, macOS)
- Windows using ConPTY (Windows 10 1809+) with fallback to subprocess
- Nuitka-compiled binaries (avoids fork() by using subprocess approach)
"""

import asyncio
import os
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from loguru import logger

# Platform detection
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# Platform-specific imports for Unix
if not IS_WINDOWS:
    import fcntl
    import pty
    import select
    import signal
    import struct
    import termios

if TYPE_CHECKING:
    from src.managers.connection import WebSocketManager


class BaseTerminal(ABC):
    """Abstract base class for terminal implementations."""

    # Default terminal dimensions
    DEFAULT_COLS = 120
    DEFAULT_ROWS = 30

    def __init__(
        self,
        session_id: str,
        working_directory: str,
        websocket_manager: "WebSocketManager | None" = None,
    ):
        """Initialize the terminal.

        Args:
            session_id: Session identifier for WebSocket communication.
            working_directory: Initial working directory.
            websocket_manager: WebSocket manager for streaming output.
        """
        self.session_id = session_id
        self.working_directory = os.path.abspath(working_directory)
        self.websocket_manager = websocket_manager
        self.cols = self.DEFAULT_COLS
        self.rows = self.DEFAULT_ROWS
        self._running = False
        self._started_at: float | None = None

    async def stream_output(self, data: dict[str, Any]) -> None:
        """Stream output to WebSocket clients."""
        if self.websocket_manager is None:
            return

        try:
            await self.websocket_manager.send_chat_message(
                session_id=self.session_id,
                content=data,
                source="pty_terminal",
            )
        except Exception as e:
            logger.debug(f"Error streaming PTY output: {e}")

    @abstractmethod
    async def start(self, cols: int | None = None, rows: int | None = None) -> bool:
        """Start the terminal session."""

    @abstractmethod
    async def write(self, data: str | bytes) -> bool:
        """Write data to the terminal."""

    @abstractmethod
    async def resize(self, cols: int, rows: int) -> None:
        """Resize the terminal."""

    @abstractmethod
    async def terminate(self, force: bool = False) -> None:
        """Terminate the terminal session."""

    @property
    def is_running(self) -> bool:
        """Check if the terminal is running."""
        return self._running

    def get_status(self) -> dict[str, Any]:
        """Get terminal status information."""
        return {
            "running": self._running,
            "cols": self.cols,
            "rows": self.rows,
            "working_directory": self.working_directory,
            "started_at": self._started_at,
            "uptime": time.time() - self._started_at if self._started_at else 0,
        }


class UnixPtyTerminal(BaseTerminal):
    """Unix PTY-based terminal using subprocess (Nuitka-compatible).

    Uses pty.openpty() + subprocess.Popen instead of os.fork() + os.exec()
    for better compatibility with Nuitka and other packagers.
    """

    # Read buffer size
    READ_BUFFER_SIZE = 4096

    # Output read interval (seconds)
    OUTPUT_READ_INTERVAL = 0.01

    def __init__(
        self,
        session_id: str,
        working_directory: str,
        websocket_manager: "WebSocketManager | None" = None,
        shell: str | None = None,
    ):
        """Initialize the Unix PTY terminal.

        Args:
            session_id: Session identifier.
            working_directory: Initial working directory.
            websocket_manager: WebSocket manager.
            shell: Shell to use (defaults to $SHELL or /bin/bash).
        """
        super().__init__(session_id, working_directory, websocket_manager)

        # Determine shell
        self.shell = shell or os.environ.get("SHELL", "/bin/bash")

        # PTY state
        self.master_fd: int | None = None
        self.slave_fd: int | None = None
        self.process: subprocess.Popen | None = None

        # Async tasks
        self._output_task: asyncio.Task | None = None
        self._terminated = False

    async def start(self, cols: int | None = None, rows: int | None = None) -> bool:
        """Start the PTY terminal session.

        Args:
            cols: Terminal width in columns.
            rows: Terminal height in rows.

        Returns:
            True if started successfully.
        """
        if self._running:
            logger.warning(
                f"PTY terminal already running for session {self.session_id}"
            )
            return False

        self.cols = cols or self.DEFAULT_COLS
        self.rows = rows or self.DEFAULT_ROWS

        try:
            # Create PTY master/slave pair
            self.master_fd, self.slave_fd = pty.openpty()

            # Set terminal size on the slave
            self._set_terminal_size(self.slave_fd, self.cols, self.rows)

            # Set master to non-blocking
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            # Set up environment
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLORTERM"] = "truecolor"
            env["LANG"] = env.get("LANG", "en_US.UTF-8")
            env["LC_ALL"] = env.get("LC_ALL", "en_US.UTF-8")
            # Set columns and lines for proper terminal size reporting
            env["COLUMNS"] = str(self.cols)
            env["LINES"] = str(self.rows)

            # Start shell process with PTY slave as stdin/stdout/stderr
            self.process = subprocess.Popen(
                [self.shell, "-l"],  # Login shell
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                cwd=self.working_directory,
                env=env,
                preexec_fn=os.setsid,  # Create new session
                close_fds=True,
            )

            # Close slave FD in parent - child has it
            os.close(self.slave_fd)
            self.slave_fd = None

            self._running = True
            self._started_at = time.time()

            # Start output monitoring
            self._output_task = asyncio.create_task(self._monitor_output())

            await self.stream_output(
                {
                    "type": "terminal_started",
                    "pid": self.process.pid,
                    "cols": self.cols,
                    "rows": self.rows,
                    "shell": self.shell,
                    "working_directory": self.working_directory,
                    "timestamp": time.time(),
                }
            )

            logger.info(
                f"PTY terminal started for session {self.session_id}, "
                f"pid={self.process.pid}, shell={self.shell}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start PTY terminal: {e}")
            await self._cleanup()
            return False

    def _set_terminal_size(self, fd: int, cols: int, rows: int) -> None:
        """Set terminal size on a file descriptor."""
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
        except Exception as e:
            logger.debug(f"Failed to set terminal size: {e}")

    async def resize(self, cols: int, rows: int) -> None:
        """Resize the terminal."""
        if not self._running or self.master_fd is None:
            return

        self.cols = cols
        self.rows = rows

        # Set size on master FD
        self._set_terminal_size(self.master_fd, cols, rows)

        # Send SIGWINCH to shell process group
        if self.process and self.process.pid:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGWINCH)
            except (ProcessLookupError, PermissionError):
                pass

        await self.stream_output(
            {
                "type": "terminal_resized",
                "cols": cols,
                "rows": rows,
                "timestamp": time.time(),
            }
        )

    async def write(self, data: str | bytes) -> bool:
        """Write data to the terminal (keyboard input)."""
        if not self._running or self.master_fd is None:
            return False

        try:
            if isinstance(data, str):
                data = data.encode("utf-8")

            os.write(self.master_fd, data)
            return True

        except OSError as e:
            if e.errno == 5:  # I/O error - terminal closed
                await self._handle_exit()
            else:
                logger.debug(f"Error writing to PTY: {e}")
            return False

    async def _monitor_output(self) -> None:
        """Monitor PTY output and stream to WebSocket."""
        loop = asyncio.get_event_loop()

        while self._running and self.master_fd is not None:
            try:
                # Check for readable data using select
                readable, _, _ = await loop.run_in_executor(
                    None,
                    lambda: select.select([self.master_fd], [], [], 0.1),
                )

                if self.master_fd in readable:
                    try:
                        data = os.read(self.master_fd, self.READ_BUFFER_SIZE)

                        if data:
                            await self.stream_output(
                                {
                                    "type": "terminal_output",
                                    "data": data.decode("utf-8", errors="replace"),
                                    "timestamp": time.time(),
                                }
                            )
                        else:
                            # EOF
                            await self._handle_exit()
                            break

                    except OSError as e:
                        if e.errno == 5:  # I/O error
                            await self._handle_exit()
                            break
                        elif e.errno != 11:  # Ignore EAGAIN
                            logger.debug(f"Error reading from PTY: {e}")

                # Check if process exited
                if self.process:
                    retcode = self.process.poll()
                    if retcode is not None:
                        await self._handle_exit(retcode)
                        break

                await asyncio.sleep(self.OUTPUT_READ_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in PTY output monitor: {e}")
                await asyncio.sleep(0.1)

    async def _handle_exit(self, exit_code: int | None = None) -> None:
        """Handle terminal exit."""
        if self._terminated:
            return

        self._terminated = True
        self._running = False

        if exit_code is None and self.process:
            exit_code = self.process.poll() or 0

        await self.stream_output(
            {
                "type": "terminal_exited",
                "exit_code": exit_code or 0,
                "duration": time.time() - self._started_at if self._started_at else 0,
                "timestamp": time.time(),
            }
        )

        logger.info(
            f"PTY terminal exited for session {self.session_id}, exit_code={exit_code}"
        )

        await self._cleanup()

    async def terminate(self, force: bool = False) -> None:
        """Terminate the terminal session."""
        if not self._running:
            return

        self._running = False

        if self.process and self.process.poll() is None:
            try:
                if force:
                    # Kill process group
                    try:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        self.process.kill()
                else:
                    # Send SIGTERM first
                    try:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        self.process.terminate()

                    # Wait briefly, then force kill
                    try:
                        self.process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            self.process.kill()

                self.process.wait(timeout=1.0)
            except Exception as e:
                logger.debug(f"Error terminating process: {e}")

        # Cancel output task
        if self._output_task and not self._output_task.done():
            self._output_task.cancel()
            try:
                await self._output_task
            except asyncio.CancelledError:
                pass

        await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up resources."""
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

        if self.slave_fd is not None:
            try:
                os.close(self.slave_fd)
            except OSError:
                pass
            self.slave_fd = None

    async def send_signal(self, sig: int) -> bool:
        """Send a signal to the terminal process group."""
        if self.process is None or self.process.poll() is not None:
            return False

        try:
            os.killpg(os.getpgid(self.process.pid), sig)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def get_status(self) -> dict[str, Any]:
        """Get terminal status."""
        status = super().get_status()
        status.update(
            {
                "pid": self.process.pid if self.process else None,
                "shell": self.shell,
            }
        )
        return status


class WindowsTerminal(BaseTerminal):
    """Windows terminal using subprocess with ConPTY-like behavior.

    Note: Full ConPTY support requires pywinpty package.
    This implementation provides a subprocess-based fallback.
    """

    READ_BUFFER_SIZE = 4096

    def __init__(
        self,
        session_id: str,
        working_directory: str,
        websocket_manager: "WebSocketManager | None" = None,
        shell: str | None = None,
    ):
        """Initialize Windows terminal."""
        super().__init__(session_id, working_directory, websocket_manager)

        # Use cmd.exe or PowerShell
        self.shell = shell or os.environ.get("COMSPEC", "cmd.exe")
        self.process: asyncio.subprocess.Process | None = None
        self._output_task: asyncio.Task | None = None
        self._terminated = False

    async def start(self, cols: int | None = None, rows: int | None = None) -> bool:
        """Start the Windows terminal session."""
        if self._running:
            return False

        self.cols = cols or self.DEFAULT_COLS
        self.rows = rows or self.DEFAULT_ROWS

        try:
            # Set up environment
            env = os.environ.copy()
            env["COLUMNS"] = str(self.cols)
            env["LINES"] = str(self.rows)

            # Try to use pywinpty if available for true PTY support
            try:
                import winpty

                # Use winpty for proper PTY emulation
                self._pty = winpty.PtyProcess.spawn(
                    self.shell,
                    cwd=self.working_directory,
                    env=env,
                    dimensions=(self.rows, self.cols),
                )
                self._use_winpty = True

            except ImportError:
                # Fallback to subprocess
                self._use_winpty = False
                self.process = await asyncio.create_subprocess_shell(
                    self.shell,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.working_directory,
                    env=env,
                )

            self._running = True
            self._started_at = time.time()

            # Start output monitoring
            self._output_task = asyncio.create_task(self._monitor_output())

            await self.stream_output(
                {
                    "type": "terminal_started",
                    "pid": (
                        self._pty.pid
                        if hasattr(self, "_use_winpty") and self._use_winpty
                        else self.process.pid if self.process else None
                    ),
                    "cols": self.cols,
                    "rows": self.rows,
                    "shell": self.shell,
                    "working_directory": self.working_directory,
                    "timestamp": time.time(),
                    "mode": (
                        "winpty"
                        if getattr(self, "_use_winpty", False)
                        else "subprocess"
                    ),
                }
            )

            return True

        except Exception as e:
            logger.error(f"Failed to start Windows terminal: {e}")
            return False

    async def write(self, data: str | bytes) -> bool:
        """Write data to the terminal."""
        if not self._running:
            return False

        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")

            if getattr(self, "_use_winpty", False) and hasattr(self, "_pty"):
                self._pty.write(data)
            elif self.process and self.process.stdin:
                if isinstance(data, str):
                    data = data.encode("utf-8")
                self.process.stdin.write(data)
                await self.process.stdin.drain()
            else:
                return False

            return True
        except Exception as e:
            logger.debug(f"Error writing to Windows terminal: {e}")
            return False

    async def resize(self, cols: int, rows: int) -> None:
        """Resize the terminal."""
        self.cols = cols
        self.rows = rows

        if getattr(self, "_use_winpty", False) and hasattr(self, "_pty"):
            try:
                self._pty.setwinsize(rows, cols)
            except Exception:
                pass

        await self.stream_output(
            {
                "type": "terminal_resized",
                "cols": cols,
                "rows": rows,
                "timestamp": time.time(),
            }
        )

    async def _monitor_output(self) -> None:
        """Monitor terminal output."""
        while self._running:
            try:
                if getattr(self, "_use_winpty", False) and hasattr(self, "_pty"):
                    # Read from winpty
                    if self._pty.isalive():
                        try:
                            data = self._pty.read(self.READ_BUFFER_SIZE, timeout=0.1)
                            if data:
                                await self.stream_output(
                                    {
                                        "type": "terminal_output",
                                        "data": data,
                                        "timestamp": time.time(),
                                    }
                                )
                        except Exception:
                            pass
                    else:
                        await self._handle_exit()
                        break

                elif self.process:
                    # Read from subprocess stdout
                    if self.process.stdout:
                        try:
                            data = await asyncio.wait_for(
                                self.process.stdout.read(self.READ_BUFFER_SIZE),
                                timeout=0.1,
                            )
                            if data:
                                await self.stream_output(
                                    {
                                        "type": "terminal_output",
                                        "data": data.decode("utf-8", errors="replace"),
                                        "timestamp": time.time(),
                                    }
                                )
                            elif self.process.returncode is not None:
                                await self._handle_exit(self.process.returncode)
                                break
                        except TimeoutError:
                            pass

                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in Windows terminal output monitor: {e}")
                await asyncio.sleep(0.1)

    async def _handle_exit(self, exit_code: int | None = None) -> None:
        """Handle terminal exit."""
        if self._terminated:
            return

        self._terminated = True
        self._running = False

        await self.stream_output(
            {
                "type": "terminal_exited",
                "exit_code": exit_code or 0,
                "duration": time.time() - self._started_at if self._started_at else 0,
                "timestamp": time.time(),
            }
        )

    async def terminate(self, force: bool = False) -> None:
        """Terminate the terminal."""
        if not self._running:
            return

        self._running = False

        if getattr(self, "_use_winpty", False) and hasattr(self, "_pty"):
            try:
                self._pty.terminate(force=force)
            except Exception:
                pass
        elif self.process:
            if force:
                self.process.kill()
            else:
                self.process.terminate()

        if self._output_task and not self._output_task.done():
            self._output_task.cancel()
            try:
                await self._output_task
            except asyncio.CancelledError:
                pass


# Factory function to create appropriate terminal for platform
def create_terminal(
    session_id: str,
    working_directory: str,
    websocket_manager: "WebSocketManager | None" = None,
    shell: str | None = None,
) -> BaseTerminal:
    """Create a terminal appropriate for the current platform.

    Args:
        session_id: Session identifier.
        working_directory: Initial working directory.
        websocket_manager: WebSocket manager.
        shell: Shell to use.

    Returns:
        BaseTerminal instance.
    """
    if IS_WINDOWS:
        return WindowsTerminal(
            session_id=session_id,
            working_directory=working_directory,
            websocket_manager=websocket_manager,
            shell=shell,  # nosec B604 - shell is the executable path, not shell=True
        )
    else:
        return UnixPtyTerminal(
            session_id=session_id,
            working_directory=working_directory,
            websocket_manager=websocket_manager,
            shell=shell,  # nosec B604 - shell is the executable path, not shell=True
        )


# Alias for backwards compatibility
PtyTerminal = UnixPtyTerminal if not IS_WINDOWS else WindowsTerminal


class PtyTerminalManager:
    """Manager for multiple PTY terminal sessions."""

    def __init__(self, websocket_manager: "WebSocketManager | None" = None):
        """Initialize the terminal manager.

        Args:
            websocket_manager: WebSocket manager.
        """
        self.websocket_manager = websocket_manager
        self._terminals: dict[str, BaseTerminal] = {}
        self._cleanup_lock = asyncio.Lock()

    def set_websocket_manager(self, manager: "WebSocketManager") -> None:
        """Set the WebSocket manager."""
        self.websocket_manager = manager
        for terminal in self._terminals.values():
            terminal.websocket_manager = manager

    async def create_terminal(
        self,
        session_id: str,
        working_directory: str,
        cols: int | None = None,
        rows: int | None = None,
        shell: str | None = None,
    ) -> BaseTerminal | None:
        """Create and start a new terminal session.

        Args:
            session_id: Session identifier.
            working_directory: Initial working directory.
            cols: Terminal width.
            rows: Terminal height.
            shell: Shell to use.

        Returns:
            BaseTerminal instance or None.
        """
        # Check for existing terminal
        if session_id in self._terminals:
            existing = self._terminals[session_id]
            if existing.is_running:
                logger.warning(f"Terminal already exists for {session_id}")
                return existing
            else:
                await self.terminate_terminal(session_id)

        terminal = create_terminal(
            session_id=session_id,
            working_directory=working_directory,
            websocket_manager=self.websocket_manager,
            shell=shell,  # nosec B604 - shell is the executable path, not shell=True
        )

        if await terminal.start(cols=cols, rows=rows):
            self._terminals[session_id] = terminal
            return terminal

        return None

    def get_terminal(self, session_id: str) -> BaseTerminal | None:
        """Get terminal by session ID."""
        return self._terminals.get(session_id)

    async def terminate_terminal(self, session_id: str, force: bool = False) -> bool:
        """Terminate a terminal session."""
        async with self._cleanup_lock:
            terminal = self._terminals.pop(session_id, None)
            if terminal:
                await terminal.terminate(force=force)
                return True
            return False

    async def cleanup_all(self) -> None:
        """Terminate all terminals."""
        async with self._cleanup_lock:
            for session_id in list(self._terminals.keys()):
                terminal = self._terminals.pop(session_id, None)
                if terminal:
                    await terminal.terminate(force=True)

    def get_active_sessions(self) -> list[str]:
        """Get list of active session IDs."""
        return [sid for sid, terminal in self._terminals.items() if terminal.is_running]

    def get_all_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all terminals."""
        return {sid: terminal.get_status() for sid, terminal in self._terminals.items()}
