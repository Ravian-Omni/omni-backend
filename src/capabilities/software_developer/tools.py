"""Async tool implementations for the Software Developer capability.

This module provides async-native tool implementations for file operations,
git operations, code analysis, and command execution.
"""

import ast
import asyncio
import os
import re
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

import git
from loguru import logger


class AsyncToolRegistry:
    """Registry for async tool handlers with execution support."""

    def __init__(self, working_directory: str = "."):
        """Initialize the tool registry.

        Args:
            working_directory: Base directory for file operations.
        """
        self.working_directory = os.path.abspath(working_directory)
        self._tools: dict[str, callable] = {}
        self._register_all_tools()

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
                # Run sync functions in executor to avoid blocking
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
        """Execute shell command asynchronously."""
        try:
            cwd = (
                self._resolve_path(working_dir)
                if working_dir
                else self.working_directory
            )

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                output = stdout.decode() if stdout else stderr.decode()
                return f"Exit code: {process.returncode}\n{output}"
            except TimeoutError:
                process.kill()
                return f"Error: Command timed out after {timeout} seconds"

        except Exception as e:
            return f"Error executing command: {str(e)}"

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
                for file in untracked[:20]:  # Limit output
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
                # Generic pattern matching for JS/TS files
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
                # JS/TS imports
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
        "description": "Execute a shell command and return its output. Use with caution.",
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
