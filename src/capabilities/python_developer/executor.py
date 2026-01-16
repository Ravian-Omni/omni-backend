import asyncio
import os
import signal
import time
from typing import Any

from autogen.code_utils import WIN32, _cmd
from autogen.coding import LocalCommandLineCodeExecutor
from autogen.coding.base import CodeBlock, CommandLineCodeResult

from src.dependencies import get_websocket_manager
from src.utilities.async_helpers import async_to_sync


class InteractiveLocalCommandLineCodeExecutor(LocalCommandLineCodeExecutor):
    """Extension that makes ALL code execution interactive via async subprocess with proper lifecycle management."""

    # Timeout for stdin drain operations (seconds)
    STDIN_DRAIN_TIMEOUT = 5.0
    # Read chunk size for non-blocking output reading
    READ_CHUNK_SIZE = 256
    # Timeout for reading output chunks when no data available (seconds)
    READ_TIMEOUT = 0.05
    # Grace period for graceful termination before force kill (seconds)
    TERMINATION_GRACE_PERIOD = 5.0

    def __init__(self, session_id, *args, **kwargs):
        """Initialize InteractiveLocalCommandLineCodeExecutor.

        Args:
            session_id: Session identifier.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        self.session_id: str = session_id
        super().__init__(*args, **kwargs)

        # Enhanced process management
        self.active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._execution_futures: dict[str, asyncio.Future] = {}
        self._process_monitor_tasks: dict[str, asyncio.Task] = {}
        self._output_tasks: dict[str, list[asyncio.Task]] = {}
        self._cleanup_lock = asyncio.Lock()

    async def stream_action(self, action_data: dict[str, Any]):
        """Stream action to all connected clients.

        Args:
            action_data: Action data to stream.
        """
        try:
            websocket_manager = await get_websocket_manager()
            await websocket_manager.send_chat_message(
                session_id=self.session_id, content=action_data, source="executor"
            )
        except Exception as e:
            print(f"Error streaming action: {e}")

    def _execute_code_dont_check_setup(
        self, code_blocks: list[CodeBlock]
    ) -> CommandLineCodeResult:
        """Override to make ALL code execution async and interactive.

        Args:
            code_blocks: List of code blocks to execute.

        Returns:
            CommandLineCodeResult with execution results.
        """
        try:
            return async_to_sync(self._async_execute_blocks(code_blocks))
        except Exception as e:
            return CommandLineCodeResult(
                exit_code=1, output=f"Execution error: {str(e)}"
            )

    async def _async_execute_blocks(
        self, code_blocks: list[CodeBlock]
    ) -> CommandLineCodeResult:
        """Execute all code blocks asynchronously with proper lifecycle management.

        Args:
            code_blocks: List of code blocks to execute.

        Returns:
            CommandLineCodeResult with execution results.
        """
        logs_all = ""
        file_names = []
        exitcode = 0

        try:
            for i, code_block in enumerate(code_blocks):
                process_id = f"block_{i}_{int(time.time() * 1000)}"

                # ===== REUSE PARENT'S LOGIC EXACTLY =====
                lang, code = code_block.language, code_block.code
                lang = lang.lower()

                # Sanitize command (parent's method)
                self.sanitize_command(lang, code)

                # Silence pip (parent's logic)
                from autogen.coding.utils import silence_pip

                code = silence_pip(code, lang)

                # Handle Python variants (parent's logic)
                from autogen.code_utils import PYTHON_VARIANTS

                if lang in PYTHON_VARIANTS:
                    lang = "python"

                # Handle Windows (parent's logic)
                if WIN32 and lang in ["sh", "shell"]:
                    lang = "ps1"

                # Check supported languages (parent's logic)
                if lang not in self.SUPPORTED_LANGUAGES:
                    exitcode = 1
                    error_msg = f"unknown language {lang}"
                    logs_all += "\n" + error_msg
                    await self.stream_action(
                        {
                            "type": "terminal_error",
                            "process_id": process_id,
                            "content": error_msg,
                            "timestamp": time.time(),
                        }
                    )
                    break

                # Check execution policy (parent's logic)
                execute_code = self.execution_policies.get(lang, False)

                # Get filename (parent's logic)
                try:
                    from autogen.coding.utils import _get_file_name_from_content

                    filename = _get_file_name_from_content(code, self._work_dir)
                except ValueError:
                    return CommandLineCodeResult(
                        exit_code=1, output="Filename is not in the workspace"
                    )

                # Generate filename if needed (parent's logic)
                if filename is None:
                    from hashlib import md5

                    code_hash = md5(code.encode()).hexdigest()
                    filename = f"tmp_code_{code_hash}.{'py' if lang.startswith('python') else lang}"

                # Write file (parent's logic)
                written_file = (self._work_dir / filename).resolve()
                with written_file.open("w", encoding="utf-8") as f:
                    f.write(code)
                file_names.append(written_file)

                # If not executing, just save (parent's logic)
                if not execute_code:
                    save_msg = f"Code saved to {written_file!s}\n"
                    logs_all += save_msg
                    await self.stream_action(
                        {
                            "type": "terminal_info",
                            "process_id": process_id,
                            "content": save_msg.strip(),
                            "timestamp": time.time(),
                        }
                    )
                    exitcode = 0
                    continue

                # Prepare command (parent's logic)
                program = _cmd(lang)
                cmd = [program, str(written_file.absolute())]
                env = os.environ.copy()

                # Virtual environment (parent's logic)
                if self._virtual_env_context:
                    virtual_env_abs_path = os.path.abspath(
                        self._virtual_env_context.bin_path
                    )
                    path_with_virtualenv = (
                        rf"{virtual_env_abs_path}{os.pathsep}{env['PATH']}"
                    )
                    env["PATH"] = path_with_virtualenv
                    if WIN32:
                        activation_script = os.path.join(
                            virtual_env_abs_path, "activate.bat"
                        )
                        cmd = [activation_script, "&&", *cmd]

                # ===== ENHANCED ASYNC EXECUTION WITH LIFECYCLE MANAGEMENT =====
                try:
                    # Force unbuffered Python output for real-time streaming
                    env["PYTHONUNBUFFERED"] = "1"

                    # Create async subprocess with process group for proper termination
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(self._work_dir),
                        env=env,
                        # Create new session/process group so we can kill all children
                        start_new_session=not WIN32,
                    )

                    # Register process
                    self.active_processes[process_id] = process

                    # Create execution future
                    execution_future: asyncio.Future[int] = asyncio.Future()
                    self._execution_futures[process_id] = execution_future

                    # Start process lifecycle monitor
                    monitor_task = asyncio.create_task(
                        self._monitor_process_lifecycle(
                            process, process_id, execution_future
                        )
                    )
                    self._process_monitor_tasks[process_id] = monitor_task

                    # Notify process started
                    await self.stream_action(
                        {
                            "type": "process_started",
                            "process_id": process_id,
                            "pid": process.pid,
                            "command": " ".join(cmd),
                            "file": str(written_file),
                            "language": lang,
                            "timestamp": time.time(),
                        }
                    )

                    # Start output monitoring with chunk-based reading for real-time prompts
                    collected_stdout: list[str] = []
                    collected_stderr: list[str] = []

                    stdout_task = asyncio.create_task(
                        self._monitor_output_stream(
                            process.stdout,
                            process,
                            process_id,
                            "stdout",
                            collected_stdout,
                        )
                    )
                    stderr_task = asyncio.create_task(
                        self._monitor_output_stream(
                            process.stderr,
                            process,
                            process_id,
                            "stderr",
                            collected_stderr,
                        )
                    )

                    # Store output tasks for cleanup
                    self._output_tasks[process_id] = [stdout_task, stderr_task]

                    # Wait for process completion with proper timeout handling
                    try:
                        if self._timeout > 0:
                            return_code = await asyncio.wait_for(
                                execution_future, timeout=float(self._timeout)
                            )
                        else:
                            return_code = await execution_future

                    except TimeoutError:
                        await self._handle_process_timeout(process_id)
                        return_code = 124
                        # Still collect remaining output
                        await self._wait_for_output_tasks(process_id)
                        break

                    except asyncio.CancelledError:
                        await self.stream_action(
                            {
                                "type": "process_cancelled",
                                "process_id": process_id,
                                "timestamp": time.time(),
                            }
                        )
                        # Ensure process is terminated and output collected
                        await self._terminate_process_group(process)
                        await self._wait_for_output_tasks(process_id)
                        return_code = 130  # SIGINT exit code
                        break

                    # Wait for output collection to complete
                    await self._wait_for_output_tasks(process_id)

                    # Combine output like parent does
                    stdout_output = (
                        "\n".join(collected_stdout) if collected_stdout else ""
                    )
                    stderr_output = (
                        "\n".join(collected_stderr) if collected_stderr else ""
                    )

                    # Follow parent's pattern: stderr first, then stdout
                    if stderr_output:
                        logs_all += stderr_output + "\n"
                    if stdout_output:
                        logs_all += stdout_output + "\n"

                    exitcode = return_code

                    # Cleanup this process
                    await self._cleanup_single_process(process_id)

                    # Break on error (parent's behavior)
                    if exitcode != 0:
                        break

                except Exception as e:
                    error_msg = f"Execution error: {str(e)}"
                    logs_all += "\n" + error_msg
                    await self.stream_action(
                        {
                            "type": "terminal_error",
                            "process_id": process_id,
                            "content": error_msg,
                            "timestamp": time.time(),
                        }
                    )
                    await self._cleanup_single_process(process_id)
                    exitcode = 1
                    break

        finally:
            # Ensure all processes are cleaned up
            await self._cleanup_all_processes()

        # Send final execution summary
        await self.stream_action(
            {
                "type": "execution_summary",
                "total_blocks": len(code_blocks),
                "exit_code": exitcode,
                "output_length": len(logs_all),
                "timestamp": time.time(),
            }
        )

        # Return result exactly like parent
        code_file = str(file_names[0]) if len(file_names) > 0 else None
        return CommandLineCodeResult(
            exit_code=exitcode, output=logs_all, code_file=code_file
        )

    async def _wait_for_output_tasks(self, process_id: str, timeout: float = 2.0):
        """Wait for output tasks to complete with timeout.

        Args:
            process_id: Process identifier.
            timeout: Maximum time to wait for output tasks.
        """
        if process_id not in self._output_tasks:
            return

        try:
            await asyncio.wait_for(
                asyncio.gather(*self._output_tasks[process_id], return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            # Cancel tasks that are still running
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
        """Monitor output stream with chunk-based reading for real-time prompt detection.

        Uses read() instead of readline() to handle prompts that don't end with newline.

        Args:
            stream: The stream to read from.
            process: Process instance for checking if still running.
            process_id: Process identifier.
            stream_name: Name of stream ("stdout" or "stderr").
            collector: List to collect output lines.
        """
        buffer = ""
        try:
            while True:
                # Check if process has ended
                if process.returncode is not None and not buffer:
                    # Try one final read to get any remaining data
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

                # Try to read available data with a short timeout
                try:
                    chunk = await asyncio.wait_for(
                        stream.read(self.READ_CHUNK_SIZE), timeout=self.READ_TIMEOUT
                    )

                    if not chunk:
                        # EOF reached - process any remaining buffer
                        if buffer:
                            await self._process_output_buffer(
                                buffer, process_id, stream_name, collector
                            )
                        break

                    buffer += chunk.decode("utf-8", errors="replace")

                    # Process complete lines and detect input prompts
                    buffer = await self._process_output_buffer(
                        buffer, process_id, stream_name, collector
                    )

                except TimeoutError:
                    # No data available right now
                    # If we have buffered data that looks like a prompt, emit it
                    if buffer and self._looks_like_input_prompt(buffer):
                        await self._emit_output(
                            buffer.rstrip("\n"),
                            process_id,
                            stream_name,
                            collector,
                            is_partial=True,
                        )
                        buffer = ""
                    continue

                except asyncio.CancelledError:
                    # Task cancelled - emit any remaining buffer
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
        """Process output buffer, emitting complete lines and detecting prompts.

        Args:
            buffer: Current buffer content.
            process_id: Process identifier.
            stream_name: Name of stream.
            collector: List to collect output.
            force_emit: If True, emit all buffer content even without newline.

        Returns:
            Remaining buffer content (incomplete line).
        """
        # Split into lines, keeping track of whether last part is complete
        lines = buffer.split("\n")

        # Process all complete lines (all but the last if no trailing newline)
        for line in lines[:-1]:
            if line:  # Skip empty lines from consecutive newlines
                await self._emit_output(line, process_id, stream_name, collector)

        # Handle the last part
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
        """Emit output to websocket and collector.

        Args:
            content: Content to emit.
            process_id: Process identifier.
            stream_name: Name of stream.
            collector: List to collect output.
            is_partial: Whether this is a partial line (no newline yet).
        """
        collector.append(content)

        is_input_prompt = self._looks_like_input_prompt(content)

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
                    "content": f"Input prompt detected: {content}",
                    "timestamp": time.time(),
                }
            )

    def _looks_like_input_prompt(self, text: str) -> bool:
        """Determine if text looks like an input prompt.

        Uses heuristics to detect common input prompt patterns without
        too many false positives.

        Args:
            text: Text to check.

        Returns:
            True if text appears to be an input prompt.
        """
        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        # Empty text is not a prompt
        if not text_stripped:
            return False

        # Strong indicators - these patterns strongly suggest input is expected
        strong_indicators = [
            "input(",  # Python input() call visible in prompt
            ">>> ",  # Python REPL
            "... ",  # Python REPL continuation
            "password:",
            "password: ",
            "[y/n]",
            "[yes/no]",
            "(y/n)",
            "(yes/no)",
        ]

        if any(ind in text_lower for ind in strong_indicators):
            return True

        # Prompt-like endings with context
        # Must end with these AND have question-like content
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
        ]

        for ending in prompt_endings:
            if text_stripped.endswith(ending):
                # Check if it has question-like content
                if any(word in text_lower for word in question_words):
                    return True

        # Ends with just ":" and is short (likely a simple prompt)
        if text_stripped.endswith(":") and len(text_stripped) < 50:
            # But exclude common non-prompt patterns
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

    async def _monitor_process_lifecycle(
        self,
        process: asyncio.subprocess.Process,
        process_id: str,
        future: asyncio.Future,
    ):
        """Monitor process lifecycle and handle completion/termination.

        Args:
            process: Process instance.
            process_id: Process identifier.
            future: Future for tracking completion.
        """
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
            await self.stream_action(
                {
                    "type": "process_monitor_error",
                    "process_id": process_id,
                    "error": str(e),
                    "timestamp": time.time(),
                }
            )

            if not future.done():
                future.set_exception(e)

    def _get_signal_name(self, signal_num: int) -> str:
        """Get human-readable signal name.

        Args:
            signal_num: Signal number.

        Returns:
            Human-readable signal name.
        """
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
        """Terminate process and all its children using process group.

        Args:
            process: Process to terminate.
        """
        if process.returncode is not None:
            return

        try:
            if WIN32:
                # Windows: just terminate the process
                process.terminate()
            else:
                # Unix: kill the entire process group
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    # Process already gone or no permission
                    process.terminate()

            # Wait for graceful termination
            try:
                await asyncio.wait_for(
                    process.wait(), timeout=self.TERMINATION_GRACE_PERIOD
                )
            except TimeoutError:
                # Force kill
                if WIN32:
                    process.kill()
                else:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        process.kill()
                await process.wait()

        except Exception:
            # Last resort
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass

    async def _handle_process_timeout(self, process_id: str):
        """Handle process timeout with graceful and forceful termination.

        Args:
            process_id: Process identifier.
        """
        if process_id not in self.active_processes:
            return

        process = self.active_processes[process_id]

        await self.stream_action(
            {
                "type": "process_timeout_start",
                "process_id": process_id,
                "timestamp": time.time(),
            }
        )

        await self._terminate_process_group(process)

        await self.stream_action(
            {
                "type": "process_timeout_completed",
                "process_id": process_id,
                "timestamp": time.time(),
            }
        )

    async def send_input_to_process(self, process_id: str, input_text: str) -> bool:
        """Send input to running process with comprehensive error handling.

        Args:
            process_id: Process identifier.
            input_text: Input text to send.

        Returns:
            True if input was sent successfully.
        """
        if process_id not in self.active_processes:
            await self.stream_action(
                {
                    "type": "input_error",
                    "process_id": process_id,
                    "content": f"Process {process_id} not found in active processes",
                    "available_processes": list(self.active_processes.keys()),
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
                        "content": f"Process {process_id} has finished (exit code: {process.returncode})",
                        "timestamp": time.time(),
                    }
                )
                return False

            if not process.stdin:
                await self.stream_action(
                    {
                        "type": "input_error",
                        "process_id": process_id,
                        "content": f"Process {process_id} stdin is not available",
                        "timestamp": time.time(),
                    }
                )
                return False

            if process.stdin.is_closing():
                await self.stream_action(
                    {
                        "type": "input_error",
                        "process_id": process_id,
                        "content": f"Process {process_id} stdin is closing",
                        "timestamp": time.time(),
                    }
                )
                return False

            # Send input with newline
            input_bytes = input_text.encode("utf-8") + b"\n"
            process.stdin.write(input_bytes)

            # Drain with timeout to prevent hanging
            try:
                await asyncio.wait_for(
                    process.stdin.drain(), timeout=self.STDIN_DRAIN_TIMEOUT
                )
            except TimeoutError:
                await self.stream_action(
                    {
                        "type": "input_warning",
                        "process_id": process_id,
                        "content": "stdin drain timed out, input may not be fully sent",
                        "timestamp": time.time(),
                    }
                )
                # Continue anyway - the data was written to the buffer

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
                    "content": f"Process {process_id} stdin pipe is broken (process ended)",
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

    async def terminate_process(self, process_id: str) -> bool:
        """Terminate a specific process with proper cleanup.

        Args:
            process_id: Process identifier.

        Returns:
            True if termination was successful.
        """
        if process_id not in self.active_processes:
            await self.stream_action(
                {
                    "type": "terminate_failed",
                    "process_id": process_id,
                    "reason": "Process not found",
                    "timestamp": time.time(),
                }
            )
            return False

        try:
            process = self.active_processes[process_id]

            await self.stream_action(
                {
                    "type": "termination_requested",
                    "process_id": process_id,
                    "timestamp": time.time(),
                }
            )

            # Cancel the execution future first
            if process_id in self._execution_futures:
                future = self._execution_futures[process_id]
                if not future.done():
                    future.cancel()

            # Terminate the process group
            await self._terminate_process_group(process)

            await self.stream_action(
                {
                    "type": "process_terminated",
                    "process_id": process_id,
                    "timestamp": time.time(),
                }
            )

            # Cleanup
            await self._cleanup_single_process(process_id)
            return True

        except Exception as e:
            await self.stream_action(
                {
                    "type": "termination_error",
                    "process_id": process_id,
                    "error": str(e),
                    "timestamp": time.time(),
                }
            )
            return False

    async def _cleanup_single_process(self, process_id: str):
        """Clean up a single process and all its resources.

        Args:
            process_id: Process identifier.
        """
        async with self._cleanup_lock:
            try:
                # Cancel and clean up monitor task
                if process_id in self._process_monitor_tasks:
                    task = self._process_monitor_tasks[process_id]
                    if not task.done():
                        task.cancel()
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(task), timeout=1.0
                            )
                        except (asyncio.CancelledError, TimeoutError):
                            pass
                    del self._process_monitor_tasks[process_id]

                # Cancel and clean up output tasks
                if process_id in self._output_tasks:
                    for task in self._output_tasks[process_id]:
                        if not task.done():
                            task.cancel()
                            try:
                                await asyncio.wait_for(
                                    asyncio.shield(task), timeout=1.0
                                )
                            except (asyncio.CancelledError, TimeoutError):
                                pass
                    del self._output_tasks[process_id]

                # Remove from active processes
                if process_id in self.active_processes:
                    del self.active_processes[process_id]

                # Clean up execution future
                if process_id in self._execution_futures:
                    future = self._execution_futures[process_id]
                    if not future.done():
                        future.cancel()
                    del self._execution_futures[process_id]

                await self.stream_action(
                    {
                        "type": "process_cleaned_up",
                        "process_id": process_id,
                        "timestamp": time.time(),
                    }
                )

            except Exception as e:
                await self.stream_action(
                    {
                        "type": "cleanup_error",
                        "process_id": process_id,
                        "error": str(e),
                        "timestamp": time.time(),
                    }
                )

    async def _cleanup_all_processes(self):
        """Clean up all remaining processes."""
        # Get snapshot of process IDs to avoid modification during iteration
        process_ids = list(self.active_processes.keys())

        if not process_ids:
            return

        await self.stream_action(
            {
                "type": "cleanup_all_start",
                "process_count": len(process_ids),
                "timestamp": time.time(),
            }
        )

        # Clean up all processes sequentially to avoid race conditions
        for process_id in process_ids:
            await self._cleanup_single_process(process_id)

        await self.stream_action(
            {"type": "cleanup_all_completed", "timestamp": time.time()}
        )

    async def cleanup(self):
        """Main cleanup method for executor."""
        try:
            await self._cleanup_all_processes()

            await self.stream_action(
                {
                    "type": "executor_cleanup_completed",
                    "session_id": self.session_id,
                    "timestamp": time.time(),
                }
            )

        except Exception as e:
            print(f"Error during executor cleanup: {e}")

    def get_active_processes(self) -> list[str]:
        """Get list of active process IDs.

        Returns:
            List of active process IDs.
        """
        return list(self.active_processes.keys())

    async def get_process_info(self, process_id: str) -> dict[str, Any]:
        """Get detailed process information for debugging.

        Args:
            process_id: Process identifier.

        Returns:
            Dictionary with process information.
        """
        if process_id not in self.active_processes:
            return {"error": "Process not found", "process_id": process_id}

        process = self.active_processes[process_id]

        info = {
            "process_id": process_id,
            "pid": process.pid,
            "returncode": process.returncode,
            "is_running": process.returncode is None,
            "stdin_available": process.stdin is not None,
            "stdin_closing": process.stdin.is_closing() if process.stdin else None,
            "stdout_available": process.stdout is not None,
            "stderr_available": process.stderr is not None,
            "has_monitor_task": process_id in self._process_monitor_tasks,
            "has_execution_future": process_id in self._execution_futures,
            "has_output_tasks": process_id in self._output_tasks,
        }

        return info

    # ===== SYNC WRAPPERS FOR BACKWARD COMPATIBILITY =====

    def send_input_sync(self, process_id: str, input_text: str) -> bool:
        """Sync wrapper for sending input.

        Args:
            process_id: Process identifier.
            input_text: Input text to send.

        Returns:
            True if successful.
        """
        try:
            return async_to_sync(self.send_input_to_process(process_id, input_text))
        except Exception as e:
            print(f"Error sending input: {e}")
            return False

    def terminate_sync(self, process_id: str) -> bool:
        """Sync wrapper for terminating process.

        Args:
            process_id: Process identifier.

        Returns:
            True if successful.
        """
        try:
            return async_to_sync(self.terminate_process(process_id))
        except Exception as e:
            print(f"Error terminating process: {e}")
            return False

    def cleanup_sync(self):
        """Sync wrapper for cleanup."""
        try:
            async_to_sync(self.cleanup())
        except Exception as e:
            print(f"Error during cleanup: {e}")

    def get_process_info_sync(self, process_id: str) -> dict[str, Any]:
        """Sync wrapper for getting process info.

        Args:
            process_id: Process identifier.

        Returns:
            Dictionary with process information.
        """
        try:
            return async_to_sync(self.get_process_info(process_id))
        except Exception as e:
            return {"error": str(e), "process_id": process_id}
