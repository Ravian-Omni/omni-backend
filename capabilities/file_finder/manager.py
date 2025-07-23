
import autogen
from pathlib import Path
import os
import json
from datetime import datetime
from autogen import register_function
from autogen.agentchat.agent import Agent
from typing import List, Dict, Any
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager
from typing import List, Dict, Optional, Union
import asyncio
from pathlib import Path
from typing import List, Dict, Set, Optional
import re
from difflib import SequenceMatcher
from collections import defaultdict
import time
from datetime import datetime
from capabilities.file_finder import prompts
from configs.llm_configs_manager import LLMConfigManager
from utilities.custom_manager import CustomGroupChatManager, ChatContext
from configs.settings import settings
from capabilities.file_finder.response_format import ProblemStatusResponse, FileFinderResponse
from loguru import logger
class FileSearchAgent:
    def __init__(self, root_dir: str = str(Path.home())):
        """
        Initialize the search engine with a root directory to index.
        
        Args:
            root_dir (str): The root directory path to index, defaults to user's home directory
        """
        self.root_dir = root_dir
        self.file_index: Dict[str, Dict] = {}
        self.inverted_index: Dict[str, Set[str]] = defaultdict(set)
        self._build_index()

    def _build_index(self) -> None:
        """Build the search index from the root directory."""
        for path in Path(self.root_dir).rglob('*'):
            if path.is_file():
                file_path = str(path)
                file_name = path.name.lower()

                # Store file metadata
                stats = path.stat()
                self.file_index[file_path] = {
                    'path': file_path,
                    'size': self._format_size(stats.st_size),
                    'modified': datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    }

                # Create tokens from filename
                tokens = self._tokenize(file_name)

                # Build inverted index
                for token in tokens:
                    self.inverted_index[token].add(file_path)

                    # Add character trigrams for fuzzy matching
                    trigrams = self._get_trigrams(token)
                    for trigram in trigrams:
                        self.inverted_index[trigram].add(file_path)

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into searchable terms."""
        return re.findall(r'\w+', text.lower())

    def _get_trigrams(self, text: str) -> Set[str]:
        """Generate character trigrams for fuzzy matching."""
        if len(text) < 3:
            return {text}
        return {text[i:i + 3] for i in range(len(text) - 2)}

    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

    def _calculate_relevance(self, query_tokens: List[str], file_path: str) -> float:
        """Calculate relevance score for a file based on the query."""
        file_name = os.path.basename(file_path).lower()

        # Base score from exact matches
        exact_match_score = sum(1 for token in query_tokens if token in file_name)

        # Fuzzy matching score
        fuzzy_score = max(
            SequenceMatcher(None, ' '.join(query_tokens), part).ratio()
            for part in [file_name, os.path.splitext(file_name)[0]]
            )

        # Combine scores
        return (0.6 * exact_match_score / len(query_tokens) +
                0.4 * fuzzy_score)


    def search_files(self, search_term: str, file_type: Optional[str] = None, max_results: int = 20) -> \
    List[Dict[str, str]]:
        """
        Search for files matching the term and optional file type.
        
        Args:
            search_term (str): Search query
            file_type (Optional[str]): File extension to filter by (without dot)
            max_results (int): Maximum number of results to return, defaults to 20
            
        Returns:
            List[Dict[str, str]]: List of top matching files with metadata
        """
        query_tokens = self._tokenize(search_term)
        if not query_tokens:
            return []

        # Get candidate files from inverted index
        candidate_files = set()
        for token in query_tokens:
            # Look for exact matches
            candidate_files.update(self.inverted_index.get(token, set()))

            # Look for trigram matches
            query_trigrams = self._get_trigrams(token)
            for trigram in query_trigrams:
                candidate_files.update(self.inverted_index.get(trigram, set()))

        # Filter by file type if specified
        if file_type:
            file_type = file_type.lower()
            if not file_type.startswith('.'):
                file_type = f'.{file_type}'
            candidate_files = {f for f in candidate_files if f.lower().endswith(file_type)}

        # Score candidates
        scored_results = []
        for file_path in candidate_files:
            score = self._calculate_relevance(query_tokens, file_path)
            if score > 0:
                result = self.file_index[file_path].copy()
                result['score'] = score  # Include the score for sorting
                scored_results.append(result)

        # Sort by relevance score (descending)
        scored_results.sort(key=lambda x: x['score'], reverse=True)

        # Return only the top max_results
        top_results = scored_results[:max_results]

        # Remove the score from the results if not needed in the output
        for result in top_results:
            result.pop('score', None)

        return top_results
    

def search_files_with_agent(search_term: str, file_type: Optional[str] = None) -> List[Dict[str, str]]:
    file_agent = FileSearchAgent()

        # Perform the search
    print(f"\nSearching for files containing '{search_term}'{f' with type .{file_type}' if file_type else ''}...")
    results = file_agent.search_files(search_term, file_type)

        # Format results for display
    if results:
        print(f"\nFound {len(results)} matching files:")
        for idx, result in enumerate(results, 1):
            print(f"\n{idx}. File Details:")
            print(f"   Path: {result['path']}")
            print(f"   Size: {result['size']}")
            print(f"   Last Modified: {result['modified']}")
    else:
        print(f"\nNo files found matching the search criteria.")

    return results


class FileFinder:
    def __init__(self, context: ChatContext):
        self.context = context
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_psc = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_psc["response_format"] = ProblemStatusResponse
        self.llm_config_process_comp = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_process_comp["response_format"] = FileFinderResponse
        self.agents = self.get_agents()
        autogen.register_function(search_files_with_agent,
                                  caller=self.file_finder,
                                  executor=self.user_proxy,
                                  name="file_search_function",
                                  description="This tool will be used to search for any files in the system",
                                  )
        self.get_chat_manager()
        
        
    def _check_cancellation(self):
        """Check if the chat should be cancelled"""
        if self.context.cancellation_token and self.context.cancellation_token.is_cancelled():
            raise asyncio.CancelledError(f"Group chat cancelled for session {self.context.chat_id}")



    def file_finder_planner(self):
        return autogen.AssistantAgent(
            name="file_finder_planner",
            llm_config=self.llm_config,
            system_message=prompts.planner
        )
    def file_finder(self):
        return autogen.AssistantAgent(
            name="file_finder",
            llm_config=self.llm_config,
            system_message=prompts.file_finder
        )
    def user_proxy(self):
        return autogen.UserProxyAgent(
            name="user_proxy",
            llm_config=self.llm_config,
            human_input_mode="NEVER",
            is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("TERMINATE"),
            code_execution_config={
                "work_dir": "file_search_workspace",
                "use_docker": False
                }
            )
    def prob_status_checker(self):
        return AssistantAgent(
            name="prob_status_checker",
            description="""call this agent to check if the Task specified by the user has been completed""",
            system_message=prompts.prob_status_checker,
            llm_config=self.llm_config_psc
            )
    def process_completion(self):
        return AssistantAgent(
            name="process_completion",
            llm_config=self.llm_config_process_comp,
            description="Let group manager know that the process is completed. ",
            system_message=prompts.process_completion)
    

    
    # static custom speaker selection, no dynamic agent selection or condition chat routing
    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
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
                if 'yes' in messages[-1]["content"].lower():
                    return groupchat.agent_by_name("process_completion")
                else:
                    return groupchat.agent_by_name("file_finder_planner")
            return None
        
        except asyncio.CancelledError:
            logger.info(f"Speaker selection cancelled for session {self.context.chat_id}")
            # Return process_completion to gracefully end the chat
            raise



    def get_agents(self) -> List[Agent]:
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
            self.process_completion
        ]
    

    def get_chat_manager(self):
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
            human_input_mode="ALWAYS"
        )
        return self.groupchat , self.manager


