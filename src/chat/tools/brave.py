import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.routes import RoutesConfig


class BraveSearchClient:
    """Client for interacting with Brave Search API.

    Handles low-level HTTP communication with Brave Search API,
    including authentication, parameter formatting, and error handling.

    Attributes:
        api_key (str): Brave Search API subscription token
        base_url (str): Base URL for Brave Search API
        headers (Dict[str, str]): HTTP headers for API requests
    """

    def __init__(self):
        """Initialize Brave Search API client.

        Args:
            api_key: Brave Search API subscription token

        Raises:
            ValueError: If api_key is not provided
        """
        brave_llm_config = LLMConfigManager.get_config("brave_llm_config")
        # Initialize Tavily client
        self.api_key = brave_llm_config.get("config_list", [])[0].get("api_key")

        self.base_url = RoutesConfig.BRAVE_SEARCH_BASE_URL
        self.headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }

    async def search(
        self,
        query: str,
        country: str = "US",
        search_lang: str = "en",
        ui_lang: str = "en-US",
        count: int = 20,
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
        """Perform a web search using Brave Search API.

        Args:
            query: Search query string
            country: Country code for search results (default: "US")
            search_lang: Language for search (default: "en")
            ui_lang: UI language (default: "en-US")
            count: Number of results (1-20, default: 20)
            offset: Offset for pagination (default: 0)
            safesearch: Safe search level - "strict", "moderate", "off"
            freshness: Time filter - "pd", "pw", "pm", "py"
            text_decorations: Include text decorations in results
            spellcheck: Enable spell checking
            result_filter: Filter results - "discussions", "videos", "news", "infobox"
            goggles_id: Goggles ID for custom ranking
            units: Unit system - "metric" or "imperial"
            extra_snippets: Include extra snippets in results

        Returns:
            Dict containing raw API response

        Raises:
            Exception: If API request fails
        """
        params = {
            "q": query,
            "search_lang": search_lang,
            "ui_lang": ui_lang,
            "count": min(max(count, 1), 20),  # Clamp between 1-20
            "offset": offset,
            "safesearch": safesearch,
            "text_decorations": "true" if text_decorations else "false",
            "spellcheck": "true" if spellcheck else "false",
            "units": units,
            "extra_snippets": "true" if extra_snippets else "false",
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
                    f"{self.base_url}/web/search",
                    headers=self.headers,
                    params=params,
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        raise Exception(
                            f"Brave API error {response.status}: {error_text}"
                        )
            except aiohttp.ClientError as e:
                raise Exception(f"HTTP request failed: {str(e)}")
            except Exception as e:
                raise Exception(f"Request failed: {str(e)}")


@dataclass
class SearchQuery:
    """Search query metadata from Brave API."""

    original: str
    altered: str | None = None
    show_strict_warning: bool = False
    is_navigational: bool = False
    is_news_breaking: bool = False
    spellcheck_off: bool = False
    country: str = "US"
    bad_results: bool = False
    should_fallback: bool = False
    more_results_available: bool = False
    postal_code: str = ""
    city: str = ""
    state: str = ""


@dataclass
class SearchResult:
    """Standardized search result format."""

    status: str
    query: dict[str, Any]
    results_count: int
    answer: str
    urls: list[str]
    web: dict[str, Any]
    videos: dict[str, Any] | None = None
    images: dict[str, Any] | None = None
    news: dict[str, Any] | None = None
    discussions: dict[str, Any] | None = None
    locations: dict[str, Any] | None = None
    faq: dict[str, Any] | None = None
    infobox: dict[str, Any] | None = None
    mixed: dict[str, Any] = field(default_factory=dict)


class BraveSearchTool:
    """Production-ready Brave Search API tool for Autogen integration.

    Provides comprehensive search functionality with multiple result types:
    - Web results with metadata
    - Videos with thumbnails
    - Images with properties
    - News articles
    - Discussions (forums, Reddit)
    - Local locations
    - FAQ results
    - Infobox information

    Attributes:
        brave_client (BraveSearchClient): Brave Search API client
        logger: Logger instance for this class
    """

    # Search type configurations
    SEARCH_TYPES = {
        "quick": {"max_count": 5, "freshness": None},
        "comprehensive": {"max_count": 20, "freshness": None},
        "recent": {"max_count": 10, "freshness": "pw"},  # Past week
    }

    # Freshness filter options
    FRESHNESS_OPTIONS = {
        "pd": "Past day",
        "pw": "Past week",
        "pm": "Past month",
        "py": "Past year",
    }

    def __init__(self, brave_client: BraveSearchClient):
        """Initialize the Brave Search Tool.

        Args:
            brave_client: Initialized BraveSearchClient instance
        """
        self.brave_client = brave_client
        self.logger = logging.getLogger(__name__)
        self.logger.info("BraveSearchTool initialized")

    async def search(
        self,
        query: str,
        search_type: str = "comprehensive",
        count: int = 5,
        freshness: str | None = None,
        country: str = "US",
        safesearch: str = "moderate",
    ) -> dict[str, Any]:
        """Execute a search query using Brave Search API.

        This is the main entry point for performing searches. It handles
        parameter validation, API calls, and result formatting.

        Args:
            query: Search query string
            search_type: Type of search - "quick", "comprehensive", or "recent"
            count: Number of results to return (1-20)
            freshness: Time filter - "pd" (day), "pw" (week), "pm" (month), "py" (year)
            country: Country code for localized results (default: "US")
            safesearch: Safe search level - "off", "moderate", or "strict"

        Returns:
            Dict containing formatted search results or error information

        Example:
            >>> client = BraveSearchClient(api_key="your_key")
            >>> tool = BraveSearchTool(client)
            >>> results = await tool.search("Python programming", search_type="comprehensive")
            >>> print(f"Found {results['results_count']} results")
        """
        try:
            # Validate and adjust parameters
            search_params = self._prepare_search_parameters(
                search_type, count, freshness
            )

            # Execute search
            response = await self._execute_search(
                query=query,
                count=search_params["count"],
                freshness=search_params["freshness"],
                country=country,
                safesearch=safesearch,
            )

            # Format and return results
            if response and "web" in response:
                return self._format_search_results(response, query, country)
            else:
                return self._create_error_response(
                    query, "No web results found in response"
                )

        except Exception as e:
            self.logger.error(
                f"Search failed for query '{query}': {str(e)}", exc_info=True
            )
            return self._create_error_response(query, str(e), is_exception=True)

    def _prepare_search_parameters(
        self,
        search_type: str,
        count: int,
        freshness: str | None,
    ) -> dict[str, Any]:
        """Validate and prepare search parameters based on search type.

        Args:
            search_type: Type of search requested
            count: Requested number of results
            freshness: Requested freshness filter

        Returns:
            Dict with validated 'count' and 'freshness' parameters
        """
        if search_type not in self.SEARCH_TYPES:
            self.logger.warning(
                f"Invalid search_type '{search_type}', defaulting to 'comprehensive'"
            )
            search_type = "comprehensive"

        config = self.SEARCH_TYPES[search_type]

        # Apply search type defaults
        adjusted_count = min(count, config["max_count"])
        adjusted_freshness = freshness or config["freshness"]

        self.logger.debug(
            f"Search params - type: {search_type}, count: {adjusted_count}, "
            f"freshness: {adjusted_freshness}"
        )

        return {
            "count": adjusted_count,
            "freshness": adjusted_freshness,
        }

    async def _execute_search(
        self,
        query: str,
        count: int,
        freshness: str | None,
        country: str,
        safesearch: str,
    ) -> dict[str, Any] | None:
        """Execute the actual Brave Search API call.

        Args:
            query: Search query
            count: Number of results
            freshness: Time filter
            country: Country code
            safesearch: Safe search level

        Returns:
            Raw API response or None on failure
        """
        self.logger.info(f"Executing search: '{query}' (count={count})")

        response = await self.brave_client.search(
            query=query,
            count=count,
            freshness=freshness,
            country=country,
            safesearch=safesearch,
            extra_snippets=True,
            text_decorations=False,
        )

        return response

    def _format_search_results(
        self,
        response: dict[str, Any],
        query: str,
        country: str,
    ) -> dict[str, Any]:
        """Format raw Brave API response into standardized structure.

        Orchestrates the formatting of all result types:
        - Query metadata
        - Web results
        - Multimedia (videos, images)
        - News and discussions
        - Special results (infobox, FAQ, locations)

        Args:
            response: Raw API response
            query: Original search query
            country: Country code used

        Returns:
            Formatted search results dictionary
        """
        web_results = response.get("web", {}).get("results", [])

        formatted_result = {
            "status": "success",
            "query": self._format_query_metadata(response, query, country),
            "results_count": len(web_results),
            "answer": self._generate_answer_summary(web_results),
            "urls": [result.get("url", "") for result in web_results],
            "web": self._format_web_results(response.get("web", {})),
            "videos": self._format_videos(response.get("videos")),
            "images": self._format_images(response.get("images")),
            "news": self._format_news(response.get("news")),
            "discussions": self._format_discussions(response.get("discussions")),
            "locations": self._format_locations(response.get("locations")),
            "faq": self._format_faq(response.get("faq")),
            "infobox": self._format_infobox(response.get("infobox")),
            "mixed": self._format_mixed_layout(response.get("mixed", {})),
        }

        self.logger.info(f"Formatted {len(web_results)} results for query: '{query}'")
        return formatted_result

    def _format_query_metadata(
        self,
        response: dict[str, Any],
        query: str,
        country: str,
    ) -> dict[str, Any]:
        """Extract and format query metadata from response."""
        query_data = response.get("query", {})

        return {
            "original": query_data.get("original", query),
            "altered": query_data.get("altered"),
            "show_strict_warning": query_data.get("show_strict_warning", False),
            "is_navigational": query_data.get("is_navigational", False),
            "is_news_breaking": query_data.get("is_news_breaking", False),
            "spellcheck_off": query_data.get("spellcheck_off", False),
            "country": query_data.get("country", country),
            "bad_results": query_data.get("bad_results", False),
            "should_fallback": query_data.get("should_fallback", False),
            "more_results_available": query_data.get("more_results_available", False),
            "postal_code": query_data.get("postal_code", ""),
            "city": query_data.get("city", ""),
            "state": query_data.get("state", ""),
        }

    def _format_web_results(self, web_data: dict[str, Any]) -> dict[str, Any]:
        """Format web search results with full metadata."""
        results = web_data.get("results", [])

        return {
            "type": web_data.get("type", "search"),
            "family_friendly": web_data.get("family_friendly", True),
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
                    "age": result.get("age", ""),
                    "page_age": result.get("page_age", ""),
                    "page_ranking": result.get("page_ranking", 0),
                    "profile": self._format_profile(result.get("profile", {})),
                    "meta_url": self._format_meta_url(result.get("meta_url", {})),
                    "thumbnail": self._format_thumbnail(result.get("thumbnail")),
                    "extra_snippets": result.get("extra_snippets", []),
                    "clustered_results": result.get("clustered_results", []),
                }
                for result in results
            ],
        }

    def _format_videos(
        self, videos_data: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Format video search results."""
        if not videos_data:
            return None

        return {
            "type": videos_data.get("type", ""),
            "mutated_by_goggles": videos_data.get("mutated_by_goggles", False),
            "results": [
                {
                    "title": video.get("title", ""),
                    "url": video.get("url", ""),
                    "description": video.get("description", ""),
                    "duration": video.get("duration", ""),
                    "views": video.get("views", ""),
                    "age": video.get("age", ""),
                    "language": video.get("language", "en"),
                    "family_friendly": video.get("family_friendly", True),
                    "thumbnail": self._format_thumbnail(video.get("thumbnail")),
                    "profile": self._format_profile(video.get("profile", {})),
                    "meta_url": video.get("meta_url", {}),
                }
                for video in videos_data.get("results", [])
            ],
        }

    def _format_images(
        self, images_data: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Format image search results."""
        if not images_data:
            return None

        return {
            "type": images_data.get("type", ""),
            "mutated_by_goggles": images_data.get("mutated_by_goggles", False),
            "results": [
                {
                    "title": img.get("title", ""),
                    "url": img.get("url", ""),
                    "age": img.get("age", ""),
                    "language": img.get("language", "en"),
                    "family_friendly": img.get("family_friendly", True),
                    "thumbnail": self._format_thumbnail(img.get("thumbnail")),
                    "properties": self._format_image_properties(img.get("properties")),
                    "profile": self._format_profile(img.get("profile", {})),
                    "meta_url": img.get("meta_url", {}),
                }
                for img in images_data.get("results", [])
            ],
        }

    def _format_news(self, news_data: dict[str, Any] | None) -> dict[str, Any] | None:
        """Format news search results."""
        if not news_data:
            return None

        return {
            "type": news_data.get("type", ""),
            "mutated_by_goggles": news_data.get("mutated_by_goggles", False),
            "results": [
                {
                    "title": news.get("title", ""),
                    "url": news.get("url", ""),
                    "description": news.get("description", ""),
                    "age": news.get("age", ""),
                    "breaking": news.get("breaking", False),
                    "language": news.get("language", "en"),
                    "family_friendly": news.get("family_friendly", True),
                    "thumbnail": self._format_thumbnail(news.get("thumbnail")),
                    "profile": self._format_profile(news.get("profile", {})),
                    "meta_url": news.get("meta_url", {}),
                }
                for news in news_data.get("results", [])
            ],
        }

    def _format_discussions(
        self,
        discussions_data: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Format discussion/forum search results."""
        if not discussions_data:
            return None

        return {
            "type": discussions_data.get("type", ""),
            "mutated_by_goggles": discussions_data.get("mutated_by_goggles", False),
            "results": [
                {
                    "title": disc.get("title", ""),
                    "url": disc.get("url", ""),
                    "description": disc.get("description", ""),
                    "age": disc.get("age", ""),
                    "number_of_answers": disc.get("number_of_answers", 0),
                    "forum": disc.get("forum", ""),
                    "language": disc.get("language", "en"),
                    "family_friendly": disc.get("family_friendly", True),
                    "profile": disc.get("profile", {}),
                    "meta_url": disc.get("meta_url", {}),
                }
                for disc in discussions_data.get("results", [])
            ],
        }

    def _format_locations(
        self,
        locations_data: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Format local business/location search results."""
        if not locations_data:
            return None

        return {
            "type": locations_data.get("type", ""),
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
                for loc in locations_data.get("results", [])
            ],
        }

    def _format_faq(self, faq_data: dict[str, Any] | None) -> dict[str, Any] | None:
        """Format FAQ search results."""
        if not faq_data:
            return None

        return {
            "type": faq_data.get("type", ""),
            "results": [
                {
                    "question": faq.get("question", ""),
                    "answer": faq.get("answer", ""),
                    "title": faq.get("title", ""),
                    "url": faq.get("url", ""),
                    "meta_url": faq.get("meta_url", {}),
                }
                for faq in faq_data.get("results", [])
            ],
        }

    def _format_infobox(
        self,
        infobox_data: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Format infobox (knowledge panel) results."""
        if not infobox_data:
            return None

        return {
            "type": infobox_data.get("type", ""),
            "title": infobox_data.get("title", ""),
            "description": infobox_data.get("description", ""),
            "long_desc": infobox_data.get("long_desc", []),
            "url": infobox_data.get("url", ""),
            "thumbnail": self._format_thumbnail(infobox_data.get("thumbnail")),
            "provider": {
                "name": infobox_data.get("provider", {}).get("name", ""),
                "url": infobox_data.get("provider", {}).get("url", ""),
                "long_name": infobox_data.get("provider", {}).get("long_name", ""),
                "img": infobox_data.get("provider", {}).get("img", ""),
            },
            "meta_url": infobox_data.get("meta_url", {}),
            "attributes": infobox_data.get("attributes", []),
        }

    def _format_mixed_layout(self, mixed_data: dict[str, Any]) -> dict[str, Any]:
        """Format mixed layout configuration."""
        return {
            "type": mixed_data.get("type", "mixed"),
            "main": mixed_data.get("main", []),
            "top": mixed_data.get("top", []),
            "side": mixed_data.get("side", []),
        }

    def _format_thumbnail(
        self,
        thumbnail_data: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Format thumbnail data."""
        if not thumbnail_data:
            return None

        return {
            "src": thumbnail_data.get("src", ""),
            "original": thumbnail_data.get("original", ""),
            "logo": thumbnail_data.get("logo", False),
        }

    def _format_profile(self, profile_data: dict[str, Any]) -> dict[str, str]:
        """Format profile/source information."""
        return {
            "name": profile_data.get("name", ""),
            "url": profile_data.get("url", ""),
            "long_name": profile_data.get("long_name", ""),
            "img": profile_data.get("img", ""),
        }

    def _format_meta_url(self, meta_url_data: dict[str, Any]) -> dict[str, str]:
        """Format meta URL information."""
        return {
            "scheme": meta_url_data.get("scheme", ""),
            "netloc": meta_url_data.get("netloc", ""),
            "hostname": meta_url_data.get("hostname", ""),
            "favicon": meta_url_data.get("favicon", ""),
            "path": meta_url_data.get("path", ""),
        }

    def _format_image_properties(
        self,
        properties_data: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Format image properties (dimensions, format, size)."""
        if not properties_data:
            return None

        return {
            "url": properties_data.get("url", ""),
            "width": properties_data.get("width", 0),
            "height": properties_data.get("height", 0),
            "format": properties_data.get("format", ""),
            "size": properties_data.get("size", 0),
        }

    def _generate_answer_summary(self, web_results: list[dict[str, Any]]) -> str:
        """Generate a brief answer summary from top search results.

        Args:
            web_results: List of web search results

        Returns:
            Concatenated summary from top results' descriptions
        """
        if not web_results:
            return ""

        # Take top 3 results and combine their descriptions
        summaries = [
            result.get("description", "")
            for result in web_results[:3]
            if result.get("description")
        ]

        return " ".join(summaries)

    def _create_error_response(
        self,
        query: str,
        error_message: str,
        is_exception: bool = False,
    ) -> dict[str, Any]:
        """Create standardized error response.

        Args:
            query: Original search query
            error_message: Error description
            is_exception: Whether this was an exception or expected failure

        Returns:
            Error response dictionary
        """
        status = "error" if is_exception else "failed"

        return {
            "status": status,
            "query": query,
            "results_count": 0,
            "error": error_message,
        }


# Autogen Integration Wrapper
class BraveSearchAutogenTool:
    """Autogen-compatible wrapper for BraveSearchTool.

    Provides synchronous wrapper methods that Autogen agents can call.
    """

    def __init__(self, brave_search_tool: BraveSearchTool):
        """Initialize Autogen wrapper.

        Args:
            brave_search_tool: Instance of BraveSearchTool
        """
        self.search_tool = brave_search_tool
        self.logger = logging.getLogger(__name__)

    def search_web(
        self,
        query: str,
        search_type: str = "comprehensive",
        count: int = 5,
    ) -> dict[str, Any]:
        """Synchronous wrapper for search method (for Autogen compatibility).

        Args:
            query: Search query
            search_type: Type of search
            count: Number of results

        Returns:
            Search results dictionary
        """
        import asyncio

        try:
            # Run async search in sync context
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in async context, create new loop
                import nest_asyncio

                nest_asyncio.apply()

            result = loop.run_until_complete(
                self.search_tool.search(query, search_type, count)
            )
            return result

        except Exception as e:
            self.logger.error(f"Search wrapper failed: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "query": query,
                "results_count": 0,
                "error": str(e),
            }


# Usage Example
if __name__ == "__main__":
    pass

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    async def demo():
        """Demonstrate usage of BraveSearchTool with example searches."""
        # Initialize client and tool
        client = BraveSearchClient()
        search_tool = BraveSearchTool(client)

        # Perform search
        results = await search_tool.search(
            query="Python programming tutorials", search_type="comprehensive", count=10
        )

        print(f"Status: {results['status']}")
        print(f"Results: {results['results_count']}")
        print(f"URLs: {results['urls'][:3]}")

        # For Autogen integration
        BraveSearchAutogenTool(search_tool)
        # autogen_results = autogen_tool.search_web("AI news")

    # asyncio.run(demo())
