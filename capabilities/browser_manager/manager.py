import sys
import os
from pathlib import Path
os.environ["ANONYMIZED_TELEMETRY"] = "false"
# Add the project root directory to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)
from typing import Annotated
import httpx
import asyncio

from configs.settings import settings
from langchain_anthropic import ChatAnthropic
import nest_asyncio
import json
from datetime import datetime
from autogen import config_list_from_json
from typing import List, Dict, Any
import autogen
from autogen import (
    AssistantAgent,
    UserProxyAgent,
    GroupChat,
    GroupChatManager,
    register_function,
)
from langchain_openai import ChatOpenAI
from browser_use import Agent, Browser, BrowserConfig, Controller, ActionResult
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.context import BrowserContextConfig
from pydantic import BaseModel
from dotenv import load_dotenv
from capabilities.browser_manager import prompts
from utilities.custom_manager import CustomGroupChatManager
from utilities.external_memory import get_last_entry, get_all_messages
from configs.llm_configs_manager import LLMConfigManager
from capabilities.browser_manager.response_format import QuestionClassification, webprocess_completion
from tavily import TavilyClient

web_api= settings.WEB_API
print(f"Using Tavily API key: {web_api}")
tavily = TavilyClient(api_key=web_api)


load_dotenv()
nest_asyncio.apply()

# Default to ./results, but allow override via env var
results_dir = os.path.join(settings.ROOT_DIR, "browser", "results")
os.makedirs(results_dir, exist_ok=True)


class Post(BaseModel):
    caption: str
    post_url: str


class Posts(BaseModel):
    posts: List[Post]
    exhaustive_result: str 


# Global reference to browser manager instance
_browser_manager_instance = None
browser_data_dir = str(Path.home() / "browser_use_data")
os.makedirs(browser_data_dir, exist_ok=True)


async def search_tool(query: Annotated[str, "The search query"]) -> Annotated[str, "The search results"]:
    api_key = "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"
    url = "https://api.tavily.com/search"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={
                "query": query,
                "search_depth": "advanced",
                "api_key": api_key,
            }
        )
        response.raise_for_status()
        results = response.json()
        print(results)
        return results

async def browser_search_function(task: str) -> str:
    """Standalone function wrapper for browser search functionality."""
    global _browser_manager_instance
    if _browser_manager_instance is None:
        raise RuntimeError("BrowserManager instance not initialized")
    return await _browser_manager_instance._browser_search_impl(task)


class BrowserManager:
    def __init__(self, headless=False, use_chrome=True, window_size=None, keep_alive=False):
        """Initialize BrowserManager with configurable browser options.
        
        Args:
            headless (bool): Whether to run browser in headless mode
            use_chrome (bool): Whether to use Chrome browser
            window_size (dict): Window size configuration {'width': int, 'height': int}
            keep_alive (bool): Whether to keep browser session alive
        """
        global _browser_manager_instance
        _browser_manager_instance = self
        
        self.headless = headless
        self.use_chrome = use_chrome
        self.window_size = window_size or {'width': 4, 'height': 4} #setup the window size
        self.keep_alive = keep_alive
        self.results_dir = results_dir
        
        # Initialize LLM configurations
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_anth = LLMConfigManager.get_config("claude-3-7-sonnet-20250219")
        
        self.llm_config_qc = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_qc["response_format"] = QuestionClassification
        
        self.llm_config_wc = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_wc["response_format"] = webprocess_completion
        
        # Initialize vision LLM
        self.vision_llm = ChatAnthropic(
            model_name="claude-3-7-sonnet-20250219",  #claude-sonnet-4-20250514 , claude-3-7-sonnet-20250219
            temperature=0.1,
            api_key=settings.ANTHROPIC_API_KEY,
        )
        
        # Initialize browser session
        self.browser_session = None
        self.controller = Controller(output_model=Posts)
        
        # Initialize agents first
        self.agents = self.get_agents()
        
        # Register functions after agents are initialized
        self._register_functions()
        
        # Initialize group chat
        self.get_chat_manager()

    async def _initialize_browser_session(self):
        """Initialize browser session with new BrowserSession and BrowserProfile."""
        if self.browser_session is None:
            browser_profile = BrowserProfile(
                window_size=self.window_size,
                keep_alive=self.keep_alive,
                user_data_dir=browser_data_dir,
                headless=self.headless,
                chrome_instance_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" if self.use_chrome else None,
            )
            
            self.browser_session = BrowserSession(
                browser_profile=browser_profile
            )
            
            await self.browser_session.start()
        
        return self.browser_session

    def _initialize_browser(self):
        """Initialize browser with configurable options (legacy method for backward compatibility)."""
        if self.use_chrome:
            return Browser(
                config=BrowserConfig(
                    headless=self.headless,
                    chrome_instance_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    new_context_config=BrowserContextConfig(highlight_elements=False),
                )
            )
        else:
            # Default browser configuration without specific Chrome path
            return Browser(
                config=BrowserConfig(
                    headless=self.headless,
                    new_context_config=BrowserContextConfig(highlight_elements=False),
                )
            )

    def _register_functions(self):
        """Register functions after agents are initialized."""
        
        autogen.register_function(
            browser_search_function,  # Use the standalone function
            caller=self.browser_reader,
            executor=self.browser_searcher,
            name="web_search_tool_chrome",
            description="""
            Interactive web automation tool for complex browser-based tasks requiring visual parsing and multi-step interactions.
        
        Core Capabilities:
        - Screenshot-based page analysis and element identification
        - Sequential action execution (click, type, navigate, scroll)
        - Form filling and authentication workflows
        - Dynamic content extraction from JavaScript-heavy sites
        - Multi-page navigation and data collection
        
        Input Parameters:
        - task_goal: Detailed step-by-step instructions describing the complete workflow
          Example: "Navigate to LinkedIn, log in with provided credentials, go to notifications tab, and extract the 5 most recent connection requests with their profile information"
        - starting_url: Optional initial URL (defaults to Google search if omitted)
        
        Optimal Use Cases:
        ✓ Account-based operations (login required content)
        ✓ E-commerce interactions (shopping, checkout processes)
        ✓ Social media automation (posting, messaging, data extraction)
        ✓ Form submissions and multi-step workflows
        ✓ Visual content analysis (charts, images, layouts)
        ✓ Sites with heavy JavaScript or dynamic loading
        
        Avoid For:
        ✗ Simple factual queries answerable by search results
        ✗ Static content that doesn't require interaction
        ✗ Time-sensitive queries where speed is critical
            """)

        autogen.register_function(
            search_tool,  # Use the standalone function
            caller=self.browser_reader,
            executor=self.browser_searcher,
            name="web_search_tool_api",
            description="""
            High-speed API-based search tool for rapid information retrieval and knowledge synthesis.
        
        Core Capabilities:
        - Multi-source search aggregation (web, news, academic)
        - Real-time data retrieval and trending information
        - Structured data extraction (knowledge graphs, snippets)
        - Cross-reference validation from multiple sources
        - Intelligent query expansion and result filtering
        
        Input Parameters:
        - query: Focused search terms optimized for information retrieval
          Example: "Tesla Q4 2024 earnings report key metrics" or "Current mortgage rates USA December 2024"
        
        Optimal Use Cases:
        ✓ Factual research and data gathering
        ✓ Current events and breaking news monitoring
        ✓ Market data and financial information
        ✓ Academic and technical knowledge lookup
        ✓ Comparative analysis across multiple sources
        ✓ Trend identification and industry insights
        
        Avoid For:
        ✗ Tasks requiring user account access
        ✗ Interactive elements or form submissions
        ✗ Visual content analysis or screenshot needs
        ✗ Multi-step workflows or complex navigation
            """)

    async def _browser_search_impl(self, task: str) -> str:
        """Implementation of browser search functionality using new BrowserSession.

        Args:
            task: The task description (e.g., "Check school website for fee structure")

        Returns:
            The search results as a string

        Creates:
            A JSON file with all result details in ./results/ directory
        """
        print(f"filename path: {self.results_dir}")
        os.makedirs(self.results_dir, exist_ok=True)
        max_failures = 5
        retry_delay = 3
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.results_dir, f"search_result_{timestamp}.json")
        
        controller = Controller(output_model=Posts)
        
        @controller.action("""Ask user for credentials,
        - Ask user credentials login ID or password""")
        def ask_human_local(question: str) -> ActionResult:
            answer = input(f'\n{question}\nInput: ')
            return ActionResult(extracted_content=answer, include_in_memory=True)
            
        import browser_use.utils
        original_config_dir = browser_use.utils.BROWSER_USE_CONFIG_DIR
        browser_use.utils.BROWSER_USE_CONFIG_DIR = Path(self.results_dir)

        # Initialize browser session
        browser_session = await self._initialize_browser_session()

        agent = Agent(
            task=task,
            browser=self._initialize_browser(),  # Use the legacy method for backward compatibility
            browser_session=browser_session,  # Use browser_session instead of browser
            max_failures=max_failures,
            retry_delay=retry_delay,
            use_vision=True,
            generate_gif=True,
            max_input_tokens=180000,
            validate_output=True,
            llm=self.vision_llm,
            save_conversation_path=self.results_dir,
            controller=controller
        )

        try:
            result = await agent.run()

            final_result = (
                result.final_result()
                if callable(result.final_result)
                else result.final_result
            )

            result_data: Dict[str, Any] = {
                "task": task,
                "timestamp": timestamp,
                "status": "success",
                "result": final_result,
                "metadata": {
                    "max_failures": max_failures,
                    "retry_delay": retry_delay,
                    "llm": str(self.vision_llm.__class__.__name__),
                    "controller": str(controller.__class__.__name__),
                    "window_size": self.window_size,
                    "keep_alive": self.keep_alive,
                },
            }

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(result_data, f, indent=2, ensure_ascii=False)

            return f"Here is the final result --> {final_result}. We have saved the data in: {filename}"

        except Exception as e:
            error_data = {
                "task": task,
                "timestamp": timestamp,
                "status": "error",
                "error": str(e),
                "metadata": {
                    "max_failures": max_failures, 
                    "retry_delay": retry_delay,
                    "window_size": self.window_size,
                    "keep_alive": self.keep_alive,
                },
            }

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(error_data, f, indent=2)

            return f"Error: {str(e)}"

    async def close_browser_session(self):
        """Close the browser session if it exists."""
        if self.browser_session:
            await self.browser_session.kill()
            self.browser_session = None

    # Keep the original method for backward compatibility
    async def browser_search(self, task: str) -> str:
        """Original browser search method - kept for backward compatibility."""
        return await self._browser_search_impl(task)

    def browser_planner(self):
        return autogen.AssistantAgent(
            name="browser_planner",
            llm_config=self.llm_config,
            system_message=prompts.planner.format(
                get_last_entry=get_last_entry, get_all_messages=get_all_messages
            ),
        )

    def browser_searcher(self):
        """Create and return browser searcher agent."""
        return autogen.UserProxyAgent(
            name="browser_searcher",
            llm_config=self.llm_config,
            code_execution_config=False,
            human_input_mode="NEVER",
        )

    def browser_reader(self):
        """Create and return browser reader agent."""
        return autogen.AssistantAgent(
            name="browser_reader",
            llm_config=self.llm_config,
            #system_message=prompts.browser_reader,
        )

    def process_completion(self):
        """Create and return process completion agent."""
        return autogen.AssistantAgent(
            name="process_completion",
            llm_config=self.llm_config_wc,
            description="Let group manager know that the process is completed.",
            system_message=prompts.process_completion,
        )

    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        """Custom speaker selection function for group chat."""
        messages = groupchat.messages
        if len(messages) == 1:
            return groupchat.agent_by_name("browser_planner")
        if last_speaker.name == "browser_planner":
            return groupchat.agent_by_name("browser_reader")
        if last_speaker.name == "browser_reader":
            return groupchat.agent_by_name("browser_searcher")
        if last_speaker.name == "browser_searcher":
            return groupchat.agent_by_name("process_completion")
        return None

    def get_agents(self):
        """Initialize and return all agents."""
        self.planner= self.browser_planner()
        self.browser_reader = self.browser_reader()
        self.browser_searcher = self.browser_searcher()
        self.process_completion = self.process_completion()
        return [
                self.planner,
                self.browser_searcher,
                self.browser_reader,
                self.process_completion,
            ]

    def get_chat_manager(self):
        """Initialize and return the group chat manager."""
        self.groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self.custom_speaker_selection_func,
            max_round=500,
        )

        self.manager = CustomGroupChatManager(
            groupchat=self.groupchat,
            llm_config=self.llm_config,
            human_input_mode="ALWAYS",
            capability_name="email_sender"
        )
        return self.groupchat, self.manager