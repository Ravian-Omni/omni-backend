import os
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Annotated, List, Dict, Any, Optional

import requests
import nest_asyncio
from pydantic import BaseModel

# AutoGen imports
import autogen
from autogen import AssistantAgent, UserProxyAgent

# Browser-use imports
from browser_use import Agent, Browser, BrowserConfig, Controller, ActionResult
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.context import BrowserContextConfig

# Your custom imports
from configs.settings import settings
from langchain_openai import ChatOpenAI
from capabilities.browser_manager import prompts
from utilities.custom_manager import CustomGroupChatManager
from configs.llm_configs_manager import LLMConfigManager
from capabilities.browser_manager.response_format import webprocess_completion
from tavily import AsyncTavilyClient
from .country_data import country_codes
from utilities.storage import ensure_path



class BrowserManager:
    def __init__(
        self, 
        chat_id: str, 
        call_id: str, 
        capability_id: str, 
        omni_memory,
        headless: bool = False,
        window_size: Dict[str, int] = None,
        save_results: bool = True,
        browser_data_dir: Optional[str] = None
    ):
        """
        Initialize BrowserManager with simplified configuration.
        
        Args:
            headless: Whether to run browser in headless mode
            window_size: Window size configuration {'width': int, 'height': int}
            save_results: Whether to save search results to files
            browser_data_dir: Directory for browser data (optional)
        """
        self.headless = headless
        self.window_size = window_size or {'width': 1280, 'height': 720}
        self.save_results = save_results
        self.chat_id = chat_id
        self.call_id = call_id
        self.capability_id = capability_id
        self.omni_memory = omni_memory
        
        # Initialize Tavily client
        self.tavily_client = AsyncTavilyClient(settings.WEB_API)
        
        # Setup directories
        self.browser_data_dir = ensure_path(browser_data_dir) or str(Path.home() / "browser_use_data")
        
        if self.save_results:
            self.results_dir = os.path.join(settings.ROOT_DIR, "browser")
            browser_gif_dir = ensure_path(os.path.join(self.results_dir, "gif", self.chat_id))
            self.browser_gif = os.path.join(browser_gif_dir, f"{self.capability_id}.gif")
        
        # Initialize LLM configurations
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_wc = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_wc["response_format"] = webprocess_completion
        
        # Initialize vision LLM
        self.vision_llm = ChatOpenAI(
            model_name="gpt-4.1-mini-2025-04-14",
            temperature=0.1,
            api_key=settings.OPENAI_API_KEY,
        )
        
        # Browser session management
        self.browser_session = None
        self.controller = Controller()
        
        # Get user country
        self.user_country = self._get_user_country()
        
        # Initialize agents and register functions
        self.agents = self._initialize_agents()
        self._register_functions()
        self.groupchat, self.manager = self._initialize_chat_manager()

    def _get_user_country(self) -> str:
        """Get user's country from IP address."""
        try:
            response = requests.get("https://ipinfo.io/json", timeout=5)
            data = response.json()
            country_code = data.get("country")
            
            country = next(
                (c for c in country_codes if c["alpha_2"] == country_code or c["alpha_3"] == country_code),
                None
            )
            return country["name"] if country else f"Unknown ({country_code})"
        except Exception as e:
            print(f"Failed to get country: {e}")
            return "Unknown"

    async def _initialize_browser_session(self) -> BrowserSession:
        """Initialize browser session with optimized configuration."""
        if self.browser_session is None:
            browser_profile = BrowserProfile(
                window_size=self.window_size,
                keep_alive=False,  # Don't keep alive by default
                user_data_dir=self.browser_data_dir,
                headless=self.headless,
            )
            
            self.browser_session = BrowserSession(browser_profile=browser_profile)
            await self.browser_session.start()
        
        return self.browser_session

    def _create_browser(self) -> Browser:
        """Create browser instance with simplified configuration."""
        return Browser(
            config=BrowserConfig(
                headless=self.headless,
                new_context_config=BrowserContextConfig(highlight_elements=False),
            )
        )

    async def get_search_tool(self, query: str) -> str:
        """API-based search tool using Tavily."""
        try:
            response = await self.tavily_client.search(query, search_depth="advanced")
            
            if response and 'results' in response:
                result_text = f"Query: {response.get('query', query)}\n"
                result_text += f"Found {len(response['results'])} results:\n\n"
                
                for i, result in enumerate(response['results'][:5], 1):
                    result_text += f"{i}. {result.get('title', 'No title')}\n"
                    result_text += f"   URL: {result.get('url', 'No URL')}\n"
                    result_text += f"   Content: {result.get('content', 'No content')[:200]}...\n\n"
                
                return result_text
            else:
                return "No results found"
                
        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            print(error_msg)
            return error_msg

    async def get_browser_search_function(self, task_goal: str, starting_url: str = None) -> str:
        """Browser automation function with optional result saving."""
        try:
            # Initialize browser session
            browser_session = await self._initialize_browser_session()
            
            # Setup controller with credentials handler
            @self.controller.action("Ask user for credentials")
            def ask_human_local(question: str) -> ActionResult:
                answer = input(f'\n{question}\nInput: ')
                return ActionResult(extracted_content=answer, include_in_memory=True)
            
            # Create agent with minimal configuration
            agent = Agent(
                task=task_goal,
                browser=self._create_browser(),
                browser_session=browser_session,
                max_failures=3,  # Reduced from 5
                retry_delay=2,   # Reduced from 3
                use_vision=False,
                generate_gif=False if not self.save_results else self.browser_gif,  # Disabled to reduce file generation
                max_input_tokens=180000,  # Reduced from 180000
                validate_output=True,
                llm=self.vision_llm,
                # save_conversation_path=None if not self.save_results else self.results_dir,
                controller=self.controller
            )

            # Run the agent
            result = await agent.run()
            final_result = (
                result.final_result()
                if callable(result.final_result)
                else result.final_result
            )

            # Optionally save results
            if self.save_results:
                await self._save_result(task_goal, final_result, "success")

            return f"Task completed successfully: {final_result}"

        except Exception as e:
            error_msg = f"Browser automation failed: {str(e)}"
            
            if self.save_results:
                await self._save_result(task_goal, error_msg, "error")
            
            return error_msg

    async def _save_result(self, task: str, result: str, status: str):
        """Save results to file if enabled."""
        if not self.save_results:
            return
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.results_dir, f"search_result_{self.chat_id}_{timestamp}.json")
        
        result_data = {
            "task": task,
            "timestamp": timestamp,
            "status": status,
            "result": result,
            "metadata": {
                "headless": self.headless,
                "window_size": self.window_size,
                "user_country": self.user_country,
            }
        }

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(result_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save results: {e}")

    def _register_functions(self):
        """Register functions with simplified descriptions."""
        async def browser_search_function_wrapper(task_goal: str, starting_url: str = None):
            """Browser automation function."""
            return await self.get_browser_search_function(task_goal, starting_url)
        
        async def search_tool_wrapper(query: str):
            """API-based search tool using Tavily."""
            return await self.get_search_tool(query)
        # Register browser search function
        autogen.register_function(
            browser_search_function_wrapper,
            caller=self.browser_reader,
            executor=self.browser_searcher,
            name="web_search_tool_chrome",
            description="""
            Interactive web automation tool for complex browser tasks requiring visual parsing and multi-step interactions.
            Use for: login-required content, form submissions, e-commerce, social media automation, visual content analysis.
            Avoid for: simple factual queries or static content.
            """
        )

        # Register API search function
        autogen.register_function(
            search_tool_wrapper,
            caller=self.browser_reader,
            executor=self.browser_searcher,
            name="web_search_tool_api",
            description="""
            High-speed API-based search for rapid information retrieval.
            Use for: factual research, current events, market data, academic lookup.
            Avoid for: tasks requiring user accounts or interactive elements.
            """
        )

    def _initialize_agents(self) -> List:
        """Initialize all agents with simplified configuration."""
        self.planner = AssistantAgent(
            name="browser_planner",
            llm_config=self.llm_config,
            system_message=prompts.planner.format(
                today_date=datetime.now(),
                usercountry=self.user_country
            ),
        )

        self.browser_reader = AssistantAgent(
            name="browser_reader",
            llm_config=self.llm_config,
        )

        self.browser_searcher = autogen.UserProxyAgent(
            name="browser_searcher",
            llm_config=self.llm_config,
            code_execution_config=False,
            human_input_mode="NEVER",
        )

        self.process_completion = AssistantAgent(
            name="process_completion",
            llm_config=self.llm_config_wc,
            description="Process completion handler.",
            system_message=prompts.process_completion,
        )

        return [self.planner, self.browser_searcher, self.browser_reader, self.process_completion]

    def _speaker_selection(self, last_speaker, groupchat):
        """Simplified speaker selection logic."""
        messages = groupchat.messages
        if len(messages) == 1 or last_speaker.name == "chat_manager":
            return groupchat.agent_by_name("browser_planner")
        elif last_speaker.name == "browser_planner":
            return groupchat.agent_by_name("browser_reader")
        elif last_speaker.name == "browser_reader":
            return groupchat.agent_by_name("browser_searcher")
        elif last_speaker.name == "browser_searcher":
            return groupchat.agent_by_name("process_completion")
        return None

    def _initialize_chat_manager(self):
        """Initialize group chat and manager."""
        groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self._speaker_selection,
            max_round=200,  # Reduced from 500
        )
        
        manager = CustomGroupChatManager(
            groupchat=groupchat,
            llm_config=self.llm_config,
            capability_name=settings.BROWSER_COLLECTION,
            capability_id=self.capability_id,
            chat_id=self.chat_id,
            call_id=self.call_id,
            omni_memory=self.omni_memory,
            human_input_mode="ALWAYS"
        )

        return groupchat, manager

    async def close_browser_session(self):
        """Clean up browser session."""
        if self.browser_session:
            try:
                await self.browser_session.kill()
            except Exception as e:
                print(f"Error closing browser session: {e}")
            finally:
                self.browser_session = None

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with cleanup."""
        await self.close_browser_session()

# Usage example:
# async def main():
#     async with BrowserManager(
#         chat_id="test_chat",
#         call_id="test_call", 
#         capability_id="test_cap",
#         omni_memory=None,
#         headless=True,
#         save_results=False  # Disable file generation
#     ) as browser_manager:
#         result = await browser_manager.browser_search_function("Search for Python tutorials")
#         print(result)