import asyncio
import concurrent.futures
import os
import re
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import autogen
from autogen import AssistantAgent
from autogen.agentchat.agent import Agent
from loguru import logger

from src.capabilities.file_finder import prompts
from src.capabilities.file_finder.function_description import (
    file_search_function_description,
)
from src.capabilities.file_finder.response_format import (
    FileFinderResponse,
    ProblemStatusResponse,
)
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.settings import settings
from src.configs.system_ai_config import GroupchatConfigurationManager
from src.utilities.custom_manager import ChatContext, CustomGroupChatManager


class FileSearchAgent:
    """File search agent for indexing and searching files on the filesystem."""

    # Directories to skip on macOS to avoid permission issues and improve speed
    SKIP_DIRS = {
        ".Trash",
        "Library/Caches",
        "Library/Logs",
        ".cache",
        "node_modules",
        ".git",
        ".venv",
        "__pycache__",
        "Library/Application Support/Google/Chrome",
        "Library/Application Support/Firefox",
        "Library/Mail",
        "Library/Messages",
        "/System",
        "/private",
        "/dev",
        "/cores",
        ".npm",
        ".gradle",
        ".m2",
    }

    # Common user-accessible directories on macOS
    PRIORITY_DIRS = [
        "Documents",
        "Desktop",
        "Downloads",
        "Pictures",
        "Movies",
        "Music",
        "Development",
        "Projects",
    ]

    def __init__(self, root_dir: str | None = None, max_depth: int = 6):
        """Initialize the search engine with a root directory to index.

        Args:
            root_dir (str): The root directory path to index, defaults to user's home directory
            max_depth (int): Maximum directory depth to search (prevents deep recursion)
        """
        self.root_dir = root_dir or str(Path.home())
        self.max_depth = max_depth
        self.file_index: dict[str, dict] = {}
        self.inverted_index: dict[str, set[str]] = defaultdict(set)
        self.user_home = str(Path.home())

    def _resolve_directory_path(self, directory: str | None) -> str:
        """Resolve directory path, handling common shortcuts and relative paths.

        Args:
            directory: Directory path (can be None, absolute, relative, or shortcut)

        Returns:
            Absolute directory path
        """
        if not directory:
            return self.root_dir

        # Handle common shortcuts
        shortcuts = {
            "documents": "Documents",
            "desktop": "Desktop",
            "downloads": "Downloads",
            "pictures": "Pictures",
            "photos": "Pictures",
            "movies": "Movies",
            "videos": "Movies",
            "music": "Music",
            "home": "",
            "~": "",
        }

        directory_lower = directory.lower().strip()
        if directory_lower in shortcuts:
            return os.path.join(self.user_home, shortcuts[directory_lower])

        # Expand ~ to home directory
        if directory.startswith("~"):
            directory = os.path.expanduser(directory)

        # Convert to absolute path if relative
        if not os.path.isabs(directory):
            directory = os.path.join(self.user_home, directory)

        # Verify directory exists
        if not os.path.exists(directory):
            raise ValueError(f"Directory not found: {directory}")

        if not os.path.isdir(directory):
            raise ValueError(f"Path is not a directory: {directory}")

        return directory

    def _should_skip_directory(self, path: Path, current_depth: int) -> bool:
        """Check if directory should be skipped to avoid permission issues."""
        if current_depth > self.max_depth:
            return True

        path_str = str(path)

        # Skip if any parent directory matches skip patterns
        for skip_dir in self.SKIP_DIRS:
            if skip_dir in path_str:
                return True

        # Skip hidden directories except in priority locations
        if path.name.startswith(".") and not any(
            p in path_str for p in self.PRIORITY_DIRS
        ):
            return True

        return False

    def _build_index_fast(
        self,
        search_term: str,
        file_type: str | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        created_after: datetime | None = None,
        size_min: int | None = None,
        size_max: int | None = None,
        search_directory: str | None = None,
    ) -> None:
        """Build index on-the-fly for search term with parallel processing and filters."""
        query_tokens = self._tokenize(search_term)

        # Calculate minimum match threshold based on search term length
        min_match_length = max(3, len(search_term) // 2) if search_term else 0

        # Determine search root - specific directory or priority directories
        if search_directory:
            # Search only in specified directory
            search_roots = [Path(search_directory)]
        else:
            # Use priority directories as before
            root = Path(self.root_dir)
            search_roots = [root / d for d in self.PRIORITY_DIRS if (root / d).exists()]
            if not search_roots:
                search_roots = [root]

        def index_directory(dir_path: Path, depth: int = 0):
            """Index a single directory."""
            local_files = []

            try:
                # Skip directory checks only if not explicitly searching this directory
                if not search_directory and self._should_skip_directory(
                    dir_path, depth
                ):
                    return local_files

                # For explicit directory search, only respect depth limit
                if search_directory and depth > self.max_depth:
                    return local_files

                # Use scandir for faster iteration
                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                entry_lower = entry.name.lower()

                                # Skip if file_type specified and doesn't match
                                if file_type:
                                    ext = file_type.lower()
                                    if not ext.startswith("."):
                                        ext = f".{ext}"
                                    if not entry_lower.endswith(ext):
                                        continue

                                # Get file stats for filtering
                                stat_info = entry.stat(follow_symlinks=False)

                                # Apply date filters
                                if (
                                    modified_after
                                    and stat_info.st_mtime < modified_after.timestamp()
                                ):
                                    continue
                                if (
                                    modified_before
                                    and stat_info.st_mtime > modified_before.timestamp()
                                ):
                                    continue
                                if (
                                    created_after
                                    and stat_info.st_ctime < created_after.timestamp()
                                ):
                                    continue

                                # Apply size filters
                                if size_min and stat_info.st_size < size_min:
                                    continue
                                if size_max and stat_info.st_size > size_max:
                                    continue

                                # Stricter matching: require substantial overlap
                                has_exact_match = (
                                    any(token in entry_lower for token in query_tokens)
                                    if query_tokens
                                    else True
                                )
                                has_strong_fuzzy = False

                                # Only use fuzzy matching if no exact token match
                                if not has_exact_match and query_tokens:
                                    # Check if enough characters match (minimum threshold)
                                    for token in query_tokens:
                                        if len(token) >= min_match_length:
                                            # Check for significant substring matches
                                            if any(
                                                token[i : i + min_match_length]
                                                in entry_lower
                                                for i in range(
                                                    len(token) - min_match_length + 1
                                                )
                                            ):
                                                has_strong_fuzzy = True
                                                break

                                if has_exact_match or has_strong_fuzzy:
                                    file_path = entry.path

                                    local_files.append(
                                        {
                                            "path": file_path,
                                            "name_lower": entry_lower,
                                            "size": stat_info.st_size,
                                            "mtime": stat_info.st_mtime,
                                            "ctime": stat_info.st_ctime,
                                        }
                                    )

                            elif entry.is_dir(follow_symlinks=False):
                                # Recursively index subdirectories
                                local_files.extend(
                                    index_directory(Path(entry.path), depth + 1)
                                )

                        except (PermissionError, OSError):
                            continue  # Skip files/dirs we can't access

            except (PermissionError, OSError):
                pass  # Skip directories we can't access

            return local_files

        # Start with determined search roots
        root = Path(self.root_dir)

        # Use thread pool for parallel directory scanning
        all_files = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_path = {
                executor.submit(index_directory, path): path for path in search_roots
            }

            for future in concurrent.futures.as_completed(future_to_path):
                try:
                    files = future.result()
                    all_files.extend(files)
                except Exception:
                    continue

        # Build index from collected files
        for file_info in all_files:
            file_path = file_info["path"]

            self.file_index[file_path] = {
                "path": file_path,
                "size": self._format_size(file_info["size"]),
                "modified": datetime.fromtimestamp(file_info["mtime"]).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "created": datetime.fromtimestamp(file_info["ctime"]).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }

            # Tokenize and build inverted index
            tokens = self._tokenize(file_info["name_lower"])
            for token in tokens:
                self.inverted_index[token].add(file_path)

                # Add trigrams
                for trigram in self._get_trigrams(token):
                    self.inverted_index[trigram].add(file_path)

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into searchable terms."""
        return re.findall(r"\w+", text.lower())

    def _get_trigrams(self, text: str) -> set[str]:
        """Generate character trigrams for fuzzy matching."""
        if len(text) < 3:
            return {text}
        return {text[i : i + 3] for i in range(len(text) - 2)}

    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

    def _calculate_relevance(self, query_tokens: list[str], file_path: str) -> float:
        """Calculate relevance score for a file based on the query."""
        file_name = os.path.basename(file_path).lower()

        # If no query tokens (filter-only search), return base score
        if not query_tokens:
            return 1.0

        # Exact match bonus
        exact_match_score = sum(1 for token in query_tokens if token in file_name)

        # Only calculate fuzzy score if there's some exact match
        if exact_match_score == 0:
            # No exact token matches - very low score
            query_str = "".join(query_tokens)
            name_without_ext = os.path.splitext(file_name)[0]

            # Require high similarity (>0.6) for fuzzy-only matches
            fuzzy_score = max(
                SequenceMatcher(None, query_str, file_name).ratio(),
                SequenceMatcher(None, query_str, name_without_ext).ratio(),
            )

            # Reject weak fuzzy matches
            if fuzzy_score < 0.6:
                return 0.0

            return 0.3 * fuzzy_score  # Lower weight for fuzzy-only

        # Has exact matches - calculate normally
        query_str = " ".join(query_tokens)
        name_without_ext = os.path.splitext(file_name)[0]

        fuzzy_score = max(
            SequenceMatcher(None, query_str, file_name).ratio(),
            SequenceMatcher(None, query_str, name_without_ext).ratio(),
        )

        # Bonus for matches at start of filename
        starts_with_bonus = 0.3 if file_name.startswith(query_tokens[0]) else 0

        # Combine scores - higher weight on exact matches
        return (
            0.6 * exact_match_score / len(query_tokens)
            + 0.3 * fuzzy_score
            + starts_with_bonus
        )

    def search_files(
        self,
        search_term: str,
        file_type: str | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        created_after: datetime | None = None,
        size_min: int | None = None,
        size_max: int | None = None,
        directory: str | None = None,
        max_results: int = 5,
    ) -> list[dict[str, str]]:
        """Search for files matching the term and optional filters.

        Args:
            search_term (str): Search query (can be empty for filter-only search)
            file_type (Optional[str]): File extension to filter by (without dot)
            modified_after (Optional[datetime]): Only files modified after this date
            modified_before (Optional[datetime]): Only files modified before this date
            created_after (Optional[datetime]): Only files created after this date
            size_min (Optional[int]): Minimum file size in bytes
            size_max (Optional[int]): Maximum file size in bytes
            directory (Optional[str]): Specific directory to search in (can use shortcuts like 'Documents', 'Desktop')
            max_results (int): Maximum number of results to return, defaults to 5

        Returns:
            List[Dict[str, str]]: List of top matching files with metadata
        """
        query_tokens = self._tokenize(search_term)

        # Resolve directory path if provided
        search_directory = None
        if directory:
            try:
                search_directory = self._resolve_directory_path(directory)
            except ValueError as e:
                print(f"Warning: {e}")
                return []

        # Build index on-the-fly with search-term and filter constraints
        self._build_index_fast(
            search_term,
            file_type,
            modified_after,
            modified_before,
            created_after,
            size_min,
            size_max,
            search_directory,
        )

        # Get candidate files - now with stricter filtering
        candidate_files = set()

        if query_tokens:
            for token in query_tokens:
                # Direct token matches only (removed trigram matching here)
                candidate_files.update(self.inverted_index.get(token, set()))
        else:
            # If no search term, return all indexed files (filter-only search)
            candidate_files = set(self.file_index.keys())

        if not candidate_files:
            return []

        # Score and sort results
        scored_results = []
        for file_path in candidate_files:
            score = self._calculate_relevance(query_tokens, file_path)
            # Higher threshold - only include good matches
            if score > 0.3:
                result = self.file_index[file_path].copy()
                result["score"] = score
                scored_results.append(result)

        # Sort by relevance
        scored_results.sort(key=lambda x: x["score"], reverse=True)

        # Return top results without score
        top_results = scored_results[:max_results]
        for result in top_results:
            result.pop("score", None)

        return top_results


def file_search_function(
    search_term: str,
    file_type: str | None = None,
    modified_after: str | None = None,
    modified_before: str | None = None,
    created_after: str | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    directory: str | None = None,
    max_results: int = 20,
) -> list[dict[str, str]]:
    """Search for files on macOS system by name, filters, and optionally within a specific directory.

    This function searches for files matching the search term and/or filter criteria. By default,
    it searches common user directories (Documents, Desktop, Downloads, etc.), but you can specify
    a particular directory to search in using the 'directory' parameter.

    Use this function when the user wants to:
    - Find a file by name or partial name (e.g., "find my report", "search for budget.xlsx")
    - List all files in a specific directory (e.g., "show all files in Documents", "list files in Desktop")
    - Find files in a specific location (e.g., "find PDFs in Downloads", "search for images in Pictures")
    - Locate files of a specific type (e.g., "find all PDFs named invoice")
    - Find files modified within a date range (e.g., "files modified last week")
    - Find files by size (e.g., "large files over 100MB", "small images under 1MB")
    - Combine multiple criteria (e.g., "PDFs in Documents modified yesterday larger than 5MB")

    Args:
        search_term (str): The filename or partial filename to search for (can be empty for filter-only or list all)
        file_type (Optional[str]): File extension without dot (e.g., "pdf", "docx", "txt")
        modified_after (Optional[str]): ISO format datetime string (e.g., "2024-01-01T00:00:00")
        modified_before (Optional[str]): ISO format datetime string
        created_after (Optional[str]): ISO format datetime string
        size_min (Optional[int]): Minimum file size in bytes (e.g., 1048576 for 1MB)
        size_max (Optional[int]): Maximum file size in bytes
        directory (Optional[str]): Specific directory to search in. Can be:
            - Absolute path: "/Users/username/Projects"
            - Relative path: "Projects/Python"
            - Home-relative: "~/Documents"
            - Shortcuts: "Documents", "Desktop", "Downloads", "Pictures", "Movies", "Music", "Home"
        max_results (int): Maximum number of results to return (default: 20)

    Returns:
        list[dict[str, str]]: List of matching files with 'path', 'size', 'modified', and 'created' date

    Examples:
        - search_files_with_agent("invoice") - finds all files with "invoice" in the name
        - search_files_with_agent("", directory="Documents") - lists all files in Documents
        - search_files_with_agent("", file_type="pdf", directory="Downloads") - all PDFs in Downloads
        - search_files_with_agent("budget", directory="Desktop") - budget files on Desktop
        - search_files_with_agent("", directory="Pictures", file_type="jpg", size_max=1048576) - small JPGs in Pictures
        - search_files_with_agent("report", modified_after="2024-10-01T00:00:00", directory="Documents") - recent reports in Documents
    """
    file_agent = FileSearchAgent()

    # Convert string dates to datetime objects if provided
    modified_after_dt = (
        datetime.fromisoformat(modified_after) if modified_after else None
    )
    modified_before_dt = (
        datetime.fromisoformat(modified_before) if modified_before else None
    )
    created_after_dt = datetime.fromisoformat(created_after) if created_after else None

    # Build search description
    filters = []
    if file_type:
        filters.append(f"type: .{file_type}")
    if directory:
        filters.append(f"in: {directory}")
    if modified_after:
        filters.append(f"modified after: {modified_after}")
    if modified_before:
        filters.append(f"modified before: {modified_before}")
    if created_after:
        filters.append(f"created after: {created_after}")
    if size_min:
        filters.append(f"size >= {file_agent._format_size(size_min)}")
    if size_max:
        filters.append(f"size <= {file_agent._format_size(size_max)}")

    search_desc = f"'{search_term}'" if search_term else "all files"
    if filters:
        search_desc += f" [{', '.join(filters)}]"

    print(f"\nSearching for files containing {search_desc}...")

    results = file_agent.search_files(
        search_term,
        file_type,
        modified_after_dt,
        modified_before_dt,
        created_after_dt,
        size_min,
        size_max,
        directory,
        max_results,
    )

    if results:
        print(f"\nFound {len(results)} matching files:")
        for idx, result in enumerate(results, 1):
            print(f"\n{idx}. {os.path.basename(result['path'])}")
            print(f"   Path: {result['path']}")
            print(f"   Size: {result['size']}")
            print(f"   Modified: {result['modified']}")
            print(f"   Created: {result['created']}")
    else:
        print("\nNo files found matching the search criteria.")

    return results


class FileFinder:
    """File finder capability manager for multi-agent file search workflows."""

    def __init__(self, context: ChatContext):
        self.context = context
        self.groupchat_config = (
            GroupchatConfigurationManager.get_instance().get_groupchat_configuration(
                "file_finder"
            )
        )
        self.llm_config = LLMConfigManager.get_config("default")
        self.agents = self.get_agents()
        autogen.register_function(
            file_search_function,
            caller=self.file_finder,
            executor=self.user_proxy,
            name="file_search_function",
            description=file_search_function_description,
        )
        self.get_chat_manager()

    def _check_cancellation(self):
        """Check if the chat should be cancelled."""
        if (
            self.context.cancellation_token
            and self.context.cancellation_token.is_cancelled()
        ):
            raise asyncio.CancelledError(
                f"Group chat cancelled for session {self.context.chat_id}"
            )

    def file_finder_planner(self):
        """Create and configure the file finder planner agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("file_finder_planner").llm_config
            or "default"
        )
        llm_file_finder_planner = LLMConfigManager.get_config(llm_config_name)
        return autogen.AssistantAgent(
            name="file_finder_planner",
            llm_config=llm_file_finder_planner,
            system_message=prompts.planner.format(
                CURRENT_DATE=settings.get_date_time_now().date(),
                CURRENT_DATETIME=settings.get_date_time_now(),
            ),
        )

    def file_finder(self):
        """Create and configure the file finder agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("file_finder").llm_config
            or "default"
        )
        llm_file_finder = LLMConfigManager.get_config(llm_config_name)
        return autogen.AssistantAgent(
            name="file_finder",
            llm_config=llm_file_finder,
            system_message=prompts.file_finder,
        )

    def user_proxy(self):
        """Create and configure the user proxy agent for code execution."""
        return autogen.UserProxyAgent(
            name="user_proxy",
            llm_config=self.llm_config,
            human_input_mode="NEVER",
            is_termination_msg=lambda x: x.get("content", "")
            .rstrip()
            .endswith("TERMINATE"),
            code_execution_config={
                "work_dir": "file_search_workspace",
                "use_docker": False,
            },
        )

    def prob_status_checker(self):
        """Create and configure the problem status checker agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("prob_status_checker").llm_config
            or "default"
        )
        llm_prob_status_checker = LLMConfigManager.get_config(llm_config_name)
        llm_prob_status_checker["response_format"] = ProblemStatusResponse
        return AssistantAgent(
            name="prob_status_checker",
            description="""call this agent to check if the Task specified by the user has been completed""",
            system_message=prompts.prob_status_checker,
            llm_config=llm_prob_status_checker,
        )

    def process_completion(self):
        """Create and configure the process completion agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("process_completion").llm_config
            or "default"
        )
        llm_process_completion = LLMConfigManager.get_config(llm_config_name)
        llm_process_completion["response_format"] = FileFinderResponse
        return AssistantAgent(
            name="process_completion",
            llm_config=llm_process_completion,
            description="Let group manager know that the process is completed. ",
            system_message=prompts.process_completion,
        )

    # static custom speaker selection, no dynamic agent selection or condition chat routing
    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        """Select the next speaker based on conversation flow logic."""
        try:
            self._check_cancellation()

            messages = groupchat.messages
            if len(messages) == 1 or last_speaker.name == "chat_manager":
                print("Initial query received ")
                return groupchat.agent_by_name("file_finder_planner")
            elif last_speaker.name == "file_finder_planner":
                return groupchat.agent_by_name("file_finder")
            elif last_speaker.name == "file_finder":
                return groupchat.agent_by_name("user_proxy")
            elif last_speaker.name == "user_proxy":
                return groupchat.agent_by_name("prob_status_checker")
            elif last_speaker.name == "prob_status_checker":
                # if "yes" in messages[-1]["content"].lower():
                #     return groupchat.agent_by_name("process_completion")
                # else:
                #     return groupchat.agent_by_name("file_finder_planner")
                return groupchat.agent_by_name("process_completion")
            return None

        except asyncio.CancelledError:
            logger.info(
                f"Speaker selection cancelled for session {self.context.chat_id}"
            )
            # Return process_completion to gracefully end the chat
            raise

    def get_agents(self) -> list[Agent]:
        """Initialize and return all agents for the file finder workflow."""
        self.file_finder_planner = self.file_finder_planner()
        self.file_finder = self.file_finder()
        self.user_proxy = self.user_proxy()
        self.prob_status_checker = self.prob_status_checker()
        self.process_completion = self.process_completion()

        return [
            self.file_finder_planner,
            self.file_finder,
            self.user_proxy,
            self.prob_status_checker,
            self.process_completion,
        ]

    def get_chat_manager(self):
        """Create and configure the group chat manager."""
        self.groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self.custom_speaker_selection_func,
            max_round=25,
        )
        self.manager = CustomGroupChatManager(
            groupchat=self.groupchat,
            llm_config=self.llm_config,
            chat_context=self.context,
            human_input_mode="ALWAYS",
        )
        return self.groupchat, self.manager
