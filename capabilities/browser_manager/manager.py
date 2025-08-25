import os
import asyncio
import json
from pathlib import Path
from datetime import datetime, date
from typing import Annotated, List, Dict, Any, Optional
from loguru import logger
import requests
import nest_asyncio
from pydantic import BaseModel
import gc
import sys
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
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from capabilities.browser_manager import prompts
from utilities.custom_manager import CustomGroupChatManager, ChatContext
from configs.llm_configs_manager import LLMConfigManager
from capabilities.browser_manager.response_format import WebProcessCompletion
from tavily import AsyncTavilyClient
from .country_data import country_codes
from utilities.storage import ensure_path
from capabilities.browser_manager.function_description import (
    web_browser_automation,
    web_api_search
)
from dependencies import get_websocket_manager
from capabilities.browser_manager.streaming_browser import StreamingAgent
from configs.system_ai_config import GroupchatConfigurationManager


class BrowserManager:
    def __init__(
        self, 
        context: ChatContext,
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
        self.context = context
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.groupchat_config = GroupchatConfigurationManager.get_instance().get_groupchat_configuration("web_browser")
        # Setup directories
        self.browser_data_dir = (ensure_path(browser_data_dir) if browser_data_dir else None) or str(Path.home() / "browser_data")
        
        if self.save_results:
            self.results_dir = ensure_path(os.path.join(self.context.chat_dir, "browser"))
            # browser_gif_dir = ensure_path(os.path.join(self.results_dir, "gif", self.context.chat_id))
            self.browser_gif = os.path.join(self.results_dir, f"{self.context.capability_id}.gif")
        
        # Initialize LLM configurations
        tavily_llm_config = LLMConfigManager.get_config("tavily_llm_config")
        # Initialize Tavily client
        tavily_client_key = tavily_llm_config.get("config_list", [])[0].get("api_key")
        self.tavily_client = AsyncTavilyClient(tavily_client_key)
        self.browser_llm_config = LLMConfigManager.get_config("browser_llm_config")
        # Initialize vision LLM
        browser_llm = self.browser_llm_config.get("config_list", [])[0]
        if "api_type" in browser_llm.keys() and browser_llm.get("api_type") == "azure":
            self.vision_llm = AzureChatOpenAI(
                azure_deployment=browser_llm.get("model"),
                temperature=browser_llm.get("temperature", 0.1),
                api_key=browser_llm.get("api_key"),
                azure_endpoint=browser_llm.get("base_url"),
                api_version=browser_llm.get("api_version")
            )

        else:
            self.vision_llm = ChatOpenAI(
                model_name=browser_llm.get("model"),
                temperature=browser_llm.get("temperature", 0.1),
                api_key=browser_llm.get("api_key"),
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

    def _check_cancellation(self):
        """Check if the chat should be cancelled"""
        if self.context.cancellation_token and self.context.cancellation_token.is_cancelled():
            raise asyncio.CancelledError(f"Group chat cancelled for session {self.context.chat_id}")
        
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
                executable_path=settings.CHROME_EXECUTABLE_PATH,
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
            response = await self.tavily_client.search(query, search_depth="advanced", include_favicon=True)
            if response and 'results' in response:
                result = {
                    "status": "success" if response else "failed",
                    "query": query,
                    "results_count": len(response.get('results', [])),
                    "answer": response.get('answer', ''),
                    "urls": [result['url'] for result in response.get('results', [])],
                    "sources": [
                        {
                            "title": result.get('title', ''),
                            "url": result.get('url', ''),
                            "content": result.get('content', ''),
                            "score": result.get('score', 0)
                        } 
                        for result in response.get('results', [])
                    ],
                    "images": response.get('images', []),
                    "search_depth": response.get('search_depth', 'basic'),
                    "follow_up_questions": response.get('follow_up_questions', [])
                }
                # result_text = f"Query: {response.get('query', query)}\n"
                # result_text += f"Found {len(response['results'])} results:\n\n"
                
                # for i, result in enumerate(response['results'][:5], 1):
                #     result_text += f"{i}. {result.get('title', 'No title')}\n"
                #     result_text += f"   URL: {result.get('url', 'No URL')}\n"
                #     result_text += f"   Content: {result.get('content', 'No content')[:200]}...\n\n"
                # return result_text
                return result
                
            else:
                return "No results found"
                
        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            print(error_msg)
            return error_msg
    
    def _clear_module_registries(self):
        """Clear any global registries in browser automation modules."""
        try:
            # Force garbage collection first
            gc.collect()
            
            # Look for browser automation modules and clear their state
            modules_to_check = []
            for module_name in sys.modules.keys():
                if any(keyword in module_name.lower() for keyword in [
                    'browser_use', 'browser', 'agent', 'event'
                ]):
                    modules_to_check.append(module_name)
            
            for module_name in modules_to_check:
                try:
                    module = sys.modules[module_name]
                    # Look for attributes that might be registries
                    for attr_name in dir(module):
                        if any(keyword in attr_name.lower() for keyword in [
                            'registry', 'instances', '_agents', '_eventbus', 'cache'
                        ]):
                            attr = getattr(module, attr_name, None)
                            if isinstance(attr, dict):
                                attr.clear()
                            elif hasattr(attr, 'clear') and callable(attr.clear):
                                attr.clear()
                except Exception:
                    continue
                    
        except Exception as e:
            print(f"Warning: Could not clear module registries: {e}")

    async def get_browser_search_function(self, task_goal: str, starting_url: str = None) -> str:
        """Browser automation function with optional result saving."""
        try:
            # self._clear_module_registries()
            ws_manager = await get_websocket_manager()
            # Initialize browser session
            browser_session = await self._initialize_browser_session()
            
            # Setup controller with credentials handler
            @self.controller.action("Ask user for credentials")
            async def ask_human_local(question: str) -> ActionResult:
                # answer = input(f'\n{question}\nInput: ')
                answer = await self.context.manager_kwargs["input_function"](question)
                return ActionResult(extracted_content=answer, include_in_memory=True)
            
            # Create agent with minimal configuration
            agent = StreamingAgent(
                task=task_goal,
                browser=self._create_browser(),
                browser_session=browser_session,
                max_failures=3,  # Reduced from 5
                retry_delay=2,   # Reduced from 3
                use_vision=True,
                generate_gif=False if not self.save_results else self.browser_gif,  # Disabled to reduce file generation
                max_input_tokens=180000,  # Reduced from 180000
                validate_output=True,
                llm=self.vision_llm,
                controller=self.controller,
                session_id = self.context.chat_id,
                ws_manager = ws_manager
                # save_conversation_path=None if not self.save_results else self.results_dir,
            )

            # Run the agent
            # result = await agent.run()
            task = asyncio.create_task(agent.run())
            ws_manager.active_browser[self.context.chat_id] = (task,browser_session)
            result = await task
            final_result = (
                result.final_result()
                if callable(result.final_result)
                else result.final_result
            )

            # Optionally save results
            if self.save_results:
                await self._save_result(task_goal, final_result, "success")
            response = {
                    "status": "success" if result.is_successful() else "failed",
                    "result": final_result,
                    "execution_time": result.total_duration_seconds(),
                    "urls_visited": result.urls(),
                    "errors": result.errors(),
                    "steps": len(result.extracted_content()),
                    "gif_path": self.browser_gif
                }
            return response

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
        filename = os.path.join(self.results_dir, f"search_result_{self.context.chat_id}_{timestamp}.json")
        
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
            name="web_browser_automation",
            description=web_browser_automation
        )

        # Register API search function
        autogen.register_function(
            search_tool_wrapper,
            caller=self.browser_reader,
            executor=self.browser_searcher,
            name="web_api_search",
            description=web_api_search
        )
    
    def get_browser_planner(self):
        llm_config_name = self.groupchat_config.get_agent_config("browser_planner").llm_config or "default"
        llm_browser_planner = LLMConfigManager.get_config(llm_config_name)
        return AssistantAgent(
            name="browser_planner",
            llm_config=llm_browser_planner,
            system_message=prompts.planner.format(
                today_date=date.today().isoformat(),
                usercountry=self.user_country
            ),
        )
    
    def get_browser_reader(self):
        llm_config_name = self.groupchat_config.get_agent_config("browser_reader").llm_config or "default"
        llm_browser_reader = LLMConfigManager.get_config(llm_config_name)
        llm_browser_reader['config_list'][0]["tool_choice"]={"type": "any"}
        return AssistantAgent(
            name="browser_reader",
            llm_config=llm_browser_reader,
        )
    
    def get_browser_searcher(self):
        # llm_config = LLMConfigManager.get_config("default")
        return UserProxyAgent(
            name="browser_searcher",
            # llm_config=llm_config,
            code_execution_config=False,
            human_input_mode="NEVER",
        )
    
    def get_process_completion(self):
        llm_config_name = self.groupchat_config.get_agent_config("process_completion").llm_config or "default"
        llm_process_completion = LLMConfigManager.get_config(llm_config_name)
        llm_process_completion["response_format"] = WebProcessCompletion
        return AssistantAgent(
            name="process_completion",
            llm_config=llm_process_completion,
            description="Process completion handler.",
            system_message=prompts.process_completion,
        )

    def _initialize_agents(self) -> List:
        """Initialize all agents with simplified configuration."""
        self.planner = self.get_browser_planner()

        self.browser_reader = self.get_browser_reader()

        self.browser_searcher = self.get_browser_searcher()

        self.process_completion = self.get_process_completion()

        return [self.planner, self.browser_searcher, self.browser_reader, self.process_completion]

    def _speaker_selection(self, last_speaker, groupchat):
        """Simplified speaker selection logic."""
        try:
            self._check_cancellation()
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
        
        except asyncio.CancelledError:
            logger.info(f"Speaker selection cancelled for session {self.context.chat_id}")
            # Return process_completion to gracefully end the chat
            raise

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
            chat_context=self.context,
            llm_config=self.llm_config,
            human_input_mode="ALWAYS"
        )

        return groupchat, manager
    
    async def _cleanup_event_bus(self):
        """Clean up EventBus instances to prevent conflicts."""
        try:
            # Check if the browser session has an event bus or agent
            if hasattr(self.browser_session, 'agent'):
                agent = self.browser_session.agent
                if hasattr(agent, 'event_bus'):
                    # Try to stop or clean up the event bus
                    if hasattr(agent.event_bus, 'stop'):
                        await agent.event_bus.stop()
                    elif hasattr(agent.event_bus, 'close'):
                        await agent.event_bus.close()
                    elif hasattr(agent.event_bus, 'cleanup'):
                        await agent.event_bus.cleanup()
            
            # Also check for global EventBus registry cleanup
            if hasattr(self.browser_session, '_cleanup_event_system'):
                await self.browser_session._cleanup_event_system()
                
        except Exception as e:
            print(f"Warning: Could not clean up EventBus: {e}")
            
    async def close_browser_session(self) -> bool:
        """Attempt to close browser gracefully using the session's built-in methods."""
        if self.browser_session is None:
            return True
            
        try:
            await self._cleanup_event_bus()
            # Try the standard close method first
            if hasattr(self.browser_session, 'close'):
                await self.browser_session.close()
            
            # Then try kill method
            if hasattr(self.browser_session, 'kill'):
                await self.browser_session.kill()
            
            # Try to close the browser if it has a browser attribute
            if hasattr(self.browser_session, 'browser') and self.browser_session.browser:
                await self.browser_session.browser.close()
            
            self.browser_session = None
            return True
            
        except Exception as e:
            print(f"Error during graceful browser closure: {e}")
            return False


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