"""Async tool implementations for the Software Developer capability.

This module provides async-native tool implementations for file operations,
git operations, code analysis, and command execution with interactive input support.
"""

import ast
import asyncio
import os
import pty
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
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
    import select
    import termios


class InteractiveCommandExecutor:
    """Async command executor with PTY-based interactive terminal support.

    This class handles command execution with:
    - PTY-based execution for true terminal emulation
    - Real-time output streaming to WebSocket/xterm.js
    - Full interactive input support (keyboard, Ctrl+C, etc.)
    - Automatic terminal display on frontend when commands execute
    """

    # Configuration constants
    STDIN_DRAIN_TIMEOUT = 5.0
    READ_CHUNK_SIZE = 4096
    READ_TIMEOUT = 0.05
    TERMINATION_GRACE_PERIOD = 5.0
    OUTPUT_READ_INTERVAL = 0.01
    DEFAULT_COLS = 120
    DEFAULT_ROWS = 30

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
        """
        self.session_id = session_id
        self.working_directory = os.path.abspath(working_directory)
        self.websocket_manager = websocket_manager
        self.default_timeout = timeout

        # PTY process management
        self._active_pty: dict[str, dict[str, Any]] = {}  # process_id -> {master_fd, process, ...}
        self._execution_futures: dict[str, asyncio.Future] = {}
        self._output_tasks: dict[str, asyncio.Task] = {}
        self._cleanup_lock = asyncio.Lock()

        # Input handling - pending writes to PTY
        self._pending_input: dict[str, asyncio.Queue] = {}
        self._current_process_id: str | None = None

        # Terminal dimensions
        self.cols = self.DEFAULT_COLS
        self.rows = self.DEFAULT_ROWS

    def set_websocket_manager(self, manager: "WebSocketManager") -> None:
        """Set the WebSocket manager for streaming."""
        self.websocket_manager = manager

    def set_terminal_size(self, cols: int, rows: int) -> None:
        """Set terminal dimensions for new commands."""
        self.cols = cols
        self.rows = rows

    async def stream_action(self, action_data: dict[str, Any]) -> None:
        """Stream action to WebSocket clients."""
        if self.websocket_manager is None:
            return

        try:
            await self.websocket_manager.send_chat_message(
                session_id=self.session_id,
                content=action_data,
                source="command_executor",
            )
        except Exception as e:
            logger.debug(f"Error streaming action: {e}")

    def _set_pty_size(self, fd: int, cols: int, rows: int) -> None:
        """Set terminal size on a PTY file descriptor."""
        if IS_WINDOWS:
            return
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
        except Exception as e:
            logger.debug(f"Failed to set PTY size: {e}")

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
            Command output as string.
        """
        if IS_WINDOWS:
            # Fall back to subprocess on Windows
            return await self._execute_command_subprocess(command, working_dir, timeout)

        process_id = f"cmd_{int(time.time() * 1000)}_{id(command) % 10000}"
        self._current_process_id = process_id
        cwd = working_dir if working_dir else self.working_directory
        exec_timeout = timeout if timeout else self.default_timeout

        master_fd = None
        slave_fd = None
        process = None
        collected_output: list[str] = []

        try:
            # Create PTY master/slave pair
            master_fd, slave_fd = pty.openpty()

            # Set terminal size
            self._set_pty_size(slave_fd, self.cols, self.rows)

            # Set master to non-blocking
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            # Set up environment
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLORTERM"] = "truecolor"
            env["PYTHONUNBUFFERED"] = "1"
            env["COLUMNS"] = str(self.cols)
            env["LINES"] = str(self.rows)

            # Get shell
            shell = os.environ.get("SHELL", "/bin/bash")

            # Start process with PTY
            import subprocess
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

            # Close slave FD in parent - child has it
            os.close(slave_fd)
            slave_fd = None

            # Store PTY info
            self._active_pty[process_id] = {
                "master_fd": master_fd,
                "process": process,
                "command": command,
            }

            # Create input queue for this process
            self._pending_input[process_id] = asyncio.Queue()

            # Notify frontend to show terminal
            await self.stream_action(
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

            logger.info(f"PTY command started: {command[:50]}... (pid={process.pid})")

            # Create execution future
            execution_future: asyncio.Future[int] = asyncio.Future()
            self._execution_futures[process_id] = execution_future

            # Start output monitoring task
            output_task = asyncio.create_task(
                self._monitor_pty_output(
                    master_fd, process, process_id, collected_output, execution_future
                )
            )
            self._output_tasks[process_id] = output_task

            # Start input handling task
            input_task = asyncio.create_task(
                self._handle_pty_input(master_fd, process_id)
            )

            # Wait for completion with timeout
            try:
                if exec_timeout > 0:
                    return_code = await asyncio.wait_for(
                        execution_future, timeout=float(exec_timeout)
                    )
                else:
                    return_code = await execution_future

            except TimeoutError:
                await self.stream_action(
                    {
                        "type": "command_timeout",
                        "process_id": process_id,
                        "timeout": exec_timeout,
                        "timestamp": time.time(),
                    }
                )
                await self._terminate_pty_process(process_id)
                return_code = 124

            except asyncio.CancelledError:
                await self.stream_action(
                    {
                        "type": "command_cancelled",
                        "process_id": process_id,
                        "timestamp": time.time(),
                    }
                )
                await self._terminate_pty_process(process_id)
                return_code = 130

            # Cancel tasks
            input_task.cancel()
            try:
                await input_task
            except asyncio.CancelledError:
                pass

            if not output_task.done():
                output_task.cancel()
                try:
                    await output_task
                except asyncio.CancelledError:
                    pass

            # Notify frontend that command terminal is done
            await self.stream_action(
                {
                    "type": "command_terminal_end",
                    "process_id": process_id,
                    "exit_code": return_code,
                    "timestamp": time.time(),
                }
            )

            # Clean up
            await self._cleanup_pty(process_id)

            # Combine collected output
            output = "".join(collected_output)
            return f"Exit code: {return_code}\n{output.strip()}"

        except Exception as e:
            error_msg = f"Error executing command: {str(e)}"
            logger.error(error_msg)
            await self.stream_action(
                {
                    "type": "command_error",
                    "process_id": process_id,
                    "error": str(e),
                    "timestamp": time.time(),
                }
            )
            await self._cleanup_pty(process_id)
            return error_msg

        finally:
            self._current_process_id = None
            # Ensure FDs are closed
            if slave_fd is not None:
                try:
                    os.close(slave_fd)
                except OSError:
                    pass

    async def _monitor_pty_output(
        self,
        master_fd: int,
        process: "subprocess.Popen",
        process_id: str,
        collector: list[str],
        future: asyncio.Future,
    ) -> None:
        """Monitor PTY output and stream to WebSocket."""
        loop = asyncio.get_event_loop()

        while True:
            try:
                # Check for readable data using select
                readable, _, _ = await loop.run_in_executor(
                    None,
                    lambda: select.select([master_fd], [], [], 0.1),
                )

                if master_fd in readable:
                    try:
                        data = os.read(master_fd, self.READ_CHUNK_SIZE)

                        if data:
                            decoded = data.decode("utf-8", errors="replace")
                            collector.append(decoded)

                            # Stream to frontend terminal
                            await self.stream_action(
                                {
                                    "type": "terminal_output",
                                    "process_id": process_id,
                                    "data": decoded,
                                    "timestamp": time.time(),
                                }
                            )
                        else:
                            # EOF
                            break

                    except OSError as e:
                        if e.errno == 5:  # I/O error - terminal closed
                            break
                        elif e.errno != 11:  # Ignore EAGAIN
                            logger.debug(f"Error reading from PTY: {e}")

                # Check if process exited
                retcode = process.poll()
                if retcode is not None:
                    # Read any remaining output
                    try:
                        while True:
                            readable, _, _ = select.select([master_fd], [], [], 0.01)
                            if master_fd not in readable:
                                break
                            data = os.read(master_fd, self.READ_CHUNK_SIZE)
                            if not data:
                                break
                            decoded = data.decode("utf-8", errors="replace")
                            collector.append(decoded)
                            await self.stream_action(
                                {
                                    "type": "terminal_output",
                                    "process_id": process_id,
                                    "data": decoded,
                                    "timestamp": time.time(),
                                }
                            )
                    except OSError:
                        pass

                    if not future.done():
                        future.set_result(retcode)
                    break

                await asyncio.sleep(self.OUTPUT_READ_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in PTY output monitor: {e}")
                await asyncio.sleep(0.1)

        # Ensure future is resolved
        if not future.done():
            retcode = process.poll()
            future.set_result(retcode if retcode is not None else -1)

    async def _handle_pty_input(self, master_fd: int, process_id: str) -> None:
        """Handle input from WebSocket and write to PTY."""
        queue = self._pending_input.get(process_id)
        if not queue:
            return

        while True:
            try:
                # Wait for input from queue
                data = await queue.get()

                if data is None:  # Sentinel to stop
                    break

                # Write to PTY
                if isinstance(data, str):
                    data = data.encode("utf-8")

                try:
                    os.write(master_fd, data)
                except OSError as e:
                    if e.errno == 5:  # I/O error
                        break
                    logger.debug(f"Error writing to PTY: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in PTY input handler: {e}")

    async def _terminate_pty_process(self, process_id: str) -> None:
        """Terminate a PTY process."""
        pty_info = self._active_pty.get(process_id)
        if not pty_info:
            return

        process = pty_info.get("process")
        if process and process.poll() is None:
            try:
                # Send SIGTERM to process group
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    process.terminate()

                # Wait briefly
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    # Force kill
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        process.kill()
                    process.wait(timeout=1.0)
            except Exception as e:
                logger.debug(f"Error terminating PTY process: {e}")

    async def _cleanup_pty(self, process_id: str) -> None:
        """Clean up PTY resources."""
        async with self._cleanup_lock:
            pty_info = self._active_pty.pop(process_id, None)
            if pty_info:
                master_fd = pty_info.get("master_fd")
                if master_fd is not None:
                    try:
                        os.close(master_fd)
                    except OSError:
                        pass

            self._pending_input.pop(process_id, None)
            self._execution_futures.pop(process_id, None)
            self._output_tasks.pop(process_id, None)

    async def _execute_command_subprocess(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """Fallback subprocess execution for Windows."""
        process_id = f"cmd_{int(time.time() * 1000)}_{id(command) % 10000}"
        self._current_process_id = process_id
        cwd = working_dir if working_dir else self.working_directory
        exec_timeout = timeout if timeout else self.default_timeout

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

            await self.stream_action(
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

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=float(exec_timeout)
                )
                return_code = process.returncode
            except TimeoutError:
                process.kill()
                await process.wait()
                return_code = 124
                stdout, stderr = b"", b"Command timed out"

            # Stream output
            if stdout:
                await self.stream_action(
                    {
                        "type": "terminal_output",
                        "process_id": process_id,
                        "data": stdout.decode("utf-8", errors="replace"),
                        "timestamp": time.time(),
                    }
                )
            if stderr:
                await self.stream_action(
                    {
                        "type": "terminal_output",
                        "process_id": process_id,
                        "data": stderr.decode("utf-8", errors="replace"),
                        "timestamp": time.time(),
                    }
                )

            await self.stream_action(
                {
                    "type": "command_terminal_end",
                    "process_id": process_id,
                    "exit_code": return_code,
                    "timestamp": time.time(),
                }
            )

            output = ""
            if stderr:
                output += stderr.decode("utf-8", errors="replace") + "\n"
            if stdout:
                output += stdout.decode("utf-8", errors="replace")

            return f"Exit code: {return_code}\n{output.strip()}"

        except Exception as e:
            return f"Error executing command: {str(e)}"
        finally:
            self._current_process_id = None

    def provide_input(self, process_id: str | None, user_input: str) -> bool:
        """Provide input to a running PTY process.

        This queues input to be written to the PTY, enabling real-time
        interaction with the running command.

        Args:
            process_id: Process identifier (or None to use current).
            user_input: The input to provide (raw keystrokes or text).

        Returns:
            True if input was queued successfully.
        """
        target_id = process_id or self._current_process_id

        if target_id and target_id in self._pending_input:
            queue = self._pending_input[target_id]
            try:
                queue.put_nowait(user_input)
                return True
            except asyncio.QueueFull:
                logger.warning(f"Input queue full for process {target_id}")
                return False

        # Try any active process if no specific target
        if not target_id:
            for pid, queue in self._pending_input.items():
                try:
                    queue.put_nowait(user_input)
                    return True
                except asyncio.QueueFull:
                    continue

        return False

    async def send_input_to_process(self, process_id: str, input_text: str) -> bool:
        """Send input directly to a running PTY process.

        Args:
            process_id: Process identifier.
            input_text: The input text to send.

        Returns:
            True if input was sent successfully.
        """
        if process_id not in self._active_pty:
            await self.stream_action(
                {
                    "type": "input_error",
                    "process_id": process_id,
                    "content": f"Process {process_id} not found",
                    "timestamp": time.time(),
                }
            )
            return False

        pty_info = self._active_pty[process_id]
        master_fd = pty_info.get("master_fd")
        process = pty_info.get("process")

        if not master_fd:
            await self.stream_action(
                {
                    "type": "input_error",
                    "process_id": process_id,
                    "content": "PTY not available",
                    "timestamp": time.time(),
                }
            )
            return False

        if process and process.poll() is not None:
            await self.stream_action(
                {
                    "type": "input_error",
                    "process_id": process_id,
                    "content": f"Process has finished (exit code: {process.poll()})",
                    "timestamp": time.time(),
                }
            )
            return False

        try:
            input_bytes = input_text.encode("utf-8")
            os.write(master_fd, input_bytes)

            await self.stream_action(
                {
                    "type": "input_sent",
                    "process_id": process_id,
                    "bytes_written": len(input_bytes),
                    "timestamp": time.time(),
                }
            )

            return True

        except OSError as e:
            await self.stream_action(
                {
                    "type": "input_error",
                    "process_id": process_id,
                    "content": f"Error sending input: {str(e)}",
                    "timestamp": time.time(),
                }
            )
            return False

    def _get_signal_name(self, signal_num: int) -> str:
        """Get human-readable signal name."""
        signal_names = {
            signal.SIGTERM: "SIGTERM",
            signal.SIGKILL: "SIGKILL",
            signal.SIGINT: "SIGINT",
        }
        if hasattr(signal, "SIGHUP"):
            signal_names[signal.SIGHUP] = "SIGHUP"
        if hasattr(signal, "SIGQUIT"):
            signal_names[signal.SIGQUIT] = "SIGQUIT"
        return signal_names.get(signal_num, f"SIGNAL_{signal_num}")

    async def terminate_process(self, process_id: str) -> bool:
        """Terminate a specific PTY process."""
        if process_id not in self._active_pty:
            return False

        try:
            # Cancel execution future
            if process_id in self._execution_futures:
                future = self._execution_futures[process_id]
                if not future.done():
                    future.cancel()

            # Terminate the PTY process
            await self._terminate_pty_process(process_id)
            await self._cleanup_pty(process_id)
            return True

        except Exception:
            return False

    async def cleanup_all(self):
        """Clean up all PTY processes."""
        for process_id in list(self._active_pty.keys()):
            await self.terminate_process(process_id)

    def get_active_processes(self) -> list[str]:
        """Get list of active PTY process IDs."""
        return list(self._active_pty.keys())

    def has_pending_input(self) -> bool:
        """Check if any process has a pending input queue."""
        return len(self._pending_input) > 0

    def get_current_process_id(self) -> str | None:
        """Get the currently executing process ID."""
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

        pty_info = self._active_pty.get(process_id)
        if not pty_info:
            return False

        master_fd = pty_info.get("master_fd")
        if not master_fd:
            return False

        try:
            self._set_pty_size(master_fd, cols, rows)

            # Send SIGWINCH to process group
            process = pty_info.get("process")
            if process and process.poll() is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGWINCH)
                except (ProcessLookupError, PermissionError):
                    pass

            return True
        except Exception as e:
            logger.debug(f"Error resizing PTY: {e}")
            return False


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
