import asyncio
import gc
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

import aiohttp

# AutoGen imports
import autogen
import requests
from autogen import AssistantAgent, UserProxyAgent

# Browser-use imports
from browser_use import ActionResult, Browser, BrowserConfig, Controller
from browser_use.browser.context import BrowserContextConfig
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from loguru import logger
from tavily import AsyncTavilyClient

from capabilities.browser_manager import prompts
from capabilities.browser_manager.function_description import (
    web_api_search,
    web_browser_automation,
)
from capabilities.browser_manager.response_format import WebProcessCompletion
from capabilities.browser_manager.streaming_browser import StreamingAgent
from configs.llm_configs_manager import LLMConfigManager

# Your custom imports
from configs.settings import settings
from configs.system_ai_config import GroupchatConfigurationManager
from dependencies import get_websocket_manager
from utilities.custom_manager import ChatContext, CustomGroupChatManager
from utilities.storage import ensure_path

from .country_data import country_codes


class BraveSearchClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.search.brave.com/res/v1"
        self.headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        }

    async def search(
        self,
        query: str,
        country: str = "US",
        search_lang: str = "en",
        ui_lang: str = "en-US",
        count: int = 2,
        offset: int = 0,
        safesearch: str = "moderate",
        freshness: str | None = None,
        text_decorations: bool = False,
        spellcheck: bool = True,
        result_filter: str | None = None,
        goggles_id: str | None = None,
        units: str = "metric",
        extra_snippets: bool = False,
    ) -> dict[str, Any]:
        """
        Perform a web search using Brave Search API

        Args:
            query: Search query string
            country: Country code for search results (default: "US")
            search_lang: Language for search (default: "en")
            ui_lang: UI language (default: "en-US")
            count: Number of results (1-20, default: 20)
            offset: Offset for pagination (default: 0)
            safesearch: Safe search level - "strict", "moderate", "off" (default: "moderate")
            freshness: Time filter - "pd" (past day), "pw" (past week), "pm" (past month), "py" (past year)
            text_decorations: Include text decorations in results
            spellcheck: Enable spell checking
            result_filter: Filter results - "discussions", "videos", "news", "infobox"
            goggles_id: Goggles ID for custom ranking
            units: Unit system - "metric" or "imperial"
            extra_snippets: Include extra snippets in results
        """

        params = {
            "q": query,
            # "country": country,
            "search_lang": search_lang,
            "ui_lang": ui_lang,
            "count": min(max(count, 1), 20),
            "offset": offset,
            "safesearch": safesearch,
            "text_decorations": (
                "true" if text_decorations else "false"
            ),  # Convert bool to string
            "spellcheck": "true" if spellcheck else "false",  # Convert bool to string
            "units": units,
            "extra_snippets": (
                "true" if extra_snippets else "false"
            ),  # Convert bool to string
        }

        # Add optional parameters if provided
        if freshness:
            params["freshness"] = freshness
        if result_filter:
            params["result_filter"] = result_filter
        if goggles_id:
            params["goggles_id"] = goggles_id

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.base_url}/web/search", headers=self.headers, params=params
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        raise Exception(
                            f"Brave API error {response.status}: {error_text}"
                        )
            except Exception as e:
                raise Exception(f"Request failed: {str(e)}")


class BrowserManager:
    def __init__(
        self,
        context: ChatContext,
        headless: bool = False,
        window_size: dict[str, int] = None,
        save_results: bool = True,
        browser_data_dir: str | None = None,
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
        self.window_size = window_size or {"width": 1280, "height": 720}
        self.save_results = save_results
        self.context = context
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.groupchat_config = (
            GroupchatConfigurationManager.get_instance().get_groupchat_configuration(
                "web_browser"
            )
        )
        # Setup directories
        self.browser_data_dir = (
            ensure_path(browser_data_dir) if browser_data_dir else None
        ) or str(Path.home() / "browser_data")

        if self.save_results:
            self.results_dir = ensure_path(
                os.path.join(self.context.chat_dir, "browser")
            )
            # browser_gif_dir = ensure_path(os.path.join(self.results_dir, "gif", self.context.chat_id))
            self.browser_gif = os.path.join(
                self.results_dir, f"{self.context.capability_id}.gif"
            )

        # Initialize LLM configurations
        tavily_llm_config = LLMConfigManager.get_config("tavily_llm_config")
        brave_llm_config = LLMConfigManager.get_config("brave_llm_config")
        # Initialize Tavily client
        tavily_client_key = tavily_llm_config.get("config_list", [])[0].get("api_key")
        brave_client_key = brave_llm_config.get("config_list", [])[0].get("api_key")
        self.tavily_client = AsyncTavilyClient(tavily_client_key)
        self.brave_client = BraveSearchClient(brave_client_key)
        self.browser_llm_config = LLMConfigManager.get_config("browser_llm_config")
        # Initialize vision LLM
        browser_llm = self.browser_llm_config.get("config_list", [])[0]
        if "api_type" in browser_llm.keys() and browser_llm.get("api_type") == "azure":
            self.vision_llm = AzureChatOpenAI(
                azure_deployment=browser_llm.get("model"),
                temperature=browser_llm.get("temperature", 0.1),
                api_key=browser_llm.get("api_key"),
                azure_endpoint=browser_llm.get("base_url"),
                api_version=browser_llm.get("api_version"),
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
        if (
            self.context.cancellation_token
            and self.context.cancellation_token.is_cancelled()
        ):
            raise asyncio.CancelledError(
                f"Group chat cancelled for session {self.context.chat_id}"
            )

    def _get_user_country(self) -> str:
        """Get user's country from IP address."""
        try:
            response = requests.get("https://ipinfo.io/json", timeout=5)
            data = response.json()
            country_code = data.get("country")

            country = next(
                (
                    c
                    for c in country_codes
                    if c["alpha_2"] == country_code or c["alpha_3"] == country_code
                ),
                None,
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
            response = await self.tavily_client.search(
                query, search_depth="advanced", include_favicon=True
            )
            if response and "results" in response:
                result = {
                    "status": "success" if response else "failed",
                    "query": query,
                    "results_count": len(response.get("results", [])),
                    "answer": response.get("answer", ""),
                    "urls": [result["url"] for result in response.get("results", [])],
                    "sources": [
                        {
                            "title": result.get("title", ""),
                            "url": result.get("url", ""),
                            "content": result.get("content", ""),
                            "score": result.get("score", 0),
                        }
                        for result in response.get("results", [])
                    ],
                    "images": response.get("images", []),
                    "search_depth": response.get("search_depth", "basic"),
                    "follow_up_questions": response.get("follow_up_questions", []),
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
                if any(
                    keyword in module_name.lower()
                    for keyword in ["browser_use", "browser", "agent", "event"]
                ):
                    modules_to_check.append(module_name)

            for module_name in modules_to_check:
                try:
                    module = sys.modules[module_name]
                    # Look for attributes that might be registries
                    for attr_name in dir(module):
                        if any(
                            keyword in attr_name.lower()
                            for keyword in [
                                "registry",
                                "instances",
                                "_agents",
                                "_eventbus",
                                "cache",
                            ]
                        ):
                            attr = getattr(module, attr_name, None)
                            if isinstance(attr, dict):
                                attr.clear()
                            elif hasattr(attr, "clear") and callable(attr.clear):
                                attr.clear()
                except Exception:
                    continue

        except Exception as e:
            print(f"Warning: Could not clear module registries: {e}")

    async def get_brave_search_tool(
        self,
        query: str,
        search_type: str = "comprehensive",
        count: int = 5,
        freshness: str | None = None,
        country: str = "US",
        safesearch: str = "moderate",
    ) -> dict[str, Any]:
        """
        Brave Search API tool with comprehensive result formatting

        Args:
            query: Search query
            search_type: "quick" (basic), "comprehensive" (detailed), "recent" (with freshness filter)
            count: Number of results (1-20)
            freshness: Time filter - "pd", "pw", "pm", "py"
            country: Country code
            safesearch: Safe search level
        """
        try:
            # Adjust parameters based on search type
            if search_type == "recent":
                freshness = (
                    freshness or "pw"
                )  # Default to past week for recent searches
            elif search_type == "comprehensive":
                count = min(count, 20)  # Max results for comprehensive

            response = await self.brave_client.search(
                query=query,
                count=count,
                freshness=freshness,
                country=country,
                safesearch=safesearch,
                extra_snippets=True,  # Get more detailed snippets
                text_decorations=False,  # Clean text
            )

            if response and "web" in response:
                web_results = response["web"]["results"]

                # Format results similar to Tavily structure
                formatted_result = {
                    "status": "success",
                    "query": {
                        "original": response.get("query", {}).get("original", query),
                        "altered": response.get("query", {}).get("altered"),
                        "show_strict_warning": response.get("query", {}).get(
                            "show_strict_warning", False
                        ),
                        "is_navigational": response.get("query", {}).get(
                            "is_navigational", False
                        ),
                        "is_news_breaking": response.get("query", {}).get(
                            "is_news_breaking", False
                        ),
                        "spellcheck_off": response.get("query", {}).get(
                            "spellcheck_off", False
                        ),
                        "country": response.get("query", {}).get("country", country),
                        "bad_results": response.get("query", {}).get(
                            "bad_results", False
                        ),
                        "should_fallback": response.get("query", {}).get(
                            "should_fallback", False
                        ),
                        "more_results_available": response.get("query", {}).get(
                            "more_results_available", False
                        ),
                        "postal_code": response.get("query", {}).get("postal_code", ""),
                        "city": response.get("query", {}).get("city", ""),
                        "state": response.get("query", {}).get("state", ""),
                    },
                    "results_count": len(web_results),
                    "answer": self._generate_answer_summary(web_results),
                    "urls": [result["url"] for result in web_results],
                    # WEB RESULTS with full metadata
                    "web": {
                        "type": response.get("web", {}).get("type", "search"),
                        "results": [
                            {
                                "title": result.get("title", ""),
                                "url": result.get("url", ""),
                                "description": result.get("description", ""),
                                "is_source_local": result.get("is_source_local", False),
                                "is_source_both": result.get("is_source_both", False),
                                "language": result.get("language", "en"),
                                "family_friendly": result.get("family_friendly", True),
                                "type": result.get("type", "search_result"),
                                "subtype": result.get("subtype", "generic"),
                                "is_live": result.get("is_live", False),
                                "age": result.get("age", ""),
                                "page_age": result.get("page_age", ""),
                                "page_fetched": result.get("page_fetched", ""),
                                "page_ranking": result.get("page_ranking", 0),
                                "profile": {
                                    "name": result.get("profile", {}).get("name", ""),
                                    "url": result.get("profile", {}).get("url", ""),
                                    "long_name": result.get("profile", {}).get(
                                        "long_name", ""
                                    ),
                                    "img": result.get("profile", {}).get("img", ""),
                                },
                                "meta_url": {
                                    "scheme": result.get("meta_url", {}).get(
                                        "scheme", ""
                                    ),
                                    "netloc": result.get("meta_url", {}).get(
                                        "netloc", ""
                                    ),
                                    "hostname": result.get("meta_url", {}).get(
                                        "hostname", ""
                                    ),
                                    "favicon": result.get("meta_url", {}).get(
                                        "favicon", ""
                                    ),
                                    "path": result.get("meta_url", {}).get("path", ""),
                                },
                                "thumbnail": (
                                    {
                                        "src": result.get("thumbnail", {}).get(
                                            "src", ""
                                        ),
                                        "original": result.get("thumbnail", {}).get(
                                            "original", ""
                                        ),
                                        "logo": result.get("thumbnail", {}).get(
                                            "logo", False
                                        ),
                                    }
                                    if result.get("thumbnail")
                                    else None
                                ),
                                "clustered_results": result.get(
                                    "clustered_results", []
                                ),
                                "extra_snippets": result.get("extra_snippets", []),
                            }
                            for result in web_results
                        ],
                        "family_friendly": response.get("web", {}).get(
                            "family_friendly", True
                        ),
                    },
                    # VIDEOS with thumbnails and metadata
                    "videos": (
                        {
                            "type": response.get("videos", {}).get("type", ""),
                            "results": [
                                {
                                    "title": video.get("title", ""),
                                    "url": video.get("url", ""),
                                    "description": video.get("description", ""),
                                    "duration": video.get("duration", ""),
                                    "views": video.get("views", ""),
                                    "age": video.get("age", ""),
                                    "thumbnail": (
                                        {
                                            "src": video.get("thumbnail", {}).get(
                                                "src", ""
                                            ),
                                            "original": video.get("thumbnail", {}).get(
                                                "original", ""
                                            ),
                                            "logo": video.get("thumbnail", {}).get(
                                                "logo", False
                                            ),
                                        }
                                        if video.get("thumbnail")
                                        else None
                                    ),
                                    "profile": {
                                        "name": video.get("profile", {}).get(
                                            "name", ""
                                        ),
                                        "url": video.get("profile", {}).get("url", ""),
                                        "long_name": video.get("profile", {}).get(
                                            "long_name", ""
                                        ),
                                        "img": video.get("profile", {}).get("img", ""),
                                    },
                                    "meta_url": video.get("meta_url", {}),
                                    "language": video.get("language", "en"),
                                    "family_friendly": video.get(
                                        "family_friendly", True
                                    ),
                                }
                                for video in response.get("videos", {}).get(
                                    "results", []
                                )
                            ],
                            "mutated_by_goggles": response.get("videos", {}).get(
                                "mutated_by_goggles", False
                            ),
                        }
                        if response.get("videos")
                        else None
                    ),
                    # IMAGES with full metadata
                    "images": (
                        {
                            "type": response.get("images", {}).get("type", ""),
                            "results": [
                                {
                                    "title": img.get("title", ""),
                                    "url": img.get("url", ""),
                                    "thumbnail": (
                                        {
                                            "src": img.get("thumbnail", {}).get(
                                                "src", ""
                                            ),
                                            "original": img.get("thumbnail", {}).get(
                                                "original", ""
                                            ),
                                            "logo": img.get("thumbnail", {}).get(
                                                "logo", False
                                            ),
                                        }
                                        if img.get("thumbnail")
                                        else None
                                    ),
                                    "properties": (
                                        {
                                            "url": img.get("properties", {}).get(
                                                "url", ""
                                            ),
                                            "width": img.get("properties", {}).get(
                                                "width", 0
                                            ),
                                            "height": img.get("properties", {}).get(
                                                "height", 0
                                            ),
                                            "format": img.get("properties", {}).get(
                                                "format", ""
                                            ),
                                            "size": img.get("properties", {}).get(
                                                "size", 0
                                            ),
                                        }
                                        if img.get("properties")
                                        else None
                                    ),
                                    "profile": {
                                        "name": img.get("profile", {}).get("name", ""),
                                        "url": img.get("profile", {}).get("url", ""),
                                        "long_name": img.get("profile", {}).get(
                                            "long_name", ""
                                        ),
                                        "img": img.get("profile", {}).get("img", ""),
                                    },
                                    "meta_url": img.get("meta_url", {}),
                                    "age": img.get("age", ""),
                                    "language": img.get("language", "en"),
                                    "family_friendly": img.get("family_friendly", True),
                                }
                                for img in response.get("images", {}).get("results", [])
                            ],
                            "mutated_by_goggles": response.get("images", {}).get(
                                "mutated_by_goggles", False
                            ),
                        }
                        if response.get("images")
                        else None
                    ),
                    # NEWS with thumbnails
                    "news": (
                        {
                            "type": response.get("news", {}).get("type", ""),
                            "results": [
                                {
                                    "title": news.get("title", ""),
                                    "url": news.get("url", ""),
                                    "description": news.get("description", ""),
                                    "age": news.get("age", ""),
                                    "breaking": news.get("breaking", False),
                                    "thumbnail": (
                                        {
                                            "src": news.get("thumbnail", {}).get(
                                                "src", ""
                                            ),
                                            "original": news.get("thumbnail", {}).get(
                                                "original", ""
                                            ),
                                            "logo": news.get("thumbnail", {}).get(
                                                "logo", False
                                            ),
                                        }
                                        if news.get("thumbnail")
                                        else None
                                    ),
                                    "profile": {
                                        "name": news.get("profile", {}).get("name", ""),
                                        "url": news.get("profile", {}).get("url", ""),
                                        "long_name": news.get("profile", {}).get(
                                            "long_name", ""
                                        ),
                                        "img": news.get("profile", {}).get("img", ""),
                                    },
                                    "meta_url": news.get("meta_url", {}),
                                    "language": news.get("language", "en"),
                                    "family_friendly": news.get(
                                        "family_friendly", True
                                    ),
                                }
                                for news in response.get("news", {}).get("results", [])
                            ],
                            "mutated_by_goggles": response.get("news", {}).get(
                                "mutated_by_goggles", False
                            ),
                        }
                        if response.get("news")
                        else None
                    ),
                    # DISCUSSIONS (forums, reddit, etc.)
                    "discussions": (
                        {
                            "type": response.get("discussions", {}).get("type", ""),
                            "results": [
                                {
                                    "title": disc.get("title", ""),
                                    "url": disc.get("url", ""),
                                    "description": disc.get("description", ""),
                                    "age": disc.get("age", ""),
                                    "number_of_answers": disc.get(
                                        "number_of_answers", 0
                                    ),
                                    "forum": disc.get("forum", ""),
                                    "profile": disc.get("profile", {}),
                                    "meta_url": disc.get("meta_url", {}),
                                    "language": disc.get("language", "en"),
                                    "family_friendly": disc.get(
                                        "family_friendly", True
                                    ),
                                }
                                for disc in response.get("discussions", {}).get(
                                    "results", []
                                )
                            ],
                            "mutated_by_goggles": response.get("discussions", {}).get(
                                "mutated_by_goggles", False
                            ),
                        }
                        if response.get("discussions")
                        else None
                    ),
                    # LOCATIONS (maps, local business)
                    "locations": (
                        {
                            "type": response.get("locations", {}).get("type", ""),
                            "results": [
                                {
                                    "title": loc.get("title", ""),
                                    "url": loc.get("url", ""),
                                    "description": loc.get("description", ""),
                                    "coordinates": loc.get("coordinates", []),
                                    "postal_address": loc.get("postal_address", {}),
                                    "contact": loc.get("contact", {}),
                                    "rating": loc.get("rating", 0),
                                    "reviews": loc.get("reviews", 0),
                                    "price_range": loc.get("price_range", ""),
                                    "thumbnail": loc.get("thumbnail", {}),
                                    "profile": loc.get("profile", {}),
                                    "meta_url": loc.get("meta_url", {}),
                                }
                                for loc in response.get("locations", {}).get(
                                    "results", []
                                )
                            ],
                        }
                        if response.get("locations")
                        else None
                    ),
                    # FAQ
                    "faq": (
                        {
                            "type": response.get("faq", {}).get("type", ""),
                            "results": [
                                {
                                    "question": faq.get("question", ""),
                                    "answer": faq.get("answer", ""),
                                    "title": faq.get("title", ""),
                                    "url": faq.get("url", ""),
                                    "meta_url": faq.get("meta_url", {}),
                                }
                                for faq in response.get("faq", {}).get("results", [])
                            ],
                        }
                        if response.get("faq")
                        else None
                    ),
                    # INFOBOX with thumbnails
                    "infobox": (
                        {
                            "type": response.get("infobox", {}).get("type", ""),
                            "title": response.get("infobox", {}).get("title", ""),
                            "description": response.get("infobox", {}).get(
                                "description", ""
                            ),
                            "long_desc": response.get("infobox", {}).get(
                                "long_desc", []
                            ),
                            "url": response.get("infobox", {}).get("url", ""),
                            "thumbnail": (
                                {
                                    "src": response.get("infobox", {})
                                    .get("thumbnail", {})
                                    .get("src", ""),
                                    "original": response.get("infobox", {})
                                    .get("thumbnail", {})
                                    .get("original", ""),
                                    "logo": response.get("infobox", {})
                                    .get("thumbnail", {})
                                    .get("logo", False),
                                }
                                if response.get("infobox", {}).get("thumbnail")
                                else None
                            ),
                            "provider": {
                                "name": response.get("infobox", {})
                                .get("provider", {})
                                .get("name", ""),
                                "url": response.get("infobox", {})
                                .get("provider", {})
                                .get("url", ""),
                                "long_name": response.get("infobox", {})
                                .get("provider", {})
                                .get("long_name", ""),
                                "img": response.get("infobox", {})
                                .get("provider", {})
                                .get("img", ""),
                            },
                            "meta_url": response.get("infobox", {}).get("meta_url", {}),
                            "attributes": response.get("infobox", {}).get(
                                "attributes", []
                            ),
                        }
                        if response.get("infobox")
                        else None
                    ),
                    # MIXED LAYOUT
                    "mixed": {
                        "type": response.get("mixed", {}).get("type", "mixed"),
                        "main": response.get("mixed", {}).get("main", []),
                        "top": response.get("mixed", {}).get("top", []),
                        "side": response.get("mixed", {}).get("side", []),
                    },
                }
                return formatted_result

            else:
                return {
                    "status": "failed",
                    "query": query,
                    "results_count": 0,
                    "error": "No web results found in response",
                }

        except Exception as e:
            return {
                "status": "error",
                "query": query,
                "results_count": 0,
                "error": str(e),
            }

    def _generate_answer_summary(self, results: list[dict]) -> str:
        """Generate a brief answer summary from top results"""
        if not results:
            return ""

        # Combine descriptions from top 3 results
        descriptions = []
        for result in results[:3]:
            desc = result.get("description", "").strip()
            if desc and desc not in descriptions:
                descriptions.append(desc)

        return " ".join(descriptions)[:500] + "..." if descriptions else ""

    async def get_browser_search_function(
        self, task_goal: str, starting_url: str = None
    ) -> str:
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
                retry_delay=2,  # Reduced from 3
                use_vision=True,
                generate_gif=(
                    False if not self.save_results else self.browser_gif
                ),  # Disabled to reduce file generation
                max_input_tokens=180000,  # Reduced from 180000
                validate_output=True,
                llm=self.vision_llm,
                controller=self.controller,
                session_id=self.context.chat_id,
                ws_manager=ws_manager,
                # save_conversation_path=None if not self.save_results else self.results_dir,
            )

            # Run the agent
            # result = await agent.run()
            task = asyncio.create_task(agent.run())
            ws_manager.active_browser[self.context.chat_id] = (task, browser_session)
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
                "gif_path": self.browser_gif,
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
        filename = os.path.join(
            self.results_dir, f"search_result_{self.context.chat_id}_{timestamp}.json"
        )

        result_data = {
            "task": task,
            "timestamp": timestamp,
            "status": status,
            "result": result,
            "metadata": {
                "headless": self.headless,
                "window_size": self.window_size,
                "user_country": self.user_country,
            },
        }

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(result_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save results: {e}")

    def _register_functions(self):
        """Register functions with simplified descriptions."""

        async def browser_search_function_wrapper(
            task_goal: str, starting_url: str = None
        ):
            """Browser automation function."""
            return await self.get_browser_search_function(task_goal, starting_url)

        # async def search_tool_wrapper(query: str):
        #     """API-based search tool using Tavily."""
        #     return await self.get_search_tool(query)

        async def search_tool_wrapper(
            query: Annotated[
                str,
                "The search query string - be specific and descriptive for better results. Include relevant keywords, context, and relationships to the topic being searched",
            ],
            search_type: Annotated[
                str,
                "Search mode: 'comprehensive' (detailed results with extra snippets), 'quick' (fast basic results), 'recent' (time-filtered results)",
            ] = "comprehensive",
        ):
            """
            Brave Search API tool with comprehensive result formatting

            Args:
                query: Search query
                search_type: "quick" (basic), "comprehensive" (detailed), "recent" (with freshness filter)
                count: Number of results (1-20)
                freshness: Time filter - "pd", "pw", "pm", "py"
                country: Country code
                safesearch: Safe search level
            """
            return await self.get_brave_search_tool(
                query=query, search_type=search_type
            )

        # Register browser search function
        autogen.register_function(
            browser_search_function_wrapper,
            caller=self.browser_reader,
            executor=self.browser_searcher,
            name="web_browser_automation",
            description=web_browser_automation,
        )

        # Register API search function
        autogen.register_function(
            search_tool_wrapper,
            caller=self.browser_reader,
            executor=self.browser_searcher,
            name="web_api_search",
            description=web_api_search,
        )

    def get_browser_planner(self):
        llm_config_name = (
            self.groupchat_config.get_agent_config("browser_planner").llm_config
            or "default"
        )
        llm_browser_planner = LLMConfigManager.get_config(llm_config_name)
        return AssistantAgent(
            name="browser_planner",
            llm_config=llm_browser_planner,
            system_message=prompts.planner.format(
                today_date=date.today().isoformat(), usercountry=self.user_country
            ),
        )

    def get_browser_reader(self):
        llm_config_name = (
            self.groupchat_config.get_agent_config("browser_reader").llm_config
            or "default"
        )
        llm_browser_reader = LLMConfigManager.get_config(llm_config_name)
        llm_browser_reader["config_list"][0]["tool_choice"] = {"type": "any"}
        return AssistantAgent(
            name="browser_reader",
            llm_config=llm_browser_reader,
        )

    def get_browser_searcher(self):
        # llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        return UserProxyAgent(
            name="browser_searcher",
            # llm_config=llm_config,
            code_execution_config=False,
            human_input_mode="NEVER",
        )

    def get_process_completion(self):
        llm_config_name = (
            self.groupchat_config.get_agent_config("process_completion").llm_config
            or "default"
        )
        llm_process_completion = LLMConfigManager.get_config(llm_config_name)
        llm_process_completion["response_format"] = WebProcessCompletion
        return AssistantAgent(
            name="process_completion",
            llm_config=llm_process_completion,
            description="Process completion handler.",
            system_message=prompts.process_completion,
        )

    def _initialize_agents(self) -> list:
        """Initialize all agents with simplified configuration."""
        self.planner = self.get_browser_planner()

        self.browser_reader = self.get_browser_reader()

        self.browser_searcher = self.get_browser_searcher()

        self.process_completion = self.get_process_completion()

        return [
            self.planner,
            self.browser_searcher,
            self.browser_reader,
            self.process_completion,
        ]

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
            logger.info(
                f"Speaker selection cancelled for session {self.context.chat_id}"
            )
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
            human_input_mode="ALWAYS",
        )

        return groupchat, manager

    async def _cleanup_event_bus(self):
        """Clean up EventBus instances to prevent conflicts."""
        try:
            # Check if the browser session has an event bus or agent
            if hasattr(self.browser_session, "agent"):
                agent = self.browser_session.agent
                if hasattr(agent, "event_bus"):
                    # Try to stop or clean up the event bus
                    if hasattr(agent.event_bus, "stop"):
                        await agent.event_bus.stop()
                    elif hasattr(agent.event_bus, "close"):
                        await agent.event_bus.close()
                    elif hasattr(agent.event_bus, "cleanup"):
                        await agent.event_bus.cleanup()

            # Also check for global EventBus registry cleanup
            if hasattr(self.browser_session, "_cleanup_event_system"):
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
            if hasattr(self.browser_session, "close"):
                await self.browser_session.close()

            # Then try kill method
            if hasattr(self.browser_session, "kill"):
                await self.browser_session.kill()

            # Try to close the browser if it has a browser attribute
            if (
                hasattr(self.browser_session, "browser")
                and self.browser_session.browser
            ):
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
