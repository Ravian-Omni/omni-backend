"""Async tool implementations for the LangGraph agent.

This module provides production-ready async tools that can be easily integrated
with LangGraph. Tools are simple to understand, well-documented, and handle
errors gracefully.
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles
from langchain_core.tools import tool
from loguru import logger


# =============================================================================
# FILE OPERATIONS
# =============================================================================


@tool
async def read_file_tool(path: str) -> str:
    """Read the contents of a file asynchronously.

    Args:
        path: The path to the file to read (relative or absolute).

    Returns:
        The file contents as a string, or an error message.
    """
    try:
        async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
            content = await f.read()
        return content
    except FileNotFoundError:
        return f"Error: File not found at path '{path}'"
    except PermissionError:
        return f"Error: Permission denied when trying to read '{path}'"
    except Exception as e:
        logger.error(f"Error reading file {path}: {e}")
        return f"Error reading file: {str(e)}"


@tool
async def write_file_tool(path: str, content: str) -> str:
    """Write content to a file asynchronously.

    Creates parent directories if they don't exist.

    Args:
        path: The path to the file to write.
        content: The content to write to the file.

    Returns:
        Success message or error message.
    """
    try:
        # Create parent directories if needed
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        async with aiofiles.open(path, mode="w", encoding="utf-8") as f:
            await f.write(content)
        return f"Successfully wrote {len(content)} characters to {path}"
    except PermissionError:
        return f"Error: Permission denied when trying to write to '{path}'"
    except Exception as e:
        logger.error(f"Error writing file {path}: {e}")
        return f"Error writing file: {str(e)}"


@tool
async def list_directory_tool(path: str = ".") -> str:
    """List all files and directories in a given path.

    Args:
        path: The directory path to list (defaults to current directory).

    Returns:
        Formatted list of files and directories, or error message.
    """
    try:
        items = await asyncio.to_thread(os.listdir, path)
        result = []

        for item in sorted(items):
            item_path = os.path.join(path, item)
            if os.path.isdir(item_path):
                result.append(f"[DIR]  {item}/")
            else:
                size = os.path.getsize(item_path)
                result.append(f"[FILE] {item} ({size} bytes)")

        return "\n".join(result) if result else "(empty directory)"
    except FileNotFoundError:
        return f"Error: Directory not found at path '{path}'"
    except PermissionError:
        return f"Error: Permission denied when trying to access '{path}'"
    except Exception as e:
        logger.error(f"Error listing directory {path}: {e}")
        return f"Error listing directory: {str(e)}"


@tool
async def create_directory_tool(path: str) -> str:
    """Create a new directory including parent directories if needed.

    Args:
        path: The directory path to create.

    Returns:
        Success message or error message.
    """
    try:
        await asyncio.to_thread(os.makedirs, path, exist_ok=True)
        return f"Successfully created directory: {path}"
    except PermissionError:
        return f"Error: Permission denied when trying to create '{path}'"
    except Exception as e:
        logger.error(f"Error creating directory {path}: {e}")
        return f"Error creating directory: {str(e)}"


@tool
async def delete_file_tool(path: str) -> str:
    """Delete a file or directory.

    Args:
        path: The path to delete.

    Returns:
        Success message or error message.
    """
    try:
        if os.path.isdir(path):
            await asyncio.to_thread(__import__("shutil").rmtree, path)
            return f"Successfully deleted directory: {path}"
        else:
            await asyncio.to_thread(os.remove, path)
            return f"Successfully deleted file: {path}"
    except FileNotFoundError:
        return f"Error: File or directory not found at '{path}'"
    except PermissionError:
        return f"Error: Permission denied when trying to delete '{path}'"
    except Exception as e:
        logger.error(f"Error deleting {path}: {e}")
        return f"Error deleting: {str(e)}"


# =============================================================================
# COMMAND EXECUTION
# =============================================================================


@tool
async def execute_command_tool(command: str, working_dir: str | None = None) -> str:
    """Execute a shell command asynchronously.

    Args:
        command: The shell command to execute.
        working_dir: Optional working directory for the command.

    Returns:
        Command output with exit code, or error message.
    """
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
        )

        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)

        exit_code = process.returncode or 0
        output_parts = []

        if stderr:
            output_parts.append(f"STDERR:\n{stderr.decode('utf-8', errors='replace')}")
        if stdout:
            output_parts.append(f"STDOUT:\n{stdout.decode('utf-8', errors='replace')}")

        output = "\n\n".join(output_parts) if output_parts else "(no output)"

        return f"Exit code: {exit_code}\n\n{output}"

    except asyncio.TimeoutError:
        return "Error: Command timed out after 120 seconds"
    except Exception as e:
        logger.error(f"Error executing command '{command}': {e}")
        return f"Error executing command: {str(e)}"


@tool
async def search_files_tool(
    pattern: str, path: str = ".", file_pattern: str | None = None
) -> str:
    """Search for a text pattern in files.

    Args:
        pattern: The text or regex pattern to search for.
        path: The directory to search in (defaults to current directory).
        file_pattern: Optional file name pattern to filter (e.g., '*.py').

    Returns:
        Formatted search results showing matches with line numbers.
    """
    try:
        import re

        matches = []
        exclude_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv"}

        def search_sync():
            for root, dirs, files in os.walk(path):
                # Filter out excluded directories
                dirs[:] = [d for d in dirs if d not in exclude_dirs]

                for file in files:
                    # Apply file pattern filter if provided
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
                                rel_path = os.path.relpath(file_path, path)
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

        await asyncio.to_thread(search_sync)
        return "\n\n".join(matches) if matches else "No matches found"

    except Exception as e:
        logger.error(f"Error searching files for '{pattern}': {e}")
        return f"Error searching files: {str(e)}"


# =============================================================================
# WEB & API TOOLS
# =============================================================================


@tool
async def fetch_url_tool(url: str) -> str:
    """Fetch content from a URL.

    Args:
        url: The URL to fetch.

    Returns:
        The response content as text, or error message.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.text[:10000]  # Limit to first 10k characters

    except Exception as e:
        logger.error(f"Error fetching URL {url}: {e}")
        return f"Error fetching URL: {str(e)}"


@tool
async def api_request_tool(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> str:
    """Make an HTTP API request.

    Args:
        url: The API endpoint URL.
        method: HTTP method (GET, POST, PUT, DELETE, etc.). Defaults to GET.
        headers: Optional HTTP headers.
        body: Optional request body (for POST/PUT).

    Returns:
        The API response as JSON string, or error message.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=body,
            )
            response.raise_for_status()

            # Try to parse as JSON
            try:
                return json.dumps(response.json(), indent=2)
            except Exception:
                return response.text

    except Exception as e:
        logger.error(f"Error making API request to {url}: {e}")
        return f"Error making API request: {str(e)}"


# =============================================================================
# DATA PROCESSING TOOLS
# =============================================================================


@tool
async def calculate_tool(expression: str) -> str:
    """Safely evaluate a mathematical expression.

    Args:
        expression: The mathematical expression to evaluate.

    Returns:
        The result of the calculation, or error message.
    """
    try:
        # Only allow safe math operations
        allowed_names = {
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
        }

        # Safely evaluate the expression
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return str(result)

    except Exception as e:
        logger.error(f"Error calculating '{expression}': {e}")
        return f"Error in calculation: {str(e)}"


@tool
async def parse_json_tool(json_string: str) -> str:
    """Parse and pretty-print a JSON string.

    Args:
        json_string: The JSON string to parse.

    Returns:
        Pretty-printed JSON or error message.
    """
    try:
        data = json.loads(json_string)
        return json.dumps(data, indent=2)
    except json.JSONDecodeError as e:
        return f"Error parsing JSON: {str(e)}"
    except Exception as e:
        logger.error(f"Error processing JSON: {e}")
        return f"Error: {str(e)}"


# =============================================================================
# DATETIME TOOLS
# =============================================================================


@tool
async def get_current_time_tool() -> str:
    """Get the current date and time.

    Returns:
        Current date and time in ISO format.
    """
    try:
        now = datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        logger.error(f"Error getting current time: {e}")
        return f"Error: {str(e)}"


# =============================================================================
# TOOL REGISTRY
# =============================================================================

# All available tools - easy to extend
ALL_TOOLS = [
    # File operations
    read_file_tool,
    write_file_tool,
    list_directory_tool,
    create_directory_tool,
    delete_file_tool,
    # Command execution
    execute_command_tool,
    search_files_tool,
    # Web & API
    fetch_url_tool,
    api_request_tool,
    # Data processing
    calculate_tool,
    parse_json_tool,
    # Datetime
    get_current_time_tool,
]


def get_tools() -> list:
    """Get all available tools for the agent.

    Returns:
        List of all tool instances.
    """
    return ALL_TOOLS


def get_tool_names() -> list[str]:
    """Get names of all available tools.

    Returns:
        List of tool names.
    """
    return [tool.name for tool in ALL_TOOLS]
