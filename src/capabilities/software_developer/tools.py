"""Async tool implementations for the Software Developer capability.

This module provides async-native tool implementations for file operations,
git operations, code analysis, and command execution with interactive input support.
"""

import ast
import asyncio
import errno
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import git
from loguru import logger

if TYPE_CHECKING:
    from src.managers.connection import WebSocketManager

# Platform detection
IS_WINDOWS = sys.platform == "win32"

# Platform-specific imports for Unix PTY
if not IS_WINDOWS:
    import fcntl
    import pty
    import select
    import struct
    import termios


# =============================================================================
# EXCEPTIONS
# =============================================================================


class CommandExecutorError(Exception):
    """Base exception for command executor errors."""


class PTYCreationError(CommandExecutorError):
    """Failed to create PTY."""


class ProcessStartError(CommandExecutorError):
    """Failed to start process."""


class ProcessNotFoundError(CommandExecutorError):
    """Process not found."""


class InputError(CommandExecutorError):
    """Error sending input to process."""


# =============================================================================
# DATA CLASSES
# =============================================================================


class ProcessState(Enum):
    """Process execution states."""

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class PTYProcess:
    """Container for PTY process information."""

    process_id: str
    command: str
    working_dir: str
    master_fd: int
    process: subprocess.Popen
    state: ProcessState = ProcessState.STARTING
    input_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    output_buffer: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    exit_code: int | None = None

    def __post_init__(self):
        """Initialize queue if not provided."""
        if self.input_queue is None:
            self.input_queue = asyncio.Queue()
        if self.output_buffer is None:
            self.output_buffer = []


# =============================================================================
# COMMAND EXECUTOR
# =============================================================================


class InteractiveCommandExecutor:
    """Production-ready async command executor with PTY-based terminal support.

    Features:
    - PTY-based execution for true terminal emulation (Unix) with subprocess fallback (Windows)
    - Real-time output streaming to WebSocket/xterm.js
    - Full interactive input support (keyboard shortcuts, Ctrl+C, etc.)
    - Automatic terminal display on frontend when commands execute
    - Proper resource cleanup and error handling
    - Thread-safe async operations
    """

    # Configuration constants
    READ_CHUNK_SIZE = 4096
    OUTPUT_READ_INTERVAL = 0.01
    TERMINATION_TIMEOUT = 5.0
    FORCE_KILL_TIMEOUT = 2.0
    DEFAULT_COLS = 120
    DEFAULT_ROWS = 30
    MAX_INPUT_QUEUE_SIZE = 1000

    def __init__(
        self,
        session_id: str,
        working_directory: str,
        websocket_manager: "WebSocketManager | None" = None,
        timeout: int = 120,
    ):
        """Initialize the interactive command executor.

        Args:
            session_id: Session identifier for WebSocket communication.
            working_directory: Base directory for command execution.
            websocket_manager: Optional WebSocket manager for streaming output.
            timeout: Default command timeout in seconds.

        Raises:
            ValueError: If session_id is empty or working_directory doesn't exist.
        """
        if not session_id:
            raise ValueError("session_id cannot be empty")

        self.session_id = session_id
        self.working_directory = os.path.abspath(working_directory)
        self.websocket_manager = websocket_manager
        self.default_timeout = max(1, timeout)  # Minimum 1 second

        # Ensure working directory exists
        os.makedirs(self.working_directory, exist_ok=True)

        # Process management with thread-safe lock
        self._processes: dict[str, PTYProcess] = {}
        self._tasks: dict[str, list[asyncio.Task]] = {}
        self._futures: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

        # Current process tracking
        self._current_process_id: str | None = None

        # Terminal dimensions
        self.cols = self.DEFAULT_COLS
        self.rows = self.DEFAULT_ROWS

        logger.debug(
            f"CommandExecutor initialized: session={session_id}, "
            f"working_dir={self.working_directory}"
        )

    def set_websocket_manager(self, manager: "WebSocketManager") -> None:
        """Set the WebSocket manager for streaming.

        Args:
            manager: WebSocket manager instance.
        """
        self.websocket_manager = manager
        logger.debug(f"WebSocket manager set for session {self.session_id}")

    def set_terminal_size(self, cols: int, rows: int) -> None:
        """Set terminal dimensions for new commands.

        Args:
            cols: Terminal width in columns (min: 10, max: 500).
            rows: Terminal height in rows (min: 5, max: 200).
        """
        self.cols = max(10, min(500, cols))
        self.rows = max(5, min(200, rows))

    # =========================================================================
    # WEBSOCKET STREAMING
    # =========================================================================

    async def _stream_message(self, message: dict[str, Any]) -> None:
        """Stream a message to WebSocket clients.

        Args:
            message: Message dictionary to send.
        """
        if self.websocket_manager is None:
            return

        try:
            await self.websocket_manager.send_chat_message(
                session_id=self.session_id,
                content=message,
                source="command_executor",
            )
        except Exception as e:
            logger.warning(f"Failed to stream message: {e}")

    async def _notify_terminal_start(
        self, proc: PTYProcess, cols: int, rows: int
    ) -> None:
        """Notify frontend that command terminal is starting."""
        await self._stream_message(
            {
                "type": "command_terminal_start",
                "process_id": proc.process_id,
                "pid": proc.process.pid,
                "command": proc.command,
                "working_dir": proc.working_dir,
                "cols": cols,
                "rows": rows,
                "timestamp": time.time(),
            }
        )

    async def _notify_terminal_output(self, process_id: str, data: str) -> None:
        """Stream terminal output to frontend."""
        await self._stream_message(
            {
                "type": "terminal_output",
                "process_id": process_id,
                "data": data,
                "timestamp": time.time(),
            }
        )

    async def _notify_terminal_end(
        self, process_id: str, exit_code: int, state: ProcessState
    ) -> None:
        """Notify frontend that command terminal has ended."""
        await self._stream_message(
            {
                "type": "command_terminal_end",
                "process_id": process_id,
                "exit_code": exit_code,
                "state": state.value,
                "timestamp": time.time(),
            }
        )

    async def _notify_error(self, process_id: str, error: str) -> None:
        """Notify frontend of an error."""
        await self._stream_message(
            {
                "type": "command_error",
                "process_id": process_id,
                "error": error,
                "timestamp": time.time(),
            }
        )

    # =========================================================================
    # PTY MANAGEMENT (Unix)
    # =========================================================================

    def _set_pty_size(self, fd: int, cols: int, rows: int) -> bool:
        """Set terminal size on a PTY file descriptor.

        Args:
            fd: File descriptor.
            cols: Column count.
            rows: Row count.

        Returns:
            True if successful, False otherwise.
        """
        if IS_WINDOWS:
            return False

        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
            return True
        except OSError as e:
            logger.debug(f"Failed to set PTY size: {e}")
            return False

    def _create_pty_pair(self) -> tuple[int, int]:
        """Create a PTY master/slave pair.

        Returns:
            Tuple of (master_fd, slave_fd).

        Raises:
            PTYCreationError: If PTY creation fails.
        """
        try:
            master_fd, slave_fd = pty.openpty()
            return master_fd, slave_fd
        except OSError as e:
            raise PTYCreationError(f"Failed to create PTY: {e}") from e

    def _configure_master_fd(self, master_fd: int) -> None:
        """Configure master FD for non-blocking I/O.

        Args:
            master_fd: Master file descriptor.

        Raises:
            PTYCreationError: If configuration fails.
        """
        try:
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        except OSError as e:
            raise PTYCreationError(f"Failed to configure PTY: {e}") from e

    def _build_environment(self, cols: int, rows: int) -> dict[str, str]:
        """Build environment variables for PTY process.

        Args:
            cols: Terminal columns.
            rows: Terminal rows.

        Returns:
            Environment dictionary.
        """
        env = os.environ.copy()
        env.update(
            {
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "PYTHONUNBUFFERED": "1",
                "COLUMNS": str(cols),
                "LINES": str(rows),
                "LANG": env.get("LANG", "en_US.UTF-8"),
                "LC_ALL": env.get("LC_ALL", "en_US.UTF-8"),
            }
        )
        return env

    def _close_fd_safe(self, fd: int | None) -> None:
        """Safely close a file descriptor.

        Args:
            fd: File descriptor to close.
        """
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    # =========================================================================
    # COMMAND EXECUTION
    # =========================================================================

    async def execute_command(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """Execute a shell command with PTY-based interactive terminal support.

        The command runs in a pseudo-terminal, and the frontend terminal
        is automatically shown so users can interact with it live.

        Args:
            command: The shell command to execute.
            working_dir: Optional working directory override.
            timeout: Optional timeout override in seconds.

        Returns:
            Command output as string with exit code.

        Raises:
            ValueError: If command is empty.
        """
        # Validate input
        if not command or not command.strip():
            return "Error: Command cannot be empty"

        # Use Windows fallback if needed
        if IS_WINDOWS:
            return await self._execute_windows(command, working_dir, timeout)

        return await self._execute_pty(command, working_dir, timeout)

    async def _execute_pty(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """Execute command using PTY (Unix systems).

        Args:
            command: Shell command to execute.
            working_dir: Working directory override.
            timeout: Timeout in seconds.

        Returns:
            Command output with exit code.
        """
        # Generate unique process ID
        process_id = f"cmd_{int(time.time() * 1000)}_{hash(command) % 10000:04d}"
        cwd = working_dir or self.working_directory
        exec_timeout = timeout or self.default_timeout

        # Validate working directory
        if not os.path.isdir(cwd):
            logger.warning(f"Working directory doesn't exist, using default: {cwd}")
            cwd = self.working_directory

        master_fd: int | None = None
        slave_fd: int | None = None
        proc: PTYProcess | None = None
        input_task: asyncio.Task | None = None
        output_task: asyncio.Task | None = None

        try:
            # Create PTY
            try:
                master_fd, slave_fd = self._create_pty_pair()
            except PTYCreationError as e:
                logger.error(f"PTY creation failed: {e}")
                await self._notify_error(process_id, str(e))
                return f"Error: Failed to create terminal - {e}"

            # Configure PTY
            try:
                self._set_pty_size(slave_fd, self.cols, self.rows)
                self._configure_master_fd(master_fd)
            except PTYCreationError as e:
                logger.error(f"PTY configuration failed: {e}")
                self._close_fd_safe(master_fd)
                self._close_fd_safe(slave_fd)
                await self._notify_error(process_id, str(e))
                return f"Error: Failed to configure terminal - {e}"

            # Build environment and start process
            env = self._build_environment(self.cols, self.rows)
            shell = os.environ.get("SHELL", "/bin/bash")

            try:
                process = subprocess.Popen(
                    [shell, "-c", command],
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    cwd=cwd,
                    env=env,
                    preexec_fn=os.setsid,
                    close_fds=True,
                )
            except OSError as e:
                logger.error(f"Failed to start process: {e}")
                self._close_fd_safe(master_fd)
                self._close_fd_safe(slave_fd)
                await self._notify_error(process_id, f"Failed to start process: {e}")
                return f"Error: Failed to start process - {e}"

            # Close slave FD in parent (child has it)
            self._close_fd_safe(slave_fd)
            slave_fd = None

            # Create process container
            proc = PTYProcess(
                process_id=process_id,
                command=command,
                working_dir=cwd,
                master_fd=master_fd,
                process=process,
                state=ProcessState.RUNNING,
            )

            # Register process
            async with self._lock:
                self._processes[process_id] = proc
                self._current_process_id = process_id

            # Notify frontend
            await self._notify_terminal_start(proc, self.cols, self.rows)

            logger.info(
                f"PTY command started: pid={process.pid}, "
                f"command={command[:50]}{'...' if len(command) > 50 else ''}"
            )

            # Create completion future
            future: asyncio.Future[int] = asyncio.Future()
            self._futures[process_id] = future

            # Start monitoring tasks
            output_task = asyncio.create_task(
                self._monitor_output(proc, future),
                name=f"output_{process_id}",
            )
            input_task = asyncio.create_task(
                self._monitor_input(proc),
                name=f"input_{process_id}",
            )

            async with self._lock:
                self._tasks[process_id] = [output_task, input_task]

            # Wait for completion
            exit_code: int
            final_state: ProcessState

            try:
                if exec_timeout > 0:
                    exit_code = await asyncio.wait_for(
                        future, timeout=float(exec_timeout)
                    )
                    final_state = ProcessState.COMPLETED
                else:
                    exit_code = await future
                    final_state = ProcessState.COMPLETED

            except TimeoutError:
                logger.warning(f"Command timed out after {exec_timeout}s: {process_id}")
                await self._terminate_process(proc)
                exit_code = 124
                final_state = ProcessState.TIMEOUT

            except asyncio.CancelledError:
                logger.info(f"Command cancelled: {process_id}")
                await self._terminate_process(proc)
                exit_code = 130
                final_state = ProcessState.CANCELLED

            # Update process state
            proc.state = final_state
            proc.exit_code = exit_code

            # Clean up tasks
            await self._cancel_tasks(process_id, input_task, output_task)

            # Notify frontend
            await self._notify_terminal_end(process_id, exit_code, final_state)

            # Get output
            output = "".join(proc.output_buffer)

            # Clean up
            await self._cleanup_process(process_id)

            return f"Exit code: {exit_code}\n{output.strip()}"

        except Exception as e:
            logger.exception(f"Unexpected error executing command: {e}")
            await self._notify_error(process_id, str(e))

            # Emergency cleanup
            self._close_fd_safe(slave_fd)
            if proc:
                await self._cleanup_process(process_id)
            elif master_fd is not None:
                self._close_fd_safe(master_fd)

            return f"Error: {e}"

        finally:
            async with self._lock:
                if self._current_process_id == process_id:
                    self._current_process_id = None

    async def _execute_windows(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """Execute command using subprocess (Windows fallback).

        Args:
            command: Shell command to execute.
            working_dir: Working directory override.
            timeout: Timeout in seconds.

        Returns:
            Command output with exit code.
        """
        process_id = f"cmd_{int(time.time() * 1000)}_{hash(command) % 10000:04d}"
        cwd = working_dir or self.working_directory
        exec_timeout = timeout or self.default_timeout

        async with self._lock:
            self._current_process_id = process_id

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            # Notify frontend
            await self._stream_message(
                {
                    "type": "command_terminal_start",
                    "process_id": process_id,
                    "pid": process.pid,
                    "command": command,
                    "working_dir": cwd,
                    "cols": self.cols,
                    "rows": self.rows,
                    "timestamp": time.time(),
                }
            )

            exit_code: int
            stdout: bytes
            stderr: bytes

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=float(exec_timeout)
                )
                exit_code = process.returncode or 0
            except TimeoutError:
                process.kill()
                await process.wait()
                exit_code = 124
                stdout, stderr = b"", b"Command timed out"

            # Stream output to frontend
            if stdout:
                await self._notify_terminal_output(
                    process_id, stdout.decode("utf-8", errors="replace")
                )
            if stderr:
                await self._notify_terminal_output(
                    process_id, stderr.decode("utf-8", errors="replace")
                )

            # Notify end
            await self._notify_terminal_end(
                process_id, exit_code, ProcessState.COMPLETED
            )

            # Build output
            output_parts = []
            if stderr:
                output_parts.append(stderr.decode("utf-8", errors="replace"))
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            return f"Exit code: {exit_code}\n{chr(10).join(output_parts).strip()}"

        except Exception as e:
            logger.exception(f"Windows command execution failed: {e}")
            await self._notify_error(process_id, str(e))
            return f"Error: {e}"

        finally:
            async with self._lock:
                if self._current_process_id == process_id:
                    self._current_process_id = None

    # =========================================================================
    # OUTPUT MONITORING
    # =========================================================================

    async def _monitor_output(self, proc: PTYProcess, future: asyncio.Future) -> None:
        """Monitor PTY output and stream to WebSocket.

        Args:
            proc: PTY process container.
            future: Future to resolve with exit code.
        """
        loop = asyncio.get_event_loop()
        master_fd = proc.master_fd

        try:
            while proc.state == ProcessState.RUNNING:
                try:
                    # Check for readable data
                    readable, _, _ = await loop.run_in_executor(
                        None,
                        lambda fd=master_fd: select.select([fd], [], [], 0.1),
                    )

                    if master_fd in readable:
                        await self._read_and_stream_output(proc)

                    # Check process status
                    retcode = proc.process.poll()
                    if retcode is not None:
                        # Drain remaining output
                        await self._drain_remaining_output(proc)

                        if not future.done():
                            future.set_result(retcode)
                        return

                    await asyncio.sleep(self.OUTPUT_READ_INTERVAL)

                except asyncio.CancelledError:
                    raise
                except OSError as e:
                    if e.errno in (errno.EIO, errno.EBADF):
                        # Terminal closed
                        break
                    logger.debug(f"Output read error: {e}")
                except Exception as e:
                    logger.debug(f"Output monitor error: {e}")
                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            pass
        finally:
            # Ensure future is resolved
            if not future.done():
                retcode = proc.process.poll()
                future.set_result(retcode if retcode is not None else -1)

    async def _read_and_stream_output(self, proc: PTYProcess) -> None:
        """Read output from PTY and stream to frontend.

        Args:
            proc: PTY process container.
        """
        try:
            data = os.read(proc.master_fd, self.READ_CHUNK_SIZE)
            if data:
                decoded = data.decode("utf-8", errors="replace")
                proc.output_buffer.append(decoded)
                await self._notify_terminal_output(proc.process_id, decoded)
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise

    async def _drain_remaining_output(self, proc: PTYProcess) -> None:
        """Drain any remaining output from PTY after process exit.

        Args:
            proc: PTY process container.
        """
        try:
            for _ in range(100):  # Max iterations to prevent infinite loop
                readable, _, _ = select.select([proc.master_fd], [], [], 0.01)
                if proc.master_fd not in readable:
                    break

                data = os.read(proc.master_fd, self.READ_CHUNK_SIZE)
                if not data:
                    break

                decoded = data.decode("utf-8", errors="replace")
                proc.output_buffer.append(decoded)
                await self._notify_terminal_output(proc.process_id, decoded)
        except OSError:
            pass

    # =========================================================================
    # INPUT HANDLING
    # =========================================================================

    async def _monitor_input(self, proc: PTYProcess) -> None:
        """Monitor input queue and write to PTY.

        Args:
            proc: PTY process container.
        """
        try:
            while proc.state == ProcessState.RUNNING:
                try:
                    # Wait for input with timeout
                    data = await asyncio.wait_for(proc.input_queue.get(), timeout=0.5)

                    if data is None:  # Sentinel to stop
                        break

                    # Write to PTY
                    await self._write_to_pty(proc, data)

                except TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug(f"Input handler error: {e}")

        except asyncio.CancelledError:
            pass

    async def _write_to_pty(self, proc: PTYProcess, data: str | bytes) -> bool:
        """Write data to PTY.

        Args:
            proc: PTY process container.
            data: Data to write.

        Returns:
            True if write succeeded.
        """
        try:
            if isinstance(data, str):
                data = data.encode("utf-8")

            os.write(proc.master_fd, data)
            return True

        except OSError as e:
            if e.errno == errno.EIO:
                logger.debug("PTY closed, cannot write")
            else:
                logger.debug(f"PTY write error: {e}")
            return False

    def provide_input(self, process_id: str | None, user_input: str | bytes) -> bool:
        """Provide input to a running PTY process.

        This queues input to be written to the PTY, enabling real-time
        interaction with the running command.

        Args:
            process_id: Process identifier (or None to use current).
            user_input: The input to provide (raw keystrokes or text).

        Returns:
            True if input was queued successfully.
        """
        if not user_input:
            return False

        target_id = process_id or self._current_process_id
        if not target_id:
            logger.debug("No active process for input")
            return False

        proc = self._processes.get(target_id)
        if not proc:
            logger.debug(f"Process not found: {target_id}")
            return False

        if proc.state != ProcessState.RUNNING:
            logger.debug(f"Process not running: {target_id} (state={proc.state})")
            return False

        try:
            proc.input_queue.put_nowait(user_input)
            return True
        except asyncio.QueueFull:
            logger.warning(f"Input queue full for: {target_id}")
            return False

    # =========================================================================
    # PROCESS TERMINATION
    # =========================================================================

    async def _terminate_process(self, proc: PTYProcess) -> None:
        """Terminate a PTY process gracefully.

        Args:
            proc: PTY process to terminate.
        """
        if proc.process.poll() is not None:
            return

        proc.state = ProcessState.STOPPING
        pid = proc.process.pid

        try:
            # Try graceful termination first
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.process.terminate()

            # Wait for termination
            try:
                proc.process.wait(timeout=self.TERMINATION_TIMEOUT)
                logger.debug(f"Process {pid} terminated gracefully")
                return
            except subprocess.TimeoutExpired:
                pass

            # Force kill
            logger.warning(f"Force killing process {pid}")
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.process.kill()

            proc.process.wait(timeout=self.FORCE_KILL_TIMEOUT)

        except Exception as e:
            logger.error(f"Error terminating process {pid}: {e}")

    async def _cancel_tasks(
        self,
        process_id: str,
        input_task: asyncio.Task | None,
        output_task: asyncio.Task | None,
    ) -> None:
        """Cancel monitoring tasks.

        Args:
            process_id: Process identifier.
            input_task: Input monitoring task.
            output_task: Output monitoring task.
        """
        for task in [input_task, output_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except (asyncio.CancelledError, TimeoutError):
                    pass

    async def _cleanup_process(self, process_id: str) -> None:
        """Clean up process resources.

        Args:
            process_id: Process identifier.
        """
        async with self._lock:
            proc = self._processes.pop(process_id, None)
            if proc:
                self._close_fd_safe(proc.master_fd)

            self._futures.pop(process_id, None)
            self._tasks.pop(process_id, None)

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    async def terminate_process(self, process_id: str) -> bool:
        """Terminate a specific process.

        Args:
            process_id: Process identifier.

        Returns:
            True if process was terminated.
        """
        proc = self._processes.get(process_id)
        if not proc:
            return False

        try:
            await self._terminate_process(proc)
            await self._cleanup_process(process_id)
            return True
        except Exception as e:
            logger.error(f"Error terminating process {process_id}: {e}")
            return False

    async def cleanup_all(self) -> None:
        """Clean up all processes."""
        process_ids = list(self._processes.keys())
        for process_id in process_ids:
            await self.terminate_process(process_id)

    def get_active_processes(self) -> list[str]:
        """Get list of active process IDs.

        Returns:
            List of process IDs.
        """
        return [
            pid
            for pid, proc in self._processes.items()
            if proc.state == ProcessState.RUNNING
        ]

    def has_pending_input(self) -> bool:
        """Check if any process is running.

        Returns:
            True if a process is running.
        """
        return any(
            proc.state == ProcessState.RUNNING for proc in self._processes.values()
        )

    def get_current_process_id(self) -> str | None:
        """Get the currently executing process ID.

        Returns:
            Current process ID or None.
        """
        return self._current_process_id

    def resize_pty(self, process_id: str, cols: int, rows: int) -> bool:
        """Resize a PTY terminal.

        Args:
            process_id: Process identifier.
            cols: New column count.
            rows: New row count.

        Returns:
            True if resize was successful.
        """
        if IS_WINDOWS:
            return False

        proc = self._processes.get(process_id)
        if not proc or proc.state != ProcessState.RUNNING:
            return False

        # Set size
        if not self._set_pty_size(proc.master_fd, cols, rows):
            return False

        # Send SIGWINCH
        try:
            pgid = os.getpgid(proc.process.pid)
            os.killpg(pgid, signal.SIGWINCH)
        except (ProcessLookupError, PermissionError, OSError):
            pass

        return True

    # Legacy method name for backwards compatibility
    async def cleanup(self) -> None:
        """Alias for cleanup_all."""
        await self.cleanup_all()

    # Legacy stream method
    async def stream_action(self, action_data: dict[str, Any]) -> None:
        """Legacy method - use _stream_message instead."""
        await self._stream_message(action_data)

    async def send_input_to_process(self, process_id: str, input_text: str) -> bool:
        """Send input directly to a running PTY process.

        Args:
            process_id: Process identifier.
            input_text: The input text to send.

        Returns:
            True if input was sent successfully.
        """
        return self.provide_input(process_id, input_text)


class AsyncToolRegistry:
    """Registry for async tool handlers with execution support."""

    def __init__(
        self,
        working_directory: str = ".",
        session_id: str | None = None,
        websocket_manager: "WebSocketManager | None" = None,
    ):
        """Initialize the tool registry.

        Args:
            working_directory: Base directory for file operations.
            session_id: Session identifier for command execution.
            websocket_manager: WebSocket manager for streaming output.
        """
        self.working_directory = os.path.abspath(working_directory)
        self.session_id = session_id or "default"
        self._tools: dict[str, Callable] = {}

        # Create interactive command executor
        self.command_executor = InteractiveCommandExecutor(
            session_id=self.session_id,
            working_directory=self.working_directory,
            websocket_manager=websocket_manager,
        )

        self._register_all_tools()

    def set_websocket_manager(self, manager: "WebSocketManager") -> None:
        """Set the WebSocket manager for streaming."""
        self.command_executor.set_websocket_manager(manager)

    def provide_input(self, process_id: str | None, user_input: str) -> bool:
        """Provide input to a waiting process.

        Args:
            process_id: Process identifier (or None to use current).
            user_input: The input to provide.

        Returns:
            True if input was accepted.
        """
        return self.command_executor.provide_input(process_id, user_input)

    def has_pending_input(self) -> bool:
        """Check if any process is waiting for input."""
        return self.command_executor.has_pending_input()

    async def cleanup(self):
        """Clean up all resources."""
        await self.command_executor.cleanup_all()

    def _register_all_tools(self):
        """Register all available tools."""
        # File operations
        self._tools["read_file"] = self.read_file
        self._tools["write_file"] = self.write_file
        self._tools["list_directory"] = self.list_directory
        self._tools["create_directory"] = self.create_directory
        self._tools["delete_file"] = self.delete_file
        self._tools["move_file"] = self.move_file
        self._tools["copy_file"] = self.copy_file
        self._tools["file_info"] = self.file_info
        self._tools["read_file_lines"] = self.read_file_lines

        # Command execution
        self._tools["execute_command"] = self.execute_command
        self._tools["search_files"] = self.search_files

        # Git operations
        self._tools["git_status"] = self.git_status
        self._tools["git_diff"] = self.git_diff
        self._tools["git_commit"] = self.git_commit
        self._tools["git_log"] = self.git_log
        self._tools["git_branch"] = self.git_branch

        # Code analysis
        self._tools["find_definition"] = self.find_definition
        self._tools["list_functions"] = self.list_functions
        self._tools["analyze_imports"] = self.analyze_imports
        self._tools["summarize_codebase"] = self.summarize_codebase

        # Development tools
        self._tools["run_tests"] = self.run_tests
        self._tools["format_code"] = self.format_code

    async def execute(self, tool_name: str, **kwargs) -> str:
        """Execute a tool by name asynchronously.

        Args:
            tool_name: Name of the tool to execute.
            **kwargs: Tool-specific arguments.

        Returns:
            Tool execution result as string.
        """
        if tool_name not in self._tools:
            return f"Unknown tool: {tool_name}"

        try:
            tool_func = self._tools[tool_name]
            if asyncio.iscoroutinefunction(tool_func):
                return await tool_func(**kwargs)
            else:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: tool_func(**kwargs))
        except Exception as e:
            logger.error(f"Error executing {tool_name}: {e}")
            return f"Error executing {tool_name}: {str(e)}"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions for the Anthropic API."""
        return TOOL_DEFINITIONS

    # =========================================================================
    # File Operations
    # =========================================================================

    def read_file(self, path: str) -> str:
        """Read file contents."""
        try:
            full_path = self._resolve_path(path)
            with open(full_path, encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {str(e)}"

    def write_file(self, path: str, content: str) -> str:
        """Write content to file."""
        try:
            full_path = self._resolve_path(path)
            os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"

    def list_directory(self, path: str = ".") -> str:
        """List directory contents."""
        try:
            full_path = self._resolve_path(path)
            items = os.listdir(full_path)
            result = []
            for item in sorted(items):
                item_path = os.path.join(full_path, item)
                if os.path.isdir(item_path):
                    result.append(f"[DIR]  {item}/")
                else:
                    size = os.path.getsize(item_path)
                    result.append(f"[FILE] {item} ({size} bytes)")
            return "\n".join(result) if result else "(empty directory)"
        except Exception as e:
            return f"Error listing directory: {str(e)}"

    def create_directory(self, path: str) -> str:
        """Create directory."""
        try:
            full_path = self._resolve_path(path)
            os.makedirs(full_path, exist_ok=True)
            return f"Created directory: {path}"
        except Exception as e:
            return f"Error creating directory: {str(e)}"

    def delete_file(self, path: str) -> str:
        """Delete file or directory."""
        try:
            full_path = self._resolve_path(path)
            if os.path.isdir(full_path):
                shutil.rmtree(full_path)
                return f"Deleted directory: {path}"
            else:
                os.remove(full_path)
                return f"Deleted file: {path}"
        except Exception as e:
            return f"Error deleting: {str(e)}"

    def move_file(self, source: str, destination: str) -> str:
        """Move or rename a file or directory."""
        try:
            src_path = self._resolve_path(source)
            dst_path = self._resolve_path(destination)
            shutil.move(src_path, dst_path)
            return f"Moved {source} to {destination}"
        except Exception as e:
            return f"Error moving file: {str(e)}"

    def copy_file(self, source: str, destination: str) -> str:
        """Copy a file or directory."""
        try:
            src_path = self._resolve_path(source)
            dst_path = self._resolve_path(destination)
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path)
                return f"Copied directory {source} to {destination}"
            else:
                shutil.copy2(src_path, dst_path)
                return f"Copied {source} to {destination}"
        except Exception as e:
            return f"Error copying file: {str(e)}"

    def file_info(self, path: str) -> str:
        """Get file metadata."""
        try:
            full_path = self._resolve_path(path)
            file_stat = os.stat(full_path)
            info = [
                f"Path: {os.path.abspath(full_path)}",
                f"Size: {file_stat.st_size} bytes",
                f"Permissions: {stat.filemode(file_stat.st_mode)}",
                f"Modified: {datetime.fromtimestamp(file_stat.st_mtime).isoformat()}",
                f"Created: {datetime.fromtimestamp(file_stat.st_ctime).isoformat()}",
                f"Is Directory: {os.path.isdir(full_path)}",
                f"Is File: {os.path.isfile(full_path)}",
            ]
            return "\n".join(info)
        except Exception as e:
            return f"Error getting file info: {str(e)}"

    def read_file_lines(self, path: str, start_line: int, end_line: int) -> str:
        """Read specific line ranges from a file."""
        try:
            full_path = self._resolve_path(path)
            with open(full_path, encoding="utf-8") as f:
                lines = f.readlines()

            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)

            result = []
            for i, line in enumerate(lines[start_idx:end_idx], start=start_line):
                result.append(f"{i:4d}: {line.rstrip()}")

            return "\n".join(result) if result else "No lines in range"
        except Exception as e:
            return f"Error reading file lines: {str(e)}"

    # =========================================================================
    # Command Execution
    # =========================================================================

    async def execute_command(
        self, command: str, working_dir: str | None = None, timeout: int = 120
    ) -> str:
        """Execute shell command with interactive input support."""
        cwd = self._resolve_path(working_dir) if working_dir else self.working_directory
        return await self.command_executor.execute_command(
            command=command,
            working_dir=cwd,
            timeout=timeout,
        )

    def search_files(
        self, pattern: str, path: str = ".", file_pattern: str | None = None
    ) -> str:
        """Search for pattern in files."""
        try:
            search_path = self._resolve_path(path)
            matches = []
            exclude_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv"}

            for root, dirs, files in os.walk(search_path):
                dirs[:] = [d for d in dirs if d not in exclude_dirs]

                for file in files:
                    if file_pattern and not Path(file).match(file_pattern):
                        continue

                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            if re.search(pattern, content, re.IGNORECASE):
                                lines = content.split("\n")
                                matching_lines = [
                                    (i + 1, line)
                                    for i, line in enumerate(lines)
                                    if re.search(pattern, line, re.IGNORECASE)
                                ]
                                rel_path = os.path.relpath(file_path, search_path)
                                matches.append(
                                    f"{rel_path}:\n"
                                    + "\n".join(
                                        [
                                            f"  Line {num}: {line.strip()}"
                                            for num, line in matching_lines[:5]
                                        ]
                                    )
                                )
                    except Exception:
                        continue

            return "\n\n".join(matches) if matches else "No matches found"
        except Exception as e:
            return f"Error searching files: {str(e)}"

    # =========================================================================
    # Git Operations
    # =========================================================================

    def git_status(self, path: str = ".") -> str:
        """Get git status."""
        try:
            repo_path = self._resolve_path(path)
            repo = git.Repo(repo_path, search_parent_directories=True)
            status = [f"Branch: {repo.active_branch.name}"]

            if repo.is_dirty():
                status.append("\nModified files:")
                for item in repo.index.diff(None):
                    status.append(f"  M {item.a_path}")

            untracked = repo.untracked_files
            if untracked:
                status.append("\nUntracked files:")
                for file in untracked[:20]:
                    status.append(f"  ? {file}")
                if len(untracked) > 20:
                    status.append(f"  ... and {len(untracked) - 20} more")

            if not repo.is_dirty() and not untracked:
                status.append("\nWorking tree clean")

            return "\n".join(status)
        except git.InvalidGitRepositoryError:
            return "Not a git repository"
        except Exception as e:
            return f"Error getting git status: {str(e)}"

    def git_diff(self, path: str = ".", cached: bool = False) -> str:
        """Get git diff."""
        try:
            repo_path = self._resolve_path(path)
            repo = git.Repo(repo_path, search_parent_directories=True)
            if cached:
                diff = repo.index.diff("HEAD")
            else:
                diff = repo.index.diff(None)

            if not diff:
                return "No changes"

            result = []
            for item in diff:
                result.append(f"\n=== {item.a_path} ===")
                if item.diff:
                    result.append(item.diff.decode("utf-8", errors="ignore"))

            return "\n".join(result)
        except Exception as e:
            return f"Error getting git diff: {str(e)}"

    def git_commit(self, message: str, path: str = ".") -> str:
        """Create git commit."""
        try:
            repo_path = self._resolve_path(path)
            repo = git.Repo(repo_path, search_parent_directories=True)
            repo.git.add(A=True)
            commit = repo.index.commit(message)
            return f"Created commit {commit.hexsha[:8]}: {message}"
        except Exception as e:
            return f"Error creating commit: {str(e)}"

    def git_log(self, path: str = ".", limit: int = 10) -> str:
        """View git commit history."""
        try:
            repo_path = self._resolve_path(path)
            repo = git.Repo(repo_path, search_parent_directories=True)
            commits = list(repo.iter_commits(max_count=limit))

            result = []
            for commit in commits:
                date = datetime.fromtimestamp(commit.committed_date).strftime(
                    "%Y-%m-%d %H:%M"
                )
                result.append(f"{commit.hexsha[:8]} - {date} - {commit.author.name}")
                result.append(f"    {commit.message.strip()[:80]}")
                result.append("")

            return "\n".join(result) if result else "No commits found"
        except git.InvalidGitRepositoryError:
            return "Not a git repository"
        except Exception as e:
            return f"Error getting git log: {str(e)}"

    def git_branch(
        self, path: str = ".", action: str = "list", branch_name: str | None = None
    ) -> str:
        """List, create, or switch branches."""
        try:
            repo_path = self._resolve_path(path)
            repo = git.Repo(repo_path, search_parent_directories=True)

            if action == "list":
                branches = []
                for branch in repo.branches:
                    prefix = "* " if branch == repo.active_branch else "  "
                    branches.append(f"{prefix}{branch.name}")
                return "\n".join(branches) if branches else "No branches found"

            elif action == "create":
                if not branch_name:
                    return "Error: branch_name required for create action"
                new_branch = repo.create_head(branch_name)
                return f"Created branch: {new_branch.name}"

            elif action == "switch":
                if not branch_name:
                    return "Error: branch_name required for switch action"
                repo.git.checkout(branch_name)
                return f"Switched to branch: {branch_name}"

            else:
                return f"Unknown action: {action}. Use 'list', 'create', or 'switch'"

        except git.InvalidGitRepositoryError:
            return "Not a git repository"
        except Exception as e:
            return f"Error with git branch: {str(e)}"

    # =========================================================================
    # Code Analysis
    # =========================================================================

    def find_definition(self, name: str, path: str = ".") -> str:
        """Find function or class definitions in files."""
        try:
            search_path = self._resolve_path(path)
            matches = []
            patterns = [
                rf"^\s*def\s+{re.escape(name)}\s*\(",
                rf"^\s*class\s+{re.escape(name)}\s*[:\(]",
                rf"^\s*async\s+def\s+{re.escape(name)}\s*\(",
            ]
            exclude_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv"}

            for root, dirs, files in os.walk(search_path):
                dirs[:] = [d for d in dirs if d not in exclude_dirs]

                for file in files:
                    if file.endswith((".py", ".js", ".ts", ".jsx", ".tsx")):
                        file_path = os.path.join(root, file)
                        try:
                            with open(
                                file_path, encoding="utf-8", errors="ignore"
                            ) as f:
                                lines = f.readlines()
                                for i, line in enumerate(lines, 1):
                                    for pattern in patterns:
                                        if re.match(pattern, line):
                                            rel_path = os.path.relpath(
                                                file_path, search_path
                                            )
                                            matches.append(
                                                f"{rel_path}:{i}: {line.strip()}"
                                            )
                        except Exception:
                            continue

            return (
                "\n".join(matches) if matches else f"No definition found for '{name}'"
            )
        except Exception as e:
            return f"Error finding definition: {str(e)}"

    def list_functions(self, path: str) -> str:
        """List all function and class definitions in a file."""
        try:
            full_path = self._resolve_path(path)
            with open(full_path, encoding="utf-8") as f:
                content = f.read()

            if path.endswith(".py"):
                try:
                    tree = ast.parse(content)
                    result = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            args = ", ".join(arg.arg for arg in node.args.args)
                            result.append(
                                f"  def {node.name}({args}) - line {node.lineno}"
                            )
                        elif isinstance(node, ast.AsyncFunctionDef):
                            args = ", ".join(arg.arg for arg in node.args.args)
                            result.append(
                                f"  async def {node.name}({args}) - line {node.lineno}"
                            )
                        elif isinstance(node, ast.ClassDef):
                            result.append(f"  class {node.name} - line {node.lineno}")
                    return (
                        f"Definitions in {path}:\n" + "\n".join(sorted(set(result)))
                        if result
                        else "No definitions found"
                    )
                except SyntaxError as e:
                    return f"Syntax error in file: {e}"
            else:
                patterns = [
                    (r"^\s*(async\s+)?function\s+(\w+)", "function"),
                    (r"^\s*class\s+(\w+)", "class"),
                    (
                        r"^\s*const\s+(\w+)\s*=\s*(\([^)]*\)|[^=]*)\s*=>",
                        "arrow function",
                    ),
                ]

                result = []
                lines = content.split("\n")
                for i, line in enumerate(lines, 1):
                    for pattern, kind in patterns:
                        match = re.match(pattern, line)
                        if match:
                            name = (
                                match.group(2) if kind == "function" else match.group(1)
                            )
                            result.append(f"  {kind} {name} - line {i}")

                return (
                    f"Definitions in {path}:\n" + "\n".join(result)
                    if result
                    else "No definitions found"
                )
        except Exception as e:
            return f"Error listing functions: {str(e)}"

    def analyze_imports(self, path: str) -> str:
        """List all imports/dependencies in a file."""
        try:
            full_path = self._resolve_path(path)
            with open(full_path, encoding="utf-8") as f:
                content = f.read()

            imports = []

            if path.endswith(".py"):
                try:
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imports.append(f"import {alias.name}")
                        elif isinstance(node, ast.ImportFrom):
                            module = node.module or ""
                            names = ", ".join(alias.name for alias in node.names)
                            imports.append(f"from {module} import {names}")
                except SyntaxError:
                    for line in content.split("\n"):
                        if re.match(r"^\s*(from|import)\s+", line):
                            imports.append(line.strip())
            else:
                patterns = [
                    r'^\s*import\s+.*?[\'"]([^\'"]+)[\'"]',
                    r'^\s*const\s+\w+\s*=\s*require\s*\([\'"]([^\'"]+)[\'"]\)',
                ]

                for line in content.split("\n"):
                    for pattern in patterns:
                        match = re.search(pattern, line)
                        if match:
                            imports.append(line.strip())
                            break

            return (
                f"Imports in {path}:\n" + "\n".join(sorted(set(imports)))
                if imports
                else "No imports found"
            )
        except Exception as e:
            return f"Error analyzing imports: {str(e)}"

    def summarize_codebase(self, path: str = ".", max_depth: int = 3) -> str:
        """Generate a summary of the project structure."""
        try:
            base_path = self._resolve_path(path)
            summary = []
            file_counts: dict[str, int] = {}
            total_files = 0

            important_files = [
                "README.md",
                "package.json",
                "requirements.txt",
                "pyproject.toml",
                "Makefile",
                "Dockerfile",
                "docker-compose.yml",
                ".gitignore",
            ]
            found_important = []
            exclude_dirs = {
                ".git",
                "node_modules",
                "__pycache__",
                ".venv",
                "venv",
                "dist",
                "build",
            }

            def explore(current_path: str, depth: int, prefix: str = ""):
                nonlocal total_files

                if depth > max_depth:
                    return

                try:
                    items = sorted(os.listdir(current_path))
                except PermissionError:
                    return

                dirs = []
                files = []

                for item in items:
                    if item.startswith(".") and item not in [
                        ".gitignore",
                        ".env.example",
                    ]:
                        continue
                    if item in exclude_dirs:
                        continue

                    full_path = os.path.join(current_path, item)

                    if os.path.isdir(full_path):
                        dirs.append(item)
                    else:
                        files.append(item)
                        total_files += 1

                        ext = Path(item).suffix or "no extension"
                        file_counts[ext] = file_counts.get(ext, 0) + 1

                        if item in important_files:
                            found_important.append(
                                os.path.relpath(full_path, base_path)
                            )

                for d in dirs:
                    summary.append(f"{prefix}[DIR] {d}/")
                    explore(os.path.join(current_path, d), depth + 1, prefix + "  ")

                for f in files[:10]:
                    summary.append(f"{prefix}[FILE] {f}")

                if len(files) > 10:
                    summary.append(f"{prefix}   ... and {len(files) - 10} more files")

            explore(base_path, 0)

            result = [f"=== Codebase Summary: {os.path.abspath(base_path)} ===\n"]

            if found_important:
                result.append("Key files found:")
                for f in found_important:
                    result.append(f"  - {f}")
                result.append("")

            result.append(f"Total files: {total_files}")
            result.append("\nFile types:")
            for ext, count in sorted(file_counts.items(), key=lambda x: -x[1])[:10]:
                result.append(f"  {ext}: {count}")

            result.append("\nStructure:")
            result.extend(summary[:50])

            if len(summary) > 50:
                result.append(f"\n... and more ({len(summary) - 50} items not shown)")

            return "\n".join(result)
        except Exception as e:
            return f"Error summarizing codebase: {str(e)}"

    # =========================================================================
    # Development Tools
    # =========================================================================

    async def run_tests(
        self, path: str = ".", framework: str = "auto", verbose: bool = False
    ) -> str:
        """Execute test suites asynchronously."""
        try:
            test_path = self._resolve_path(path)

            if framework == "auto":
                if os.path.exists(os.path.join(test_path, "package.json")):
                    framework = "npm"
                elif os.path.exists(
                    os.path.join(test_path, "pytest.ini")
                ) or os.path.exists(os.path.join(test_path, "pyproject.toml")):
                    framework = "pytest"
                else:
                    framework = "pytest"

            if framework == "pytest":
                cmd = f"python -m pytest {test_path}"
                if verbose:
                    cmd += " -v"
            elif framework == "npm":
                cmd = "npm test"
            elif framework == "jest":
                cmd = f"npx jest {test_path}"
                if verbose:
                    cmd += " --verbose"
            else:
                return f"Unknown framework: {framework}"

            return await self.execute_command(cmd, working_dir=test_path, timeout=300)

        except Exception as e:
            return f"Error running tests: {str(e)}"

    async def format_code(self, path: str, formatter: str | None = None) -> str:
        """Auto-format code using appropriate formatter."""
        try:
            full_path = self._resolve_path(path)

            if formatter is None:
                if path.endswith(".py"):
                    formatter = "black"
                elif path.endswith((".js", ".jsx", ".ts", ".tsx", ".json", ".md")):
                    formatter = "prettier"
                else:
                    formatter = "black"

            if formatter == "black":
                cmd = f"python -m black {full_path}"
            elif formatter == "prettier":
                cmd = f"npx prettier --write {full_path}"
            elif formatter == "autopep8":
                cmd = f"python -m autopep8 --in-place {full_path}"
            else:
                return f"Unknown formatter: {formatter}"

            return await self.execute_command(cmd, timeout=60)

        except Exception as e:
            return f"Error formatting code: {str(e)}"

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _resolve_path(self, path: str | None) -> str:
        """Resolve a path relative to the working directory."""
        if path is None:
            return self.working_directory
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.working_directory, path))


# Tool definitions for Anthropic API
TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns the file content as a string.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to read (relative or absolute)",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates the file if it doesn't exist, or overwrites it if it does.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List all files and directories in a given path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to list (defaults to current directory)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "execute_command",
        "description": "Execute a shell command and return its output. Supports interactive commands that require user input - the system will automatically detect input prompts and request input from the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "working_dir": {
                    "type": "string",
                    "description": "The working directory for the command (optional)",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for files containing specific text or patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The text or regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "The directory to search in (defaults to current directory)",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "File name pattern to filter (e.g., '*.py', '*.js')",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "git_status",
        "description": "Get the git status of the current repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The repository path (defaults to current directory)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "git_diff",
        "description": "Get the git diff for tracked changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The repository path (defaults to current directory)",
                },
                "cached": {
                    "type": "boolean",
                    "description": "Show staged changes instead of unstaged",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_commit",
        "description": "Stage all changes and create a git commit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The commit message",
                },
                "path": {
                    "type": "string",
                    "description": "The repository path (defaults to current directory)",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "git_log",
        "description": "View git commit history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The repository path (defaults to current directory)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of commits to show (default 10)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_branch",
        "description": "List, create, or switch branches.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The repository path (defaults to current directory)",
                },
                "action": {
                    "type": "string",
                    "description": "Action to perform: 'list', 'create', or 'switch'",
                },
                "branch_name": {
                    "type": "string",
                    "description": "Branch name (required for create/switch)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "create_directory",
        "description": "Create a new directory (including parent directories if needed).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to create",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file or directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to delete",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "move_file",
        "description": "Move or rename a file or directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "The source path",
                },
                "destination": {
                    "type": "string",
                    "description": "The destination path",
                },
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "copy_file",
        "description": "Copy a file or directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "The source path",
                },
                "destination": {
                    "type": "string",
                    "description": "The destination path",
                },
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "file_info",
        "description": "Get file metadata including size, permissions, and modification time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file_lines",
        "description": "Read specific line ranges from a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file",
                },
                "start_line": {
                    "type": "integer",
                    "description": "The starting line number (1-indexed)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "The ending line number (inclusive)",
                },
            },
            "required": ["path", "start_line", "end_line"],
        },
    },
    {
        "name": "find_definition",
        "description": "Find function or class definitions in files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The name of the function or class to find",
                },
                "path": {
                    "type": "string",
                    "description": "The directory to search in (defaults to current directory)",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_functions",
        "description": "List all function and class definitions in a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to analyze",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "analyze_imports",
        "description": "List all imports/dependencies in a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to analyze",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "summarize_codebase",
        "description": "Generate a summary of the project structure and key files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The project root path (defaults to current directory)",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum directory depth to explore (default 3)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "run_tests",
        "description": "Execute test suites (pytest, jest, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to test file or directory",
                },
                "framework": {
                    "type": "string",
                    "description": "Test framework: 'pytest', 'jest', 'npm', 'auto'",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Run in verbose mode",
                },
            },
            "required": [],
        },
    },
    {
        "name": "format_code",
        "description": "Auto-format code using appropriate formatter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to file or directory to format",
                },
                "formatter": {
                    "type": "string",
                    "description": "Formatter to use: 'black', 'prettier', 'autopep8'",
                },
            },
            "required": ["path"],
        },
    },
]


# =============================================================================
# LANGGRAPH TOOL WRAPPERS
# =============================================================================

from langchain_core.tools import tool as langgraph_tool


def create_langgraph_tools(tool_registry: "AsyncToolRegistry") -> list:
    """Create LangGraph-compatible tools from AsyncToolRegistry.

    Args:
        tool_registry: The AsyncToolRegistry instance with all tools.

    Returns:
        List of LangChain tool instances.
    """

    @langgraph_tool
    async def read_file(path: str) -> str:
        """Read the contents of a file.

        Args:
            path: The path to the file to read (relative or absolute).

        Returns:
            The file contents as string.
        """
        return tool_registry.read_file(path)

    @langgraph_tool
    async def write_file(path: str, content: str) -> str:
        """Write content to a file.

        Args:
            path: The path to the file to write.
            content: The content to write to the file.

        Returns:
            Success message or error message.
        """
        return tool_registry.write_file(path, content)

    @langgraph_tool
    async def list_directory(path: str = ".") -> str:
        """List all files and directories in a given path.

        Args:
            path: The directory path to list (defaults to current directory).

        Returns:
            Formatted list of files and directories.
        """
        return tool_registry.list_directory(path)

    @langgraph_tool
    async def create_directory(path: str) -> str:
        """Create a new directory.

        Args:
            path: The directory path to create.

        Returns:
            Success message or error message.
        """
        return tool_registry.create_directory(path)

    @langgraph_tool
    async def delete_file(path: str) -> str:
        """Delete a file or directory.

        Args:
            path: The path to delete.

        Returns:
            Success message or error message.
        """
        return tool_registry.delete_file(path)

    @langgraph_tool
    async def move_file(source: str, destination: str) -> str:
        """Move or rename a file or directory.

        Args:
            source: The source path.
            destination: The destination path.

        Returns:
            Success message or error message.
        """
        return tool_registry.move_file(source, destination)

    @langgraph_tool
    async def copy_file(source: str, destination: str) -> str:
        """Copy a file or directory.

        Args:
            source: The source path.
            destination: The destination path.

        Returns:
            Success message or error message.
        """
        return tool_registry.copy_file(source, destination)

    @langgraph_tool
    async def file_info(path: str) -> str:
        """Get file metadata including size, permissions, and modification time.

        Args:
            path: The path to the file.

        Returns:
            File metadata information.
        """
        return tool_registry.file_info(path)

    @langgraph_tool
    async def read_file_lines(path: str, start_line: int, end_line: int) -> str:
        """Read specific line ranges from a file.

        Args:
            path: The path to the file.
            start_line: The starting line number (1-indexed).
            end_line: The ending line number (inclusive).

        Returns:
            The requested lines with line numbers.
        """
        return tool_registry.read_file_lines(path, start_line, end_line)

    @langgraph_tool
    async def execute_command(command: str, working_dir: str = None, timeout: int = 120) -> str:
        """Execute a shell command with PTY-based interactive terminal support.

        The command runs in a pseudo-terminal with full interactivity support.

        Args:
            command: The shell command to execute.
            working_dir: Optional working directory for the command.
            timeout: Optional timeout in seconds (default 120).

        Returns:
            Command output with exit code.
        """
        return await tool_registry.execute_command(command, working_dir, timeout)

    @langgraph_tool
    async def search_files(pattern: str, path: str = ".", file_pattern: str = None) -> str:
        """Search for a text pattern in files.

        Args:
            pattern: The text or regex pattern to search for.
            path: The directory to search in (defaults to current directory).
            file_pattern: Optional file name pattern to filter (e.g., '*.py').

        Returns:
            Formatted search results showing matches with line numbers.
        """
        return tool_registry.search_files(pattern, path, file_pattern)

    @langgraph_tool
    async def git_status(path: str = ".") -> str:
        """Get the git status of the current repository.

        Args:
            path: The repository path (defaults to current directory).

        Returns:
            Git status information.
        """
        return tool_registry.git_status(path)

    @langgraph_tool
    async def git_diff(path: str = ".", cached: bool = False) -> str:
        """Get the git diff for tracked changes.

        Args:
            path: The repository path (defaults to current directory).
            cached: Show staged changes instead of unstaged.

        Returns:
            Git diff output.
        """
        return tool_registry.git_diff(path, cached)

    @langgraph_tool
    async def git_commit(message: str, path: str = ".") -> str:
        """Stage all changes and create a git commit.

        Args:
            message: The commit message.
            path: The repository path (defaults to current directory).

        Returns:
            Commit result message.
        """
        return tool_registry.git_commit(message, path)

    @langgraph_tool
    async def git_log(path: str = ".", limit: int = 10) -> str:
        """View git commit history.

        Args:
            path: The repository path (defaults to current directory).
            limit: Maximum number of commits to show (default 10).

        Returns:
            Git log output.
        """
        return tool_registry.git_log(path, limit)

    @langgraph_tool
    async def git_branch(path: str = ".", action: str = "list", branch_name: str = None) -> str:
        """List, create, or switch branches.

        Args:
            path: The repository path (defaults to current directory).
            action: Action to perform: 'list', 'create', or 'switch'.
            branch_name: Branch name (required for create/switch).

        Returns:
            Branch operation result.
        """
        return tool_registry.git_branch(path, action, branch_name)

    @langgraph_tool
    async def find_definition(name: str, path: str = ".") -> str:
        """Find function or class definitions in files.

        Args:
            name: The name of the function or class to find.
            path: The directory to search in (defaults to current directory).

        Returns:
            Matching definitions with file paths and line numbers.
        """
        return tool_registry.find_definition(name, path)

    @langgraph_tool
    async def list_functions(path: str) -> str:
        """List all function and class definitions in a file.

        Args:
            path: The path to the file to analyze.

        Returns:
            List of all definitions with line numbers.
        """
        return tool_registry.list_functions(path)

    @langgraph_tool
    async def analyze_imports(path: str) -> str:
        """List all imports/dependencies in a file.

        Args:
            path: The path to the file to analyze.

        Returns:
            List of all imports.
        """
        return tool_registry.analyze_imports(path)

    @langgraph_tool
    async def summarize_codebase(path: str = ".", max_depth: int = 3) -> str:
        """Generate a summary of the project structure and key files.

        Args:
            path: The project root path (defaults to current directory).
            max_depth: Maximum directory depth to explore (default 3).

        Returns:
            Codebase structure summary.
        """
        return tool_registry.summarize_codebase(path, max_depth)

    @langgraph_tool
    async def run_tests(path: str = ".", framework: str = "auto", verbose: bool = False) -> str:
        """Execute test suites (pytest, jest, etc.).

        Args:
            path: Path to test file or directory.
            framework: Test framework: 'pytest', 'jest', 'npm', 'auto' (default auto).
            verbose: Run in verbose mode.

        Returns:
            Test execution results.
        """
        return await tool_registry.run_tests(path, framework, verbose)

    @langgraph_tool
    async def format_code(path: str, formatter: str = None) -> str:
        """Auto-format code using appropriate formatter.

        Args:
            path: Path to file or directory to format.
            formatter: Formatter to use: 'black', 'prettier', 'autopep8' (default auto-detect).

        Returns:
            Formatting result message.
        """
        return await tool_registry.format_code(path, formatter)

    return [
        read_file,
        write_file,
        list_directory,
        create_directory,
        delete_file,
        move_file,
        copy_file,
        file_info,
        read_file_lines,
        execute_command,
        search_files,
        git_status,
        git_diff,
        git_commit,
        git_log,
        git_branch,
        find_definition,
        list_functions,
        analyze_imports,
        summarize_codebase,
        run_tests,
        format_code,
    ]
