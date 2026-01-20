"""Async tool implementations for the Software Developer capability.

This module provides async-native tool implementations for file operations,
git operations, code analysis, and command execution with interactive input support.
"""

import ast
import asyncio
import os
import re
import shutil
import signal
import stat
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import git
from loguru import logger

if TYPE_CHECKING:
    from src.managers.connection import WebSocketManager


class InteractiveCommandExecutor:
    """Async command executor with interactive input support.

    This class handles command execution with:
    - Real-time output streaming to WebSocket
    - Input prompt detection
    - Interactive input from frontend via WebSocket
    - Proper process lifecycle management
    """

    # Configuration constants
    STDIN_DRAIN_TIMEOUT = 5.0
    READ_CHUNK_SIZE = 256
    READ_TIMEOUT = 0.05
    TERMINATION_GRACE_PERIOD = 5.0
    # Stall detection: if no output for this long, assume process might need input
    STALL_DETECTION_TIMEOUT = 1.5
    WIN32 = os.name == "nt"

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

        # Process management
        self.active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._execution_futures: dict[str, asyncio.Future] = {}
        self._process_monitor_tasks: dict[str, asyncio.Task] = {}
        self._output_tasks: dict[str, list[asyncio.Task]] = {}
        self._cleanup_lock = asyncio.Lock()

        # Input handling
        self._pending_input_futures: dict[str, asyncio.Future] = {}
        self._current_process_id: str | None = None

        # Stall detection - track last output time per process
        self._last_output_time: dict[str, float] = {}
        self._stall_detection_tasks: dict[str, asyncio.Task] = {}
        self._stall_notified: dict[str, bool] = {}

    def set_websocket_manager(self, manager: "WebSocketManager") -> None:
        """Set the WebSocket manager for streaming."""
        self.websocket_manager = manager

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

    async def execute_command(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """Execute a shell command with interactive input support.

        Args:
            command: The shell command to execute.
            working_dir: Optional working directory override.
            timeout: Optional timeout override in seconds.

        Returns:
            Command output as string.
        """
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
                start_new_session=not self.WIN32,
            )

            self.active_processes[process_id] = process
            execution_future: asyncio.Future[int] = asyncio.Future()
            self._execution_futures[process_id] = execution_future

            monitor_task = asyncio.create_task(
                self._monitor_process_lifecycle(process, process_id, execution_future)
            )
            self._process_monitor_tasks[process_id] = monitor_task

            await self.stream_action(
                {
                    "type": "process_started",
                    "process_id": process_id,
                    "pid": process.pid,
                    "command": command,
                    "working_dir": cwd,
                    "timestamp": time.time(),
                }
            )

            collected_stdout: list[str] = []
            collected_stderr: list[str] = []

            stdout_task = asyncio.create_task(
                self._monitor_output_stream(
                    process.stdout, process, process_id, "stdout", collected_stdout
                )
            )
            stderr_task = asyncio.create_task(
                self._monitor_output_stream(
                    process.stderr, process, process_id, "stderr", collected_stderr
                )
            )

            self._output_tasks[process_id] = [stdout_task, stderr_task]

            # Initialize stall detection tracking
            self._last_output_time[process_id] = time.time()
            self._stall_notified[process_id] = False

            # Start stall detection monitor
            stall_task = asyncio.create_task(
                self._monitor_stall_detection(process, process_id)
            )
            self._stall_detection_tasks[process_id] = stall_task

            try:
                if exec_timeout > 0:
                    return_code = await asyncio.wait_for(
                        execution_future, timeout=float(exec_timeout)
                    )
                else:
                    return_code = await execution_future

            except TimeoutError:
                await self._handle_process_timeout(process_id)
                return_code = 124
                await self._wait_for_output_tasks(process_id)

            except asyncio.CancelledError:
                await self.stream_action(
                    {
                        "type": "process_cancelled",
                        "process_id": process_id,
                        "timestamp": time.time(),
                    }
                )
                await self._terminate_process_group(process)
                await self._wait_for_output_tasks(process_id)
                return_code = 130

            await self._wait_for_output_tasks(process_id)

            stdout_output = "\n".join(collected_stdout) if collected_stdout else ""
            stderr_output = "\n".join(collected_stderr) if collected_stderr else ""

            output = ""
            if stderr_output:
                output += stderr_output + "\n"
            if stdout_output:
                output += stdout_output

            await self._cleanup_single_process(process_id)

            return f"Exit code: {return_code}\n{output.strip()}"

        except Exception as e:
            error_msg = f"Error executing command: {str(e)}"
            await self.stream_action(
                {
                    "type": "terminal_error",
                    "process_id": process_id,
                    "content": error_msg,
                    "timestamp": time.time(),
                }
            )
            await self._cleanup_single_process(process_id)
            return error_msg

        finally:
            self._current_process_id = None

    async def _wait_for_output_tasks(self, process_id: str, timeout: float = 2.0):
        """Wait for output tasks to complete with timeout."""
        if process_id not in self._output_tasks:
            return

        try:
            await asyncio.wait_for(
                asyncio.gather(*self._output_tasks[process_id], return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            for task in self._output_tasks[process_id]:
                if not task.done():
                    task.cancel()

    async def _monitor_output_stream(
        self,
        stream: asyncio.StreamReader,
        process: asyncio.subprocess.Process,
        process_id: str,
        stream_name: str,
        collector: list[str],
    ):
        """Monitor output stream with real-time prompt detection."""
        buffer = ""
        try:
            while True:
                if process.returncode is not None and not buffer:
                    try:
                        remaining = await asyncio.wait_for(
                            stream.read(self.READ_CHUNK_SIZE), timeout=0.1
                        )
                        if remaining:
                            buffer += remaining.decode("utf-8", errors="replace")
                        else:
                            break
                    except (TimeoutError, asyncio.CancelledError):
                        break

                try:
                    chunk = await asyncio.wait_for(
                        stream.read(self.READ_CHUNK_SIZE), timeout=self.READ_TIMEOUT
                    )

                    if not chunk:
                        if buffer:
                            await self._process_output_buffer(
                                buffer, process_id, stream_name, collector
                            )
                        break

                    buffer += chunk.decode("utf-8", errors="replace")
                    buffer = await self._process_output_buffer(
                        buffer, process_id, stream_name, collector
                    )

                except TimeoutError:
                    if buffer and self._looks_like_input_prompt(buffer):
                        await self._emit_output(
                            buffer.rstrip("\n"),
                            process_id,
                            stream_name,
                            collector,
                            is_partial=True,
                        )
                        user_input = await self._wait_for_user_input(process_id, buffer)
                        if user_input is not None:
                            await self.send_input_to_process(process_id, user_input)
                        buffer = ""
                    continue

                except asyncio.CancelledError:
                    if buffer:
                        await self._process_output_buffer(
                            buffer, process_id, stream_name, collector, force_emit=True
                        )
                    raise

        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self.stream_action(
                {
                    "type": "terminal_error",
                    "process_id": process_id,
                    "content": f"Error reading {stream_name}: {str(e)}",
                    "timestamp": time.time(),
                }
            )

    async def _process_output_buffer(
        self,
        buffer: str,
        process_id: str,
        stream_name: str,
        collector: list[str],
        force_emit: bool = False,
    ) -> str:
        """Process output buffer, emitting complete lines."""
        lines = buffer.split("\n")

        for line in lines[:-1]:
            if line:
                await self._emit_output(line, process_id, stream_name, collector)

        remaining = lines[-1]

        if force_emit and remaining:
            await self._emit_output(remaining, process_id, stream_name, collector)
            return ""

        return remaining

    async def _emit_output(
        self,
        content: str,
        process_id: str,
        stream_name: str,
        collector: list[str],
        is_partial: bool = False,
    ):
        """Emit output to WebSocket and collector."""
        collector.append(content)
        is_input_prompt = self._looks_like_input_prompt(content)

        # Update last output time for stall detection
        self._last_output_time[process_id] = time.time()
        # Reset stall notification since we got output
        self._stall_notified[process_id] = False

        await self.stream_action(
            {
                "type": "terminal_output",
                "stream": stream_name,
                "process_id": process_id,
                "content": content,
                "is_input_prompt": is_input_prompt,
                "is_partial": is_partial,
                "timestamp": time.time(),
            }
        )

        if is_input_prompt:
            await self.stream_action(
                {
                    "type": "input_prompt_detected",
                    "process_id": process_id,
                    "prompt_text": content,
                    "message": f"The command is waiting for input: {content}",
                    "timestamp": time.time(),
                }
            )

    def _looks_like_input_prompt(self, text: str) -> bool:
        """Determine if text looks like an input prompt."""
        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        if not text_stripped:
            return False

        strong_indicators = [
            "input(",
            ">>> ",
            "... ",
            "password:",
            "password: ",
            "[y/n]",
            "[yes/no]",
            "(y/n)",
            "(yes/no)",
            "enter your",
            "type your",
            "please enter",
            "please type",
            "confirm",
        ]

        if any(ind in text_lower for ind in strong_indicators):
            return True

        prompt_endings = ["?", ": ", ":"]
        question_words = [
            "enter",
            "input",
            "type",
            "provide",
            "specify",
            "choose",
            "select",
            "please",
            "what",
            "which",
            "name",
            "value",
            "continue",
            "proceed",
            "overwrite",
        ]

        for ending in prompt_endings:
            if text_stripped.endswith(ending):
                if any(word in text_lower for word in question_words):
                    return True

        if text_stripped.endswith(":") and len(text_stripped) < 50:
            non_prompt_patterns = [
                "error:",
                "warning:",
                "info:",
                "debug:",
                "note:",
                "traceback",
                "file ",
                "line ",
                "exception",
            ]
            if not any(pat in text_lower for pat in non_prompt_patterns):
                return True

        return False

    async def _wait_for_user_input(
        self, process_id: str, prompt_text: str, timeout: float = 300.0
    ) -> str | None:
        """Wait for user input from WebSocket."""
        input_future: asyncio.Future[str] = asyncio.Future()
        self._pending_input_futures[process_id] = input_future

        try:
            user_input = await asyncio.wait_for(input_future, timeout=timeout)
            return user_input
        except TimeoutError:
            await self.stream_action(
                {
                    "type": "input_timeout",
                    "process_id": process_id,
                    "message": "Input prompt timed out waiting for user response",
                    "timestamp": time.time(),
                }
            )
            return None
        except asyncio.CancelledError:
            return None
        finally:
            self._pending_input_futures.pop(process_id, None)

    async def _monitor_stall_detection(
        self, process: asyncio.subprocess.Process, process_id: str
    ):
        """Monitor for stalled processes that might be waiting for input.

        This handles cases like bash's `read -p` which writes prompts
        directly to /dev/tty instead of stdout/stderr, so we can't
        detect the prompt through normal output monitoring.

        Args:
            process: The subprocess to monitor.
            process_id: Process identifier.
        """
        try:
            # Wait a bit before starting stall detection to allow initial output
            await asyncio.sleep(self.STALL_DETECTION_TIMEOUT)

            while process.returncode is None:
                # Check if process is stalled (no output recently)
                last_output = self._last_output_time.get(process_id, time.time())
                time_since_output = time.time() - last_output

                # If stalled and not already notified and no pending input future
                if (
                    time_since_output >= self.STALL_DETECTION_TIMEOUT
                    and not self._stall_notified.get(process_id, False)
                    and process_id not in self._pending_input_futures
                ):
                    # Mark as notified to avoid spamming
                    self._stall_notified[process_id] = True

                    # Notify frontend that input might be needed
                    await self.stream_action(
                        {
                            "type": "input_might_be_needed",
                            "process_id": process_id,
                            "message": (
                                "Process appears to be waiting for input. "
                                "If prompted, please provide input."
                            ),
                            "stall_duration": time_since_output,
                            "timestamp": time.time(),
                        }
                    )

                    # Wait for user input
                    user_input = await self._wait_for_user_input(
                        process_id, "(possible hidden prompt)"
                    )
                    if user_input is not None:
                        await self.send_input_to_process(process_id, user_input)

                # Sleep before next check
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Stall detection error for {process_id}: {e}")

    def provide_input(self, process_id: str | None, user_input: str) -> bool:
        """Provide input to a waiting process.

        Args:
            process_id: Process identifier (or None to use current).
            user_input: The input to provide.

        Returns:
            True if input was accepted.
        """
        target_id = process_id or self._current_process_id

        if target_id and target_id in self._pending_input_futures:
            future = self._pending_input_futures[target_id]
            if not future.done():
                future.set_result(user_input)
                return True

        if not target_id:
            for pid, future in self._pending_input_futures.items():
                if not future.done():
                    future.set_result(user_input)
                    return True

        return False

    async def send_input_to_process(self, process_id: str, input_text: str) -> bool:
        """Send input directly to a running process stdin."""
        if process_id not in self.active_processes:
            await self.stream_action(
                {
                    "type": "input_error",
                    "process_id": process_id,
                    "content": f"Process {process_id} not found",
                    "timestamp": time.time(),
                }
            )
            return False

        try:
            process = self.active_processes[process_id]

            if process.returncode is not None:
                await self.stream_action(
                    {
                        "type": "input_error",
                        "process_id": process_id,
                        "content": f"Process has finished (exit code: {process.returncode})",
                        "timestamp": time.time(),
                    }
                )
                return False

            if not process.stdin or process.stdin.is_closing():
                await self.stream_action(
                    {
                        "type": "input_error",
                        "process_id": process_id,
                        "content": "Process stdin is not available",
                        "timestamp": time.time(),
                    }
                )
                return False

            input_bytes = input_text.encode("utf-8") + b"\n"
            process.stdin.write(input_bytes)

            try:
                await asyncio.wait_for(
                    process.stdin.drain(), timeout=self.STDIN_DRAIN_TIMEOUT
                )
            except TimeoutError:
                pass  # Continue anyway

            await self.stream_action(
                {
                    "type": "input_sent",
                    "process_id": process_id,
                    "content": input_text,
                    "bytes_written": len(input_bytes),
                    "timestamp": time.time(),
                }
            )

            return True

        except BrokenPipeError:
            await self.stream_action(
                {
                    "type": "input_error",
                    "process_id": process_id,
                    "content": "stdin pipe is broken (process ended)",
                    "timestamp": time.time(),
                }
            )
            return False
        except Exception as e:
            await self.stream_action(
                {
                    "type": "input_error",
                    "process_id": process_id,
                    "content": f"Error sending input: {str(e)}",
                    "timestamp": time.time(),
                }
            )
            return False

    async def _monitor_process_lifecycle(
        self,
        process: asyncio.subprocess.Process,
        process_id: str,
        future: asyncio.Future,
    ):
        """Monitor process lifecycle and handle completion."""
        try:
            return_code = await process.wait()

            if return_code < 0:
                signal_name = self._get_signal_name(-return_code)
                await self.stream_action(
                    {
                        "type": "process_terminated_by_signal",
                        "process_id": process_id,
                        "signal": signal_name,
                        "return_code": return_code,
                        "timestamp": time.time(),
                    }
                )
            else:
                await self.stream_action(
                    {
                        "type": "process_completed",
                        "process_id": process_id,
                        "exit_code": return_code,
                        "timestamp": time.time(),
                    }
                )

            if not future.done():
                future.set_result(return_code)

        except asyncio.CancelledError:
            if not future.done():
                future.cancel()
            raise
        except Exception as e:
            if not future.done():
                future.set_exception(e)

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

    async def _terminate_process_group(self, process: asyncio.subprocess.Process):
        """Terminate process and all its children."""
        if process.returncode is not None:
            return

        try:
            if self.WIN32:
                process.terminate()
            else:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    process.terminate()

            try:
                await asyncio.wait_for(
                    process.wait(), timeout=self.TERMINATION_GRACE_PERIOD
                )
            except TimeoutError:
                if self.WIN32:
                    process.kill()
                else:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        process.kill()
                await process.wait()
        except Exception:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass

    async def _handle_process_timeout(self, process_id: str):
        """Handle process timeout."""
        if process_id not in self.active_processes:
            return

        process = self.active_processes[process_id]
        await self.stream_action(
            {
                "type": "process_timeout",
                "process_id": process_id,
                "timestamp": time.time(),
            }
        )
        await self._terminate_process_group(process)

    async def terminate_process(self, process_id: str) -> bool:
        """Terminate a specific process."""
        if process_id not in self.active_processes:
            return False

        try:
            process = self.active_processes[process_id]

            if process_id in self._execution_futures:
                future = self._execution_futures[process_id]
                if not future.done():
                    future.cancel()

            if process_id in self._pending_input_futures:
                future = self._pending_input_futures[process_id]
                if not future.done():
                    future.cancel()

            await self._terminate_process_group(process)
            await self._cleanup_single_process(process_id)
            return True

        except Exception:
            return False

    async def _cleanup_single_process(self, process_id: str):
        """Clean up a single process and all its resources."""
        async with self._cleanup_lock:
            try:
                if process_id in self._process_monitor_tasks:
                    task = self._process_monitor_tasks[process_id]
                    if not task.done():
                        task.cancel()
                        try:
                            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
                        except (asyncio.CancelledError, TimeoutError):
                            pass
                    del self._process_monitor_tasks[process_id]

                # Cancel stall detection task
                if process_id in self._stall_detection_tasks:
                    task = self._stall_detection_tasks[process_id]
                    if not task.done():
                        task.cancel()
                    del self._stall_detection_tasks[process_id]

                if process_id in self._output_tasks:
                    for task in self._output_tasks[process_id]:
                        if not task.done():
                            task.cancel()
                    del self._output_tasks[process_id]

                self.active_processes.pop(process_id, None)
                # Clean up stall detection tracking
                self._last_output_time.pop(process_id, None)
                self._stall_notified.pop(process_id, None)
                if process_id in self._execution_futures:
                    future = self._execution_futures[process_id]
                    if not future.done():
                        future.cancel()
                    del self._execution_futures[process_id]
                self._pending_input_futures.pop(process_id, None)

            except Exception as e:
                logger.debug(f"Cleanup error for {process_id}: {e}")

    async def cleanup_all(self):
        """Clean up all processes."""
        for process_id in list(self.active_processes.keys()):
            await self._cleanup_single_process(process_id)

    def get_active_processes(self) -> list[str]:
        """Get list of active process IDs."""
        return list(self.active_processes.keys())

    def has_pending_input(self) -> bool:
        """Check if any process is waiting for input."""
        return any(not f.done() for f in self._pending_input_futures.values())

    def get_current_process_id(self) -> str | None:
        """Get the currently executing process ID."""
        return self._current_process_id


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
