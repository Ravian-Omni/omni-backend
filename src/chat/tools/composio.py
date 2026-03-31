import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from inspect import Signature
from typing import Any

from autogen_core.tools import FunctionTool
from composio import Composio
from composio.client.types import Tool
from composio.core.provider.agentic import AgenticProviderExecuteFn
from composio.utils.shared import get_signature_format_from_schema_params
from composio_autogen import AutogenProvider

from src.configs.llm_configs_manager import LLMConfigManager  # type: ignore
from src.configs.routes import RoutesConfig
from src.utilities.api_client import api_client


class NuitkaSafeAutogenProvider(AutogenProvider, name="autogen"):
    """Nuitka-safe replacement for AutogenProvider.

    Avoids types.FunctionType + closure recreation,
    which crashes in Nuitka compiled binaries.
    """

    def wrap_tool(
        self,
        tool: Tool,
        execute_tool: AgenticProviderExecuteFn,
    ) -> FunctionTool:
        """wrap_tool creates a FunctionTool without using closures."""

        def execute_action(**kwargs: Any) -> dict:
            return execute_tool(slug=tool.slug, arguments=kwargs)

        # Generate safe function name
        func_name = self._process_function_name_for_registration(input_string=tool.slug)

        # Mutate function instead of recreating it
        execute_action.__name__ = func_name
        execute_action.__doc__ = tool.description

        params = get_signature_format_from_schema_params(
            schema_params=tool.input_parameters
        )

        execute_action.__signature__ = Signature(parameters=params)
        execute_action.__annotations__ = {p.name: p.annotation for p in params} | {
            "return": dict[str, Any]
        }

        return FunctionTool(
            func=execute_action,
            description=tool.description,
            name=func_name,
        )


class ToolObject:
    """Wrapper class for Composio tool definitions.

    Attributes:
        slug (str): Unique tool identifier (e.g., 'GMAIL_SEND_EMAIL')
        description (str): Human-readable description of the tool
        input_parameters (dict): JSON schema of tool parameters
        app_name (str): The app/toolkit this tool belongs to
    """

    def __init__(self, data: dict[str, Any], app_name: str | None = None):
        function_info = data.get("function", {})
        self.slug = function_info.get("name")
        self.description = function_info.get("description", "")
        self.input_parameters = function_info.get("parameters", {})
        # Extract app name from slug (e.g., 'GMAIL_SEND_EMAIL' -> 'GMAIL')
        self.app_name = app_name or (self.slug.split("_")[0] if self.slug else None)


class ComposioToolCache:
    """Persistent cache for Composio tools (lasts until server restart).

    Caches tools per user to avoid repeated API calls. Since this is a local
    backend, the cache persists for the lifetime of the server process.
    """

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        """Create singleton instance of ComposioToolCache."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = {}
            cls._instance._logger = logging.getLogger(__name__)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ComposioToolCache":
        """Get the singleton cache instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _cache_key(self, user_id: str) -> str:
        """Generate cache key for user."""
        return f"tools:{user_id}"

    def get(self, user_id: str) -> dict[str, Any] | None:
        """Get cached tools for user (no expiry - persists until server restart)."""
        key = self._cache_key(user_id)
        if key in self._cache:
            self._logger.info(f"Cache hit for user {user_id}")
            return self._cache[key]["data"]
        return None

    def set(self, user_id: str, data: dict[str, Any]) -> None:
        """Cache tools for user."""
        key = self._cache_key(user_id)
        self._cache[key] = {"data": data, "timestamp": time.time()}
        self._logger.info(f"Cached tools for user {user_id}")

    def add_app(self, user_id: str, app_name: str, app_tools: list[dict]) -> bool:
        """Add tools for a newly connected app to the cache.

        Args:
            user_id: User identifier
            app_name: App name (e.g., 'GMAIL')
            app_tools: List of raw tool definitions for the app

        Returns:
            True if app was added, False if cache doesn't exist for user
        """
        key = self._cache_key(user_id)
        if key not in self._cache:
            self._logger.warning(f"No cache exists for user {user_id}, cannot add app")
            return False

        cached_data = self._cache[key]["data"]
        existing_tools = cached_data.get("raw_tools", [])
        existing_toolkits = cached_data.get("toolkits", [])

        # Add app to toolkits if not already present
        app_upper = app_name.upper()
        if app_upper not in existing_toolkits:
            existing_toolkits.append(app_upper)

        # Add new tools
        existing_tools.extend(app_tools)

        # Update cache
        cached_data["raw_tools"] = existing_tools
        cached_data["toolkits"] = existing_toolkits
        self._cache[key]["timestamp"] = time.time()

        self._logger.info(
            f"Added {len(app_tools)} tools for app {app_name} to cache for user {user_id}"
        )
        return True

    def remove_app(self, user_id: str, app_name: str) -> list[str]:
        """Remove tools for a disconnected app from the cache.

        Args:
            user_id: User identifier
            app_name: App name to remove (e.g., 'GMAIL')

        Returns:
            List of tool slugs that were removed
        """
        key = self._cache_key(user_id)
        if key not in self._cache:
            self._logger.warning(
                f"No cache exists for user {user_id}, cannot remove app"
            )
            return []

        cached_data = self._cache[key]["data"]
        existing_tools = cached_data.get("raw_tools", [])
        existing_toolkits = cached_data.get("toolkits", [])

        app_upper = app_name.upper()
        removed_slugs = []

        # Remove app from toolkits
        if app_upper in existing_toolkits:
            existing_toolkits.remove(app_upper)

        # Remove tools belonging to this app
        filtered_tools = []
        for tool in existing_tools:
            func_info = tool.get("function", {})
            tool_name = func_info.get("name", "")
            # Tools are named like APP_ACTION (e.g., GMAIL_SEND_EMAIL)
            if tool_name.startswith(f"{app_upper}_"):
                removed_slugs.append(tool_name)
            else:
                filtered_tools.append(tool)

        cached_data["raw_tools"] = filtered_tools
        cached_data["toolkits"] = existing_toolkits
        self._cache[key]["timestamp"] = time.time()

        self._logger.info(
            f"Removed {len(removed_slugs)} tools for app {app_name} from cache for user {user_id}"
        )
        return removed_slugs

    def get_app_tools(self, user_id: str, app_name: str) -> list[dict]:
        """Get cached tools for a specific app.

        Args:
            user_id: User identifier
            app_name: App name (e.g., 'GMAIL')

        Returns:
            List of raw tool definitions for the app
        """
        key = self._cache_key(user_id)
        if key not in self._cache:
            return []

        cached_data = self._cache[key]["data"]
        existing_tools = cached_data.get("raw_tools", [])
        app_upper = app_name.upper()

        app_tools = []
        for tool in existing_tools:
            func_info = tool.get("function", {})
            tool_name = func_info.get("name", "")
            if tool_name.startswith(f"{app_upper}_"):
                app_tools.append(tool)

        return app_tools

    def has_app(self, user_id: str, app_name: str) -> bool:
        """Check if an app is in the cache for a user.

        Args:
            user_id: User identifier
            app_name: App name (e.g., 'GMAIL')

        Returns:
            True if app is cached
        """
        key = self._cache_key(user_id)
        if key not in self._cache:
            return False

        cached_data = self._cache[key]["data"]
        toolkits = cached_data.get("toolkits", [])
        return app_name.upper() in toolkits

    def invalidate(self, user_id: str) -> None:
        """Invalidate cache for user."""
        key = self._cache_key(user_id)
        if key in self._cache:
            del self._cache[key]
            self._logger.info(f"Invalidated cache for user {user_id}")

    def clear(self) -> None:
        """Clear entire cache."""
        self._cache.clear()
        self._logger.info("Cleared all tool cache")


class ComposioToolManager:
    """Manages Composio tool registration and execution for Autogen agents.

    This class handles the complete lifecycle of Composio tools:
    - Fetching tools from multiple toolkits (in parallel)
    - Creating tool wrappers compatible with Autogen
    - Registering tools with chat and executor agents
    - Executing tool actions with proper error handling
    - Caching tools to avoid repeated API calls
    - Live connection/disconnection of apps without reconnecting

    Attributes:
        user_id (str): Unique identifier for the user's Composio session
        chat_agent: Autogen chat agent that will use the tools
        agent_executor: Autogen executor agent that will run the tools
        composio (Composio): Composio API client instance
        toolset (AutogenProvider): Autogen-specific tool provider
        logger (logging.Logger): Logger instance for this class
    """

    # Shared thread pool for running sync Composio API calls
    _executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="composio_")

    def __init__(self, user_id: str, chat_agent, agent_executor):
        """Initialize the Composio Tool Manager.

        Args:
            user_id (str): Unique identifier for the user
            chat_agent: Autogen conversational agent
            agent_executor: Autogen agent that executes tools

        Raises:
            ValueError: If COMPOSIO_API_KEY is not set in environment
        """
        self.user_id = user_id
        self.chat_agent = chat_agent
        self.agent_executor = agent_executor

        # Setup logging
        self.logger = logging.getLogger(__name__)

        # Initialize Composio client
        composio_api_key = LLMConfigManager.get_config("composio_api_key")
        api_key = composio_api_key.get("config_list", [])[0].get("api_key")

        self.composio = Composio(api_key=api_key)
        self.toolset = NuitkaSafeAutogenProvider()
        self._cache = ComposioToolCache.get_instance()

        self.logger.info(f"Initialized ComposioToolManager for user: {user_id}")

    async def _run_in_executor(self, func, *args, **kwargs):
        """Run a synchronous function in the thread pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))

    async def has_active_connection(self, app_name: str) -> bool:
        """Check if the user has an ACTIVE Composio connection for the given app.

        Args:
            app_name: App name (e.g., 'GMAIL').

        Returns:
            True if an active connection exists.
        """
        try:
            connections = await self._run_in_executor(
                self.composio.connected_accounts.list, user_ids=[self.user_id]
            )
            app_lower = app_name.lower()
            for conn in connections.items:
                toolkit = conn.toolkit.slug.lower() if conn.toolkit else ""
                if toolkit == app_lower and conn.status == "ACTIVE":
                    return True
            return False
        except Exception as e:
            self.logger.error(f"Error checking connection for {app_name}: {e}")
            return False

    async def get_no_auth_apps(self) -> dict[str, Any]:
        """Get all no-auth apps from Composio (optional, degrades gracefully offline).

        Returns:
            Dictionary with no-auth apps information.
        """
        import asyncio

        self.logger.debug("Fetching no-auth apps")

        try:
            result = await asyncio.wait_for(
                api_client.get(RoutesConfig.API_CHAT_NO_AUTH_APPS),
                timeout=5.0,
            )
            result = result.standard_response()
            if not result.get("success"):
                raise Exception(f"Failed: {result.get('message', 'Unknown error')}")
            return result.get("data")
        except asyncio.TimeoutError:
            self.logger.warning("No-auth apps fetch timed out (offline?)")
            return {"apps": []}
        except Exception as e:
            self.logger.warning(f"No-auth apps unavailable (offline?): {e}")
            return {"apps": []}

    async def get_user_connected_apps_async(
        self, user_id: str, status_filter: str | None = None
    ) -> dict[str, Any]:
        """Get all connected apps for a user from Composio (async).

        Args:
            user_id: User identifier
            status_filter: Optional filter by status (ACTIVE, EXPIRED, etc.)

        Returns:
            Dictionary with user's connected apps information.
        """
        self.logger.debug(f"Fetching connected apps for user {user_id}")

        try:
            # Run sync Composio API call in thread pool
            connections = await self._run_in_executor(
                self.composio.connected_accounts.list, user_ids=[user_id]
            )

            apps = []
            app_names = []
            active_count = 0

            for conn in connections.items:
                try:
                    app_name = conn.toolkit.slug.upper() if conn.toolkit else "UNKNOWN"
                    display_name = (
                        conn.toolkit.slug.title() if conn.toolkit else "Unknown"
                    )
                    status = conn.status

                    if status_filter and status != status_filter.upper():
                        continue

                    is_active = status == "ACTIVE"
                    if is_active:
                        active_count += 1

                    app_info = {
                        "app_name": app_name,
                        "display_name": display_name,
                        "connection_id": conn.id,
                        "status": status,
                        "connected_at": (
                            conn.created_at if hasattr(conn, "created_at") else None
                        ),
                        "is_active": is_active,
                    }

                    apps.append(app_info)

                    if status == "ACTIVE":
                        app_names.append(app_name)

                except Exception as e:
                    self.logger.warning(f"Error parsing connection {conn.id}: {e}")
                    continue

            self.logger.info(
                f"Found {len(apps)} connected apps for user {user_id} ({active_count} active)"
            )

            # Fetch no-auth apps concurrently
            no_auth_apps = await self.get_no_auth_apps()
            app_names.extend(no_auth_apps.get("apps", []))

            return {
                "user_id": user_id,
                "total_apps": len(apps),
                "active_apps": active_count,
                "apps": apps,
                "app_names": app_names,
            }

        except Exception as e:
            self.logger.error(f"Failed to fetch connected apps: {e}")
            raise

    async def get_configured_toolkits_async(self) -> list[str]:
        """Retrieve the list of toolkits for the user (async).

        Returns:
            List[str]: List of toolkit names (e.g., ['GMAIL', 'GITHUB'])
        """
        toolkits_user = await self.get_user_connected_apps_async(self.user_id)
        toolkits = toolkits_user.get("app_names", [])

        self.logger.info(f"Configured toolkits: {toolkits}")
        return toolkits

    async def _fetch_toolkit_tools(self, toolkit: str) -> list[dict[str, Any]]:
        """Fetch tools for a single toolkit (runs in thread pool).

        Args:
            toolkit: Toolkit name to fetch tools from

        Returns:
            List of tool definitions for the toolkit
        """
        try:
            toolkit_tools = await self._run_in_executor(
                self.composio.tools.get, user_id=self.user_id, toolkits=[toolkit], limit=60
            )
            self.logger.info(f"Fetched {len(toolkit_tools)} tools from {toolkit}")
            return list(toolkit_tools)
        except Exception as e:
            self.logger.error(f"Failed to fetch tools from {toolkit}: {str(e)}")
            return []

    async def fetch_tools_from_toolkits_async(
        self, toolkits: list[str]
    ) -> list[dict[str, Any]]:
        """Fetch tools from multiple Composio toolkits in parallel.

        Args:
            toolkits (List[str]): List of toolkit names to fetch tools from

        Returns:
            List[Dict[str, Any]]: Combined list of raw tool definitions from all toolkits
        """
        if not toolkits:
            return []

        # Fetch all toolkits in parallel
        self.logger.info(f"Fetching tools from {len(toolkits)} toolkits in parallel")
        start_time = time.time()

        tasks = [self._fetch_toolkit_tools(toolkit) for toolkit in toolkits]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        raw_tools = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Failed to fetch tools from {toolkits[i]}: {result}")
            elif isinstance(result, list):
                raw_tools.extend(result)

        elapsed = time.time() - start_time
        self.logger.info(
            f"Fetched {len(raw_tools)} tools from {len(toolkits)} toolkits in {elapsed:.2f}s"
        )
        return raw_tools

    def create_tool_wrappers(
        self, raw_tools: list[dict[str, Any]], app_name: str | None = None
    ) -> list[ToolObject]:
        """Convert raw tool definitions into Autogen-compatible tool objects.

        Args:
            raw_tools (List[Dict[str, Any]]): Raw tool definitions from Composio API
            app_name: Optional app name to associate with tools

        Returns:
            List[ToolObject]: List of wrapped tool objects ready for Autogen
        """
        tools = [ToolObject(tool, app_name) for tool in raw_tools]

        self.logger.info(f"Created {len(tools)} tool wrappers")
        if self.logger.isEnabledFor(logging.DEBUG):
            for tool in tools:
                self.logger.debug(f"Tool: {tool.slug} - {tool.description}")

        return tools

    def create_tool_executor(self) -> callable:
        """Create the execution function for running Composio tools.

        Returns:
            callable: Function that executes tools with signature (slug, arguments) -> dict
        """

        def execute_tool(slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
            """Execute a Composio tool action.

            Args:
                slug (str): Tool identifier (e.g., 'GMAIL_SEND_EMAIL')
                arguments (dict): Tool-specific parameters

            Returns:
                dict: Tool execution result or error information
            """
            try:
                self.logger.info(f"Executing tool: {slug}")
                self.logger.debug(f"Arguments: {arguments}")

                result = self.composio.tools.execute(
                    slug=slug, user_id=self.user_id, arguments=arguments,
                    dangerously_skip_version_check=True,
                )

                self.logger.info(f"Successfully executed: {slug}")
                return result

            except Exception as e:
                error_msg = f"Failed to execute {slug}: {str(e)}"
                self.logger.error(error_msg, exc_info=True)

                return {
                    "error": str(e),
                    "tool": slug,
                    "arguments": arguments,
                    "success": False,
                }

        return execute_tool

    def register_tools_with_agents(
        self, tools: list[ToolObject], execute_tool: callable
    ) -> int:
        """Register wrapped tools with Autogen agents.

        Args:
            tools (List[ToolObject]): List of tool wrapper objects
            execute_tool (callable): Function to execute tools

        Returns:
            int: Number of tools successfully registered

        Raises:
            Exception: If tool registration fails
        """
        try:
            # Wrap tools in Autogen's format
            function_tools = self.toolset.wrap_tools(
                tools=tools, execute_tool=execute_tool
            )

            # Register with agents
            self.toolset.register_tools(
                caller=self.chat_agent,
                executor=self.agent_executor,
                tools=function_tools,
            )

            tool_count = len(function_tools)
            self.logger.info(f"Successfully registered {tool_count} tools with agents")

            return tool_count

        except Exception as e:
            self.logger.error(f"Failed to register tools: {str(e)}", exc_info=True)
            raise

    async def register_all_tools_async(self) -> int:
        """Async method to register all configured Composio tools.

        This is the primary entry point that coordinates the entire tool
        registration workflow with optimized parallel fetching:
        1. Check cache for existing tools
        2. Get configured toolkits from user connections
        3. Fetch tools from each toolkit in parallel
        4. Create tool wrappers
        5. Create executor function
        6. Register everything with Autogen agents

        Returns:
            int: Total number of tools registered

        Raises:
            Exception: If any critical step fails
        """
        start_time = time.time()

        try:
            # Check cache first
            cached = self._cache.get(self.user_id)
            if cached is not None:
                raw_tools = cached.get("raw_tools", [])
                self.logger.info(
                    f"Using {len(raw_tools)} cached tools for user {self.user_id}"
                )
            else:
                # Step 1: Get toolkit configuration
                toolkits = await self.get_configured_toolkits_async()

                # Step 2: Fetch raw tools from Composio in parallel
                raw_tools = await self.fetch_tools_from_toolkits_async(toolkits)

                # Cache the results
                if raw_tools:
                    self._cache.set(
                        self.user_id,
                        {"raw_tools": raw_tools, "toolkits": toolkits},
                    )

            if not raw_tools:
                self.logger.warning("No tools were fetched from any toolkit")
                return 0

            # Step 3: Create tool wrappers
            tools = self.create_tool_wrappers(raw_tools)

            # Step 4: Create executor function
            execute_tool = self.create_tool_executor()

            # Step 5: Register with agents
            tool_count = self.register_tools_with_agents(tools, execute_tool)

            elapsed = time.time() - start_time
            self.logger.info(
                f"Tool registration complete: {tool_count} tools in {elapsed:.2f}s"
            )

            return tool_count

        except Exception as e:
            self.logger.error(
                f"Critical error during tool registration: {str(e)}", exc_info=True
            )
            raise

    async def _initiate_oauth(self, app_name: str) -> dict[str, Any]:
        """Initiate OAuth connection flow for an app.

        Creates an auth config (if needed) and initiates the connection,
        returning the OAuth URL for the user to complete in their browser.

        Args:
            app_name: App name (e.g., 'GMAIL').

        Returns:
            Dict with redirect_url for OAuth and connection status.
        """
        app_slug = app_name.lower()

        # Create auth config if it doesn't exist
        try:
            auth_config = await self._run_in_executor(
                self.composio.auth_configs.create,
                app_slug,
                {"type": "use_composio_managed_auth"},
            )
            auth_config_id = auth_config.id
            self.logger.info(
                f"Created auth config for {app_name}: {auth_config_id}"
            )
        except Exception as e:
            # Might already exist — try to find it
            self.logger.info(
                f"Auth config creation failed (may already exist): {e}"
            )
            configs = await self._run_in_executor(
                self.composio.auth_configs.list
            )
            auth_config_id = None
            for c in configs.items:
                # Check toolkit_slug, name, or id for the app
                toolkit = getattr(c, "toolkit_slug", "") or ""
                name = getattr(c, "name", "") or ""
                if toolkit.lower() == app_slug or app_slug in name.lower():
                    auth_config_id = c.id
                    break
            if not auth_config_id:
                raise Exception(
                    f"Cannot find or create auth config for {app_name}"
                )

        # Initiate connection
        conn_request = await self._run_in_executor(
            self.composio.connected_accounts.initiate,
            self.user_id,
            auth_config_id,
        )

        redirect_url = getattr(conn_request, "redirect_url", None)
        conn_id = getattr(conn_request, "id", None)
        conn_status = getattr(conn_request, "status", "UNKNOWN")

        self.logger.info(
            f"OAuth initiated for {app_name}: status={conn_status}, url={redirect_url}"
        )

        return {
            "success": True,
            "app": app_name,
            "tool_count": 0,
            "message": f"Please complete {app_name} authorization in your browser, then try connecting again.",
            "oauth_required": True,
            "redirect_url": redirect_url,
            "connection_id": conn_id,
            "connection_status": conn_status,
        }

    async def connect_app_async(self, app_name: str) -> dict[str, Any]:
        """Connect a new app and register its tools without full reload.

        This method fetches tools for a single app, updates the cache,
        and registers the new tools with the agents.

        Args:
            app_name: App name to connect (e.g., 'GMAIL')

        Returns:
            Dict with status, app name, and tool count
        """
        app_upper = app_name.upper()
        start_time = time.time()

        try:
            # Verify there's an ACTIVE Composio connection (not just cached tools)
            is_active = await self.has_active_connection(app_upper)

            if not is_active:
                # No active connection — initiate OAuth flow
                self.logger.info(
                    f"No active connection for {app_upper}, initiating OAuth"
                )
                # Clear stale cache for this app
                self._cache.remove_app(self.user_id, app_upper)
                try:
                    return await self._initiate_oauth(app_upper)
                except Exception as oauth_err:
                    self.logger.error(f"OAuth initiation failed: {oauth_err}")
                    return {
                        "success": False,
                        "app": app_upper,
                        "tool_count": 0,
                        "message": f"OAuth initiation failed for {app_upper}: {str(oauth_err)}",
                    }

            # Active connection exists — check cache first
            if self._cache.has_app(self.user_id, app_upper):
                self.logger.info(
                    f"App {app_upper} already cached for user {self.user_id}"
                )
                return {
                    "success": True,
                    "app": app_upper,
                    "tool_count": len(
                        self._cache.get_app_tools(self.user_id, app_upper)
                    ),
                    "message": "App already connected",
                    "already_connected": True,
                }

            # Fetch tools for the newly connected app
            self.logger.info(f"Fetching tools for {app_upper}")
            app_tools = await self._fetch_toolkit_tools(app_upper)

            if not app_tools:
                self.logger.warning(f"No tools returned for {app_upper}")
                return {
                    "success": False,
                    "app": app_upper,
                    "tool_count": 0,
                    "message": f"Connection is active but no tools found for {app_upper}",
                }

            # Update cache
            cache_updated = self._cache.add_app(self.user_id, app_upper, app_tools)
            if not cache_updated:
                # Cache doesn't exist, create it
                self._cache.set(
                    self.user_id,
                    {"raw_tools": app_tools, "toolkits": [app_upper]},
                )

            # Create tool wrappers for new tools
            tools = self.create_tool_wrappers(app_tools, app_upper)

            # Create executor and register tools
            execute_tool = self.create_tool_executor()
            tool_count = self.register_tools_with_agents(tools, execute_tool)

            elapsed = time.time() - start_time
            self.logger.info(
                f"Connected app {app_upper}: {tool_count} tools in {elapsed:.2f}s"
            )

            return {
                "success": True,
                "app": app_upper,
                "tool_count": tool_count,
                "message": f"Successfully connected {app_upper} with {tool_count} tools",
                "already_connected": False,
            }

        except Exception as e:
            self.logger.error(f"Failed to connect app {app_upper}: {e}", exc_info=True)
            return {
                "success": False,
                "app": app_upper,
                "tool_count": 0,
                "message": f"Failed to connect app: {str(e)}",
                "error": str(e),
            }

    async def disconnect_app_async(self, app_name: str) -> dict[str, Any]:
        """Disconnect an app: revoke Composio connection and remove cached tools.

        Deletes the connected account from Composio (user will need to
        re-authorize via OAuth to use the app again) and clears local cache.

        Args:
            app_name: App name to disconnect (e.g., 'GMAIL')

        Returns:
            Dict with status, app name, and removed tools count
        """
        app_upper = app_name.upper()
        app_lower = app_name.lower()

        try:
            # Delete active Composio connections for this app
            deleted_count = 0
            try:
                connections = await self._run_in_executor(
                    self.composio.connected_accounts.list,
                    user_ids=[self.user_id],
                )
                for conn in connections.items:
                    toolkit = conn.toolkit.slug.lower() if conn.toolkit else ""
                    if toolkit == app_lower:
                        try:
                            await self._run_in_executor(
                                self.composio.connected_accounts.delete,
                                conn.id,
                            )
                            deleted_count += 1
                            self.logger.info(
                                f"Deleted Composio connection {conn.id} "
                                f"({conn.status}) for {app_upper}"
                            )
                        except Exception as del_err:
                            self.logger.warning(
                                f"Failed to delete connection {conn.id}: {del_err}"
                            )
            except Exception as e:
                self.logger.warning(
                    f"Could not list/delete Composio connections: {e}"
                )

            # Remove from local cache
            removed_slugs = self._cache.remove_app(self.user_id, app_upper)

            self.logger.info(
                f"Disconnected app {app_upper}: removed {len(removed_slugs)} tools from cache"
            )

            return {
                "success": True,
                "app": app_upper,
                "removed_count": len(removed_slugs),
                "removed_tools": removed_slugs,
                "composio_deleted": deleted_count,
                "message": (
                    f"Disconnected {app_upper}. "
                    f"{deleted_count} Composio connection(s) removed. "
                    f"{len(removed_slugs)} tools removed from cache. "
                    "You will need to re-authorize to use this app again."
                ),
                "was_connected": True,
            }

        except Exception as e:
            self.logger.error(
                f"Failed to disconnect app {app_upper}: {e}", exc_info=True
            )
            return {
                "success": False,
                "app": app_upper,
                "removed_count": 0,
                "message": f"Failed to disconnect app: {str(e)}",
                "error": str(e),
            }

    # Legacy synchronous methods for backward compatibility
    def get_user_connected_apps(
        self, user_id: str, status_filter: str | None = None
    ) -> dict[str, Any]:
        """Synchronous wrapper for get_user_connected_apps_async.

        Deprecated: Use get_user_connected_apps_async instead.
        """
        self.logger.warning(
            "Using synchronous get_user_connected_apps - consider using async version"
        )
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.get_user_connected_apps_async(user_id, status_filter)
            )
        finally:
            loop.close()

    def get_configured_toolkits(self) -> list[str]:
        """Synchronous wrapper for get_configured_toolkits_async.

        Deprecated: Use get_configured_toolkits_async instead.
        """
        self.logger.warning(
            "Using synchronous get_configured_toolkits - consider using async version"
        )
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.get_configured_toolkits_async())
        finally:
            loop.close()

    def fetch_tools_from_toolkits(self, toolkits: list[str]) -> list[dict[str, Any]]:
        """Synchronous wrapper for fetch_tools_from_toolkits_async.

        Deprecated: Use fetch_tools_from_toolkits_async instead.
        """
        self.logger.warning(
            "Using synchronous fetch_tools_from_toolkits - consider using async version"
        )
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.fetch_tools_from_toolkits_async(toolkits)
            )
        finally:
            loop.close()

    def register_all_tools(self) -> int:
        """Synchronous wrapper for register_all_tools_async.

        Deprecated: Use register_all_tools_async instead.
        """
        self.logger.warning(
            "Using synchronous register_all_tools - consider using async version"
        )
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.register_all_tools_async())
        finally:
            loop.close()


# Usage Example
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Initialize and register tools
    # manager = ComposioToolManager(
    #     user_id="user_123",
    #     chat_agent=my_chat_agent,
    #     agent_executor=my_executor_agent
    # )
    #
    # # Async usage (preferred)
    # tool_count = await manager.register_all_tools_async()
    # print(f"Ready to use {tool_count} Composio tools!")
    #
    # # Live app connection
    # result = await manager.connect_app_async("SLACK")
    # print(f"Connected: {result}")
    #
    # # Live app disconnection
    # result = await manager.disconnect_app_async("SLACK")
    # print(f"Disconnected: {result}")
