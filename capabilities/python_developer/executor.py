import asyncio
import subprocess
import threading
import time
import os
import signal
from typing import List, Dict, Any, Optional, Callable
from autogen.coding import LocalCommandLineCodeExecutor
from autogen.coding.base import CodeBlock, CommandLineCodeResult
from autogen.code_utils import _cmd, TIMEOUT_MSG, WIN32
from dependencies import get_websocket_manager
from utilities.async_helpers import async_to_sync

class InteractiveLocalCommandLineCodeExecutor(LocalCommandLineCodeExecutor):
    """Extension that makes ALL code execution interactive via async subprocess with proper lifecycle management"""
    
    def __init__(self, session_id, *args, **kwargs):
        self.session_id: str = session_id 
        super().__init__(*args, **kwargs)
        
        # Enhanced process management
        self.active_processes: Dict[str, asyncio.subprocess.Process] = {}
        self._execution_futures: Dict[str, asyncio.Future] = {}  # Track execution futures
        self._process_monitor_tasks: Dict[str, asyncio.Task] = {}  # Monitor tasks
        self._output_tasks: Dict[str, List[asyncio.Task]] = {}  # Output monitoring tasks
    
    async def stream_action(self, action_data: Dict[str, Any]):
        """Stream action to all connected clients"""
        try:
            websocket_manager = await get_websocket_manager()
            await websocket_manager.send_chat_message(
                session_id=self.session_id, 
                content=action_data, 
                source="executor"
            )
        except Exception as e:
            print(f"Error streaming action: {e}")
    
    def _execute_code_dont_check_setup(self, code_blocks: List[CodeBlock]) -> CommandLineCodeResult:
        """Override to make ALL code execution async and interactive"""
        try:
            return async_to_sync(self._async_execute_blocks(code_blocks))
        except Exception as e:
            return CommandLineCodeResult(
                exit_code=1,
                output=f"Execution error: {str(e)}"
            )
    
    async def _async_execute_blocks(self, code_blocks: List[CodeBlock]) -> CommandLineCodeResult:
        """Execute all code blocks asynchronously with proper lifecycle management"""
        
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
                    await self.stream_action({
                        'type': 'terminal_error',
                        'process_id': process_id,
                        'content': error_msg,
                        'timestamp': time.time()
                    })
                    break

                # Check execution policy (parent's logic)
                execute_code = self.execution_policies.get(lang, False)
                
                # Get filename (parent's logic)
                try:
                    from autogen.coding.utils import _get_file_name_from_content
                    filename = _get_file_name_from_content(code, self._work_dir)
                except ValueError:
                    return CommandLineCodeResult(exit_code=1, output="Filename is not in the workspace")

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
                    await self.stream_action({
                        'type': 'terminal_info',
                        'process_id': process_id,
                        'content': save_msg.strip(),
                        'timestamp': time.time()
                    })
                    exitcode = 0
                    continue

                # Prepare command (parent's logic)
                program = _cmd(lang)
                cmd = [program, str(written_file.absolute())]
                env = os.environ.copy()

                # Virtual environment (parent's logic)
                if self._virtual_env_context:
                    virtual_env_abs_path = os.path.abspath(self._virtual_env_context.bin_path)
                    path_with_virtualenv = rf"{virtual_env_abs_path}{os.pathsep}{env['PATH']}"
                    env["PATH"] = path_with_virtualenv
                    if WIN32:
                        activation_script = os.path.join(virtual_env_abs_path, "activate.bat")
                        cmd = [activation_script, "&&", *cmd]
                
                # ===== ENHANCED ASYNC EXECUTION WITH LIFECYCLE MANAGEMENT =====
                try:
                    # Create async subprocess
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(self._work_dir),
                        env=env,
                        bufsize=0  # Unbuffered for better real-time interaction
                    )
                    
                    # Register process
                    self.active_processes[process_id] = process
                    
                    # Create execution future
                    execution_future = asyncio.Future()
                    self._execution_futures[process_id] = execution_future
                    
                    # Start process lifecycle monitor
                    monitor_task = asyncio.create_task(
                        self._monitor_process_lifecycle(process, process_id, execution_future)
                    )
                    self._process_monitor_tasks[process_id] = monitor_task
                    
                    # Notify process started
                    await self.stream_action({
                        'type': 'process_started',
                        'process_id': process_id,
                        'pid': process.pid,
                        'command': ' '.join(cmd),
                        'file': str(written_file),
                        'language': lang,
                        'timestamp': time.time()
                    })
                    
                    # Start output monitoring
                    collected_stdout = []
                    collected_stderr = []
                    
                    stdout_task = asyncio.create_task(
                        self._monitor_and_collect_stdout(process, process_id, collected_stdout)
                    )
                    stderr_task = asyncio.create_task(
                        self._monitor_and_collect_stderr(process, process_id, collected_stderr)
                    )
                    
                    # Store output tasks for cleanup
                    self._output_tasks[process_id] = [stdout_task, stderr_task]
                    
                    # Wait for process completion with proper timeout handling
                    try:
                        if self._timeout > 0:
                            # Wait with timeout
                            return_code = await asyncio.wait_for(
                                execution_future,
                                timeout=float(self._timeout)
                            )
                        else:
                            # Wait indefinitely
                            return_code = await execution_future
                            
                    except asyncio.TimeoutError:
                        # Handle timeout
                        await self._handle_process_timeout(process_id)
                        return_code = 124
                        break
                    
                    except asyncio.CancelledError:
                        # Process was manually terminated
                        await self.stream_action({
                            'type': 'process_cancelled',
                            'process_id': process_id,
                            'timestamp': time.time()
                        })
                        return_code = 130  # SIGINT exit code
                        break
                    
                    # Wait for output collection to complete
                    await asyncio.gather(*self._output_tasks[process_id], return_exceptions=True)
                    
                    # Combine output like parent does
                    stdout_output = '\n'.join(collected_stdout) if collected_stdout else ''
                    stderr_output = '\n'.join(collected_stderr) if collected_stderr else ''
                    
                    # Follow parent's pattern: stderr first, then stdout
                    if stderr_output:
                        logs_all += stderr_output + '\n'
                    if stdout_output:
                        logs_all += stdout_output + '\n'
                    
                    exitcode = return_code
                    
                    # Cleanup this process
                    await self._cleanup_single_process(process_id)
                    
                    # Break on error (parent's behavior)
                    if exitcode != 0:
                        break
                        
                except Exception as e:
                    error_msg = f"Execution error: {str(e)}"
                    logs_all += "\n" + error_msg
                    await self.stream_action({
                        'type': 'terminal_error',
                        'process_id': process_id,
                        'content': error_msg,
                        'timestamp': time.time()
                    })
                    await self._cleanup_single_process(process_id)
                    exitcode = 1
                    break
            
        finally:
            # Ensure all processes are cleaned up
            await self._cleanup_all_processes()
        
        # Send final execution summary
        await self.stream_action({
            'type': 'execution_summary',
            'total_blocks': len(code_blocks),
            'exit_code': exitcode,
            'output_length': len(logs_all),
            'timestamp': time.time()
        })
        
        # Return result exactly like parent
        code_file = str(file_names[0]) if len(file_names) > 0 else None
        return CommandLineCodeResult(exit_code=exitcode, output=logs_all, code_file=code_file)
    
    async def _monitor_process_lifecycle(self, process: asyncio.subprocess.Process, process_id: str, future: asyncio.Future):
        """Monitor process lifecycle and handle completion/termination"""
        try:
            # Wait for process to complete naturally
            return_code = await process.wait()
            
            # Check if process was terminated by signal
            if return_code < 0:
                signal_name = self._get_signal_name(-return_code)
                await self.stream_action({
                    'type': 'process_terminated_by_signal',
                    'process_id': process_id,
                    'signal': signal_name,
                    'return_code': return_code,
                    'timestamp': time.time()
                })
            else:
                await self.stream_action({
                    'type': 'process_completed',
                    'process_id': process_id,
                    'exit_code': return_code,
                    'timestamp': time.time()
                })
            
            # Set the future result
            if not future.done():
                future.set_result(return_code)
                
        except Exception as e:
            await self.stream_action({
                'type': 'process_monitor_error',
                'process_id': process_id,
                'error': str(e),
                'timestamp': time.time()
            })
            
            if not future.done():
                future.set_exception(e)
    
    def _get_signal_name(self, signal_num: int) -> str:
        """Get human-readable signal name"""
        signal_names = {
            signal.SIGTERM: "SIGTERM",
            signal.SIGKILL: "SIGKILL", 
            signal.SIGINT: "SIGINT",
        }
        
        # Add more signals for Unix systems
        if hasattr(signal, 'SIGHUP'):
            signal_names[signal.SIGHUP] = "SIGHUP"
        if hasattr(signal, 'SIGQUIT'):
            signal_names[signal.SIGQUIT] = "SIGQUIT"
            
        return signal_names.get(signal_num, f"SIGNAL_{signal_num}")
    
    async def _handle_process_timeout(self, process_id: str):
        """Handle process timeout with graceful and forceful termination"""
        if process_id not in self.active_processes:
            return
            
        process = self.active_processes[process_id]
        
        await self.stream_action({
            'type': 'process_timeout_start',
            'process_id': process_id,
            'timestamp': time.time()
        })
        
        # Try graceful termination first
        process.terminate()
        
        try:
            # Wait 5 seconds for graceful termination
            await asyncio.wait_for(process.wait(), timeout=5)
            await self.stream_action({
                'type': 'process_terminated_gracefully',
                'process_id': process_id,
                'timestamp': time.time()
            })
        except asyncio.TimeoutError:
            # Force kill
            process.kill()
            await process.wait()
            await self.stream_action({
                'type': 'process_killed_forcefully',
                'process_id': process_id,
                'timestamp': time.time()
            })
    
    async def _monitor_and_collect_stdout(self, process: asyncio.subprocess.Process, process_id: str, collector: List[str]):
        """Monitor stdout with enhanced input detection and real-time streaming"""
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                
                output = line.decode('utf-8', errors='replace').rstrip()
                if output:
                    collector.append(output)
                    
                    # Enhanced input prompt detection
                    input_indicators = [
                        'input(', '>>> ', '... ', 'Enter ', 'enter ', 'Please enter', 
                        'Type ', 'type ', ':', '? ', 'Password:', 'password:', 
                        'Choose', 'choose', 'Select', 'select', 'Y/N', 'y/n'
                    ]
                    
                    output_lower = output.lower().strip()
                    is_input_prompt = (
                        any(indicator in output_lower for indicator in input_indicators) or
                        output.endswith(':') or output.endswith('?') or
                        'input' in output_lower or 'enter' in output_lower
                    )
                    
                    await self.stream_action({
                        'type': 'terminal_output',
                        'stream': 'stdout',
                        'process_id': process_id,
                        'content': output,
                        'is_input_prompt': is_input_prompt,
                        'timestamp': time.time()
                    })
                    
                    if is_input_prompt:
                        await self.stream_action({
                            'type': 'input_prompt_detected',
                            'process_id': process_id,
                            'content': f"Input prompt detected: {output}",
                            'timestamp': time.time()
                        })
                        
        except Exception as e:
            await self.stream_action({
                'type': 'terminal_error',
                'process_id': process_id,
                'content': f"Error reading stdout: {str(e)}",
                'timestamp': time.time()
            })
    
    async def _monitor_and_collect_stderr(self, process: asyncio.subprocess.Process, process_id: str, collector: List[str]):
        """Monitor stderr with real-time streaming"""
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                
                error = line.decode('utf-8', errors='replace').rstrip()
                if error:
                    collector.append(error)
                    
                    await self.stream_action({
                        'type': 'terminal_output',
                        'stream': 'stderr',
                        'process_id': process_id,
                        'content': error,
                        'timestamp': time.time()
                    })
        except Exception as e:
            await self.stream_action({
                'type': 'terminal_error',
                'process_id': process_id,
                'content': f"Error reading stderr: {str(e)}",
                'timestamp': time.time()
            })
    
    async def send_input_to_process(self, process_id: str, input_text: str) -> bool:
        """Send input to running process with comprehensive error handling"""
        if process_id not in self.active_processes:
            await self.stream_action({
                'type': 'input_error',
                'process_id': process_id,
                'content': f"Process {process_id} not found in active processes",
                'available_processes': list(self.active_processes.keys()),
                'timestamp': time.time()
            })
            return False
        
        try:
            process = self.active_processes[process_id]
            
            # Check if process is still running
            if process.returncode is not None:
                await self.stream_action({
                    'type': 'input_error',
                    'process_id': process_id,
                    'content': f"Process {process_id} has finished (exit code: {process.returncode})",
                    'timestamp': time.time()
                })
                return False
            
            # Check stdin availability
            if not process.stdin:
                await self.stream_action({
                    'type': 'input_error',
                    'process_id': process_id,
                    'content': f"Process {process_id} stdin is not available",
                    'timestamp': time.time()
                })
                return False
            
            if process.stdin.is_closing():
                await self.stream_action({
                    'type': 'input_error',
                    'process_id': process_id,
                    'content': f"Process {process_id} stdin is closing",
                    'timestamp': time.time()
                })
                return False
            
            # Send input with newline
            input_bytes = input_text.encode('utf-8') + b'\n'
            process.stdin.write(input_bytes)
            await process.stdin.drain()
            
            await self.stream_action({
                'type': 'input_sent',
                'process_id': process_id,
                'content': input_text,
                'bytes_written': len(input_bytes),
                'timestamp': time.time()
            })
            
            return True
            
        except BrokenPipeError:
            await self.stream_action({
                'type': 'input_error',
                'process_id': process_id,
                'content': f"Process {process_id} stdin pipe is broken (process ended)",
                'timestamp': time.time()
            })
            return False
        except Exception as e:
            await self.stream_action({
                'type': 'input_error',
                'process_id': process_id,
                'content': f"Error sending input: {str(e)}",
                'timestamp': time.time()
            })
            return False
    
    async def terminate_process(self, process_id: str) -> bool:
        """Terminate a specific process with proper cleanup"""
        if process_id not in self.active_processes:
            await self.stream_action({
                'type': 'terminate_failed',
                'process_id': process_id,
                'reason': 'Process not found',
                'timestamp': time.time()
            })
            return False
        
        try:
            process = self.active_processes[process_id]
            
            await self.stream_action({
                'type': 'termination_requested',
                'process_id': process_id,
                'timestamp': time.time()
            })
            
            # Cancel the execution future first
            if process_id in self._execution_futures:
                future = self._execution_futures[process_id]
                if not future.done():
                    future.cancel()
            
            # Terminate the process gracefully
            process.terminate()
            
            try:
                # Wait for graceful termination
                await asyncio.wait_for(process.wait(), timeout=5)
                await self.stream_action({
                    'type': 'process_terminated',
                    'process_id': process_id,
                    'method': 'graceful',
                    'timestamp': time.time()
                })
            except asyncio.TimeoutError:
                # Force kill if doesn't terminate gracefully
                process.kill()
                await process.wait()
                await self.stream_action({
                    'type': 'process_terminated',
                    'process_id': process_id,
                    'method': 'forced',
                    'timestamp': time.time()
                })
            
            # Cleanup
            await self._cleanup_single_process(process_id)
            return True
            
        except Exception as e:
            await self.stream_action({
                'type': 'termination_error',
                'process_id': process_id,
                'error': str(e),
                'timestamp': time.time()
            })
            return False
    
    async def _cleanup_single_process(self, process_id: str):
        """Clean up a single process and all its resources"""
        try:
            # Cancel and clean up monitor task
            if process_id in self._process_monitor_tasks:
                task = self._process_monitor_tasks[process_id]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del self._process_monitor_tasks[process_id]
            
            # Cancel and clean up output tasks
            if process_id in self._output_tasks:
                for task in self._output_tasks[process_id]:
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
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
            
            await self.stream_action({
                'type': 'process_cleaned_up',
                'process_id': process_id,
                'timestamp': time.time()
            })
            
        except Exception as e:
            await self.stream_action({
                'type': 'cleanup_error',
                'process_id': process_id,
                'error': str(e),
                'timestamp': time.time()
            })
    
    async def _cleanup_all_processes(self):
        """Clean up all remaining processes"""
        if not self.active_processes:
            return
        
        await self.stream_action({
            'type': 'cleanup_all_start',
            'process_count': len(self.active_processes),
            'timestamp': time.time()
        })
        
        # Clean up all processes concurrently
        cleanup_tasks = []
        for process_id in list(self.active_processes.keys()):
            task = asyncio.create_task(self._cleanup_single_process(process_id))
            cleanup_tasks.append(task)
        
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        
        await self.stream_action({
            'type': 'cleanup_all_completed',
            'timestamp': time.time()
        })
    
    async def cleanup(self):
        """Main cleanup method for executor"""
        try:
            await self._cleanup_all_processes()
            
            await self.stream_action({
                'type': 'executor_cleanup_completed',
                'session_id': self.session_id,
                'timestamp': time.time()
            })
            
        except Exception as e:
            print(f"Error during executor cleanup: {e}")
    
    def get_active_processes(self) -> List[str]:
        """Get list of active process IDs"""
        return list(self.active_processes.keys())
    
    async def get_process_info(self, process_id: str) -> Dict[str, Any]:
        """Get detailed process information for debugging"""
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
        """Sync wrapper for sending input"""
        try:
            return async_to_sync(self.send_input_to_process(process_id, input_text))
        except Exception as e:
            print(f"Error sending input: {e}")
            return False
    
    def terminate_sync(self, process_id: str) -> bool:
        """Sync wrapper for terminating process"""
        try:
            return async_to_sync(self.terminate_process(process_id))
        except Exception as e:
            print(f"Error terminating process: {e}")
            return False
    
    def cleanup_sync(self):
        """Sync wrapper for cleanup"""
        try:
            async_to_sync(self.cleanup())
        except Exception as e:
            print(f"Error during cleanup: {e}")
    
    def get_process_info_sync(self, process_id: str) -> Dict[str, Any]:
        """Sync wrapper for getting process info"""
        try:
            return async_to_sync(self.get_process_info(process_id))
        except Exception as e:
            return {"error": str(e), "process_id": process_id}