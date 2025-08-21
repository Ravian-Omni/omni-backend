import asyncio
import subprocess
import threading
import time
import os
from typing import List, Dict, Any, Optional, Callable
from autogen.coding import LocalCommandLineCodeExecutor
from autogen.coding.base import CodeBlock, CommandLineCodeResult
from autogen.code_utils import _cmd, TIMEOUT_MSG, WIN32
from dependencies import get_websocket_manager
from utilities.async_helpers import async_to_sync

class InteractiveLocalCommandLineCodeExecutor(LocalCommandLineCodeExecutor):
    """Extension that makes ALL code execution interactive via async subprocess"""
    
    def __init__(self, session_id, *args, **kwargs):
        # Extract callback parameters
        self.session_id: str = session_id 
        
        # Call parent constructor
        super().__init__(*args, **kwargs)
        
        # Process management
        self.active_processes: Dict[str, asyncio.subprocess.Process] = {}
    
    async def stream_action(self, action_data: Dict[str, Any]):
        """Stream action to all connected clients"""
        websocket_manager = await get_websocket_manager()
        await websocket_manager.send_chat_message(
            session_id=self.session_id, 
            content=action_data, 
            source="executor"
        )
    
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
        """Execute all code blocks asynchronously and return when done"""
        
        logs_all = ""
        file_names = []
        exitcode = 0
        
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
            
            # ===== ASYNC EXECUTION WITH REAL-TIME STREAMING =====
            try:
                # Create async subprocess
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self._work_dir),
                    env=env
                )
                
                # Register for interaction
                self.active_processes[process_id] = process
                
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
                
                # Collect output while streaming
                collected_stdout = []
                collected_stderr = []
                
                # Start real-time monitoring with collection
                stdout_task = asyncio.create_task(
                    self._monitor_and_collect_stdout(process, process_id, collected_stdout)
                )
                stderr_task = asyncio.create_task(
                    self._monitor_and_collect_stderr(process, process_id, collected_stderr)
                )
                
                # Handle timeout like parent
                if self._timeout > 0:
                    try:
                        return_code = await asyncio.wait_for(
                            process.wait(), 
                            timeout=float(self._timeout)
                        )
                    except asyncio.TimeoutError:
                        # Terminate on timeout (parent's behavior)
                        process.terminate()
                        try:
                            await asyncio.wait_for(process.wait(), timeout=5)
                        except asyncio.TimeoutError:
                            process.kill()
                        
                        timeout_msg = TIMEOUT_MSG
                        logs_all += "\n" + timeout_msg
                        await self.stream_action({
                            'type': 'terminal_timeout',
                            'process_id': process_id,
                            'content': timeout_msg,
                            'timestamp': time.time()
                        })
                        exitcode = 124  # Parent's timeout exit code
                        break
                else:
                    # No timeout - wait for completion
                    return_code = await process.wait()
                
                # Wait for output collection to complete
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                
                # Combine output like parent does
                stdout_output = '\n'.join(collected_stdout) if collected_stdout else ''
                stderr_output = '\n'.join(collected_stderr) if collected_stderr else ''
                
                # Follow parent's pattern: stderr first, then stdout
                if stderr_output:
                    logs_all += stderr_output + '\n'
                if stdout_output:
                    logs_all += stdout_output + '\n'
                
                exitcode = return_code
                
                # Notify completion
                await self.stream_action({
                    'type': 'process_completed',
                    'process_id': process_id,
                    'exit_code': return_code,
                    'timestamp': time.time()
                })
                
                # Cleanup
                if process_id in self.active_processes:
                    del self.active_processes[process_id]

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
                exitcode = 1
                break
            
        # Send final execution summary via stream_action
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
    
    # async def _monitor_and_collect_stdout(self, process: asyncio.subprocess.Process, process_id: str, collector: List[str]):
    #     """Monitor stdout, stream in real-time, and collect for final output"""
    #     try:
    #         while True:
    #             line = await process.stdout.readline()
    #             if not line:
    #                 break
                
    #             output = line.decode('utf-8', errors='replace').rstrip()
    #             if output:
    #                 # Collect for final result (like parent)
    #                 collector.append(output)
                    
    #                 # Stream in real-time (new feature)
    #                 await self.stream_action({
    #                     'type': 'terminal_output',
    #                     'stream': 'stdout',
    #                     'process_id': process_id,
    #                     'content': output,
    #                     'timestamp': time.time()
    #                 })
    #     except Exception as e:
    #         await self.stream_action({
    #             'type': 'terminal_error',
    #             'process_id': process_id,
    #             'content': f"Error reading stdout: {str(e)}",
    #             'timestamp': time.time()
    #         })
    
    async def _monitor_and_collect_stdout(self, process: asyncio.subprocess.Process, process_id: str, collector: List[str]):
        """Monitor stdout with input detection"""
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                
                output = line.decode('utf-8', errors='replace').rstrip()
                if output:
                    collector.append(output)
                    
                    # Detect input prompts
                    input_indicators = ['input(', '>>> ', 'Enter ', 'Please enter', ':']
                    is_input_prompt = any(indicator in output.lower() for indicator in input_indicators)
                    
                    await self.stream_action({
                        'type': 'terminal_output',
                        'stream': 'stdout',
                        'process_id': process_id,
                        'content': output,
                        'is_input_prompt': is_input_prompt,  # Add this flag
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
        """Monitor stderr, stream in real-time, and collect for final output"""
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                
                error = line.decode('utf-8', errors='replace').rstrip()
                if error:
                    # Collect for final result (like parent)
                    collector.append(error)
                    
                    # Stream in real-time (new feature)
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
    
    # ===== FULLY ASYNC INTERFACE =====
    
    async def send_input_to_process(self, process_id: str, input_text: str) -> bool:
        """Send input to running process with better error handling"""
        if process_id not in self.active_processes:
            await self.stream_action({
                'type': 'terminal_error',
                'process_id': process_id,
                'content': f"Process {process_id} not found in active processes",
                'timestamp': time.time()
            })
            return False
        
        try:
            process = self.active_processes[process_id]
            
            # Check if process is still running
            if process.returncode is not None:
                await self.stream_action({
                    'type': 'terminal_error',
                    'process_id': process_id,
                    'content': f"Process {process_id} has already finished (exit code: {process.returncode})",
                    'timestamp': time.time()
                })
                return False
            
            # Check if stdin is available and open
            if not process.stdin:
                await self.stream_action({
                    'type': 'terminal_error',
                    'process_id': process_id,
                    'content': f"Process {process_id} stdin is not available",
                    'timestamp': time.time()
                })
                return False
            
            if process.stdin.is_closing():
                await self.stream_action({
                    'type': 'terminal_error',
                    'process_id': process_id,
                    'content': f"Process {process_id} stdin is closing",
                    'timestamp': time.time()
                })
                return False
            
            # Send input
            process.stdin.write(input_text.encode('utf-8') + b'\n')
            await process.stdin.drain()
            
            await self.stream_action({
                'type': 'input_sent',
                'process_id': process_id,
                'content': input_text,
                'timestamp': time.time()
            })
            
            # Also log that input was actually written to stdin
            await self.stream_action({
                'type': 'debug_info',
                'process_id': process_id,
                'content': f"Input '{input_text}' written to stdin successfully",
                'timestamp': time.time()
            })
            
            return True
            
        except BrokenPipeError:
            await self.stream_action({
                'type': 'terminal_error',
                'process_id': process_id,
                'content': f"Process {process_id} stdin pipe is broken (process may have ended)",
                'timestamp': time.time()
            })
            return False
        except Exception as e:
            await self.stream_action({
                'type': 'terminal_error',
                'process_id': process_id,
                'content': f"Error sending input to {process_id}: {str(e)}",
                'timestamp': time.time()
            })
            return False
    
    async def terminate_process(self, process_id: str) -> bool:
        """Terminate running process (async)"""
        if process_id not in self.active_processes:
            return False
        
        try:
            process = self.active_processes[process_id]
            process.terminate()
            
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            
            await self.stream_action({
                'type': 'process_terminated',
                'process_id': process_id,
                'timestamp': time.time()
            })
            
            # Clean up
            if process_id in self.active_processes:
                del self.active_processes[process_id]
            
            return True
        except Exception as e:
            await self.stream_action({
                'type': 'terminal_error',
                'process_id': process_id,
                'content': f"Error terminating: {str(e)}",
                'timestamp': time.time()
            })
            return False
    
    async def cleanup(self):
        """Clean up all resources (async)"""
        try:
            # Terminate all processes concurrently
            if self.active_processes:
                tasks = [
                    self.terminate_process(process_id) 
                    for process_id in list(self.active_processes.keys())
                ]
                
                # Wait for all terminations to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Log any failures
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        print(f"Failed to terminate process: {result}")
            
            # Send cleanup notification
            await self.stream_action({
                'type': 'executor_cleanup',
                'session_id': self.session_id,
                'timestamp': time.time()
            })
            
        except Exception as e:
            print(f"Error during cleanup: {e}")
    
    def get_active_processes(self) -> List[str]:
        """Get list of active process IDs (sync - this is just a data accessor)"""
        return list(self.active_processes.keys())
    
    # ===== OPTIONAL: SYNC WRAPPERS FOR BACKWARD COMPATIBILITY =====
    
    def send_input_sync(self, process_id: str, input_text: str) -> bool:
        """Sync wrapper for sending input (use only if needed for compatibility)"""
        try:
            return async_to_sync(self.send_input_to_process(process_id, input_text))
        except Exception as e:
            print(f"Error sending input: {e}")
            return False
    
    def terminate_sync(self, process_id: str) -> bool:
        """Sync wrapper for terminating process (use only if needed for compatibility)"""
        try:
            return async_to_sync(self.terminate_process(process_id))
        except Exception as e:
            print(f"Error terminating process: {e}")
            return False
    
    def cleanup_sync(self):
        """Sync wrapper for cleanup (use only if needed for compatibility)"""
        try:
            async_to_sync(self.cleanup())
        except Exception as e:
            print(f"Error during cleanup: {e}")