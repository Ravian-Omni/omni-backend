import logging
from inspect import Signature
from typing import Any

from autogen_core.tools import FunctionTool
from composio import Composio
from composio.client.types import Tool
from composio.core.provider.agentic import AgenticProviderExecuteFn
from composio.utils.shared import get_signature_format_from_schema_params
from composio_autogen import AutogenProvider

from src.configs.llm_configs_manager import LLMConfigManager  # type: ignore


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


class ComposioToolManager:
    """Manages Composio tool registration and execution for Autogen agents.

    This class handles the complete lifecycle of Composio tools:
    - Fetching tools from multiple toolkits
    - Creating tool wrappers compatible with Autogen
    - Registering tools with chat and executor agents
    - Executing tool actions with proper error handling

    Attributes:
        user_id (str): Unique identifier for the user's Composio session
        chat_agent: Autogen chat agent that will use the tools
        agent_executor: Autogen executor agent that will run the tools
        composio (Composio): Composio API client instance
        toolset (AutogenProvider): Autogen-specific tool provider
        logger (logging.Logger): Logger instance for this class
    """

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
        # Initialize Tavily client
        api_key = composio_api_key.get("config_list", [])[0].get("api_key")

        self.composio = Composio(api_key=api_key)
        self.toolset = NuitkaSafeAutogenProvider()

        self.logger.info(f"Initialized ComposioToolManager for user: {user_id}")

    def get_user_connected_apps(
        self, user_id: str, status_filter: str | None = None
    ) -> dict[str, Any]:
        """Get all connected apps for a user from Composio.

        Args:
            user_id: User identifier
            status_filter: Optional filter by status (ACTIVE, EXPIRED, etc.)

        Returns:
            Dictionary with user's connected apps information.
        """
        print(f"Fetching connected apps for user {user_id}")

        try:
            # Fetch all connections from Composio
            connections = self.composio.connected_accounts.list(user_ids=[user_id])

            apps = []
            app_names = []
            active_count = 0

            for conn in connections.items:
                try:
                    # Extract app name from toolkit
                    app_name = conn.toolkit.slug.upper() if conn.toolkit else "UNKNOWN"
                    display_name = (
                        conn.toolkit.slug.title() if conn.toolkit else "Unknown"
                    )

                    # Get status
                    status = conn.status

                    # Apply status filter if provided
                    if status_filter and status != status_filter.upper():
                        continue

                    # Check if active
                    is_active = status == "ACTIVE"
                    if is_active:
                        active_count += 1

                    # Create app info
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
                    print(f"Error parsing connection {conn.id}: {e}")
                    continue

            print(
                f"Found {len(apps)} connected apps for user {user_id} ({active_count} active)"
            )

            return {
                "user_id": user_id,
                "total_apps": len(apps),
                "active_apps": active_count,
                "apps": apps,
                "app_names": app_names,
            }

        except Exception as e:
            print(f"Failed to fetch connected apps: {e}")
            raise

    def get_configured_toolkits(self) -> list[str]:
        """Retrieve the list of toolkits from environment configuration.

        Reads COMPOSIO_TOOLKITS environment variable and parses it into
        a list of toolkit names. Defaults to GMAIL and GITHUB if not set.

        Returns:
            List[str]: List of toolkit names (e.g., ['GMAIL', 'GITHUB'])

        Example:
            >>> manager.get_configured_toolkits()
            ['GMAIL', 'GITHUB', 'SLACK']
        """
        toolkits_user = self.get_user_connected_apps(self.user_id)
        # toolkits_str = os.environ.get("COMPOSIO_TOOLKITS", "GMAIL,GITHUB")
        # toolkits = [toolkit.strip() for toolkit in toolkits_str.split(",")]
        toolkits = toolkits_user.get("app_names")

        self.logger.info(f"Configured toolkits: {toolkits}")
        return toolkits

    def fetch_tools_from_toolkits(self, toolkits: list[str]) -> list[dict[str, Any]]:
        """Fetch tools from multiple Composio toolkits.

        Due to a Composio limitation, tools must be fetched one toolkit at a time
        and then combined. This method handles that process with proper error handling.

        Args:
            toolkits (List[str]): List of toolkit names to fetch tools from

        Returns:
            List[Dict[str, Any]]: Combined list of raw tool definitions from all toolkits

        Note:
            Failed toolkit fetches are logged but don't stop the process.
            Other toolkits will continue to be processed.
        """
        raw_tools = []

        for toolkit in toolkits:
            try:
                toolkit_tools = self.composio.tools.get(
                    user_id=self.user_id, toolkits=[toolkit]
                )
                raw_tools.extend(toolkit_tools)
                self.logger.info(
                    f"Successfully fetched {len(toolkit_tools)} tools from {toolkit}"
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to fetch tools from {toolkit}: {str(e)}", exc_info=True
                )

        self.logger.info(
            f"Total tools fetched: {len(raw_tools)} from {len(toolkits)} toolkits"
        )
        return raw_tools

    def create_tool_wrappers(self, raw_tools: list[dict[str, Any]]) -> list[Any]:
        """Convert raw tool definitions into Autogen-compatible tool objects.

        Creates wrapper objects that extract the necessary metadata from
        Composio's tool format (slug, description, parameters) into a format
        that Autogen can work with.

        Args:
            raw_tools (List[Dict[str, Any]]): Raw tool definitions from Composio API

        Returns:
            List[ToolObject]: List of wrapped tool objects ready for Autogen

        Example tool structure:
            raw_tool = {
                'function': {
                    'name': 'GMAIL_SEND_EMAIL',
                    'description': 'Send an email via Gmail',
                    'parameters': {...}
                }
            }
        """

        class ToolObject:
            """Wrapper class for Composio tool definitions.

            Attributes:
                slug (str): Unique tool identifier (e.g., 'GMAIL_SEND_EMAIL')
                description (str): Human-readable description of the tool
                input_parameters (dict): JSON schema of tool parameters
            """

            def __init__(self, data: dict[str, Any]):
                function_info = data.get("function", {})
                self.slug = function_info.get("name")
                self.description = function_info.get("description", "")
                self.input_parameters = function_info.get("parameters", {})

        tools = [ToolObject(tool) for tool in raw_tools]

        self.logger.info(f"Created {len(tools)} tool wrappers")
        if self.logger.isEnabledFor(logging.DEBUG):
            for tool in tools:
                self.logger.debug(f"Tool: {tool.slug} - {tool.description}")

        return tools

    def create_tool_executor(self) -> callable:
        """Create the execution function for running Composio tools.

        This function will be called by Autogen when a tool needs to be executed.
        It uses the Composio API to run the actual tool action and returns results.

        Returns:
            callable: Function that executes tools with signature (slug, arguments) -> dict

        The returned function:
            - Takes a tool slug (str) and arguments (dict)
            - Executes the tool via Composio API
            - Returns the result dict or error dict
        """

        def execute_tool(slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
            """Execute a Composio tool action.

            Args:
                slug (str): Tool identifier (e.g., 'GMAIL_SEND_EMAIL')
                arguments (dict): Tool-specific parameters

            Returns:
                dict: Tool execution result or error information

            Example:
                >>> execute_tool('GMAIL_SEND_EMAIL', {
                ...     'to': 'user@example.com',
                ...     'subject': 'Hello',
                ...     'body': 'Test email'
                ... })
                {'status': 'success', 'message_id': '...'}
            """
            try:
                self.logger.info(f"Executing tool: {slug}")
                self.logger.debug(f"Arguments: {arguments}")

                result = self.composio.tools.execute(
                    slug=slug, user_id=self.user_id, arguments=arguments
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
        self, tools: list[Any], execute_tool: callable
    ) -> int:
        """Register wrapped tools with Autogen agents.

        This method:
        1. Wraps tools using Autogen's provider format
        2. Registers them with both chat and executor agents
        3. Returns count of successfully registered tools

        Args:
            tools (List[Any]): List of tool wrapper objects
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

    def register_all_tools(self) -> int:
        """Main orchestration method to register all configured Composio tools.

        This is the primary entry point that coordinates the entire tool
        registration workflow:
        1. Get configured toolkits from environment
        2. Fetch tools from each toolkit
        3. Create tool wrappers
        4. Create executor function
        5. Register everything with Autogen agents

        Returns:
            int: Total number of tools registered

        Raises:
            Exception: If any critical step fails

        Example:
            >>> manager = ComposioToolManager('user123', chat_agent, executor)
            >>> count = manager.register_all_tools()
            >>> print(f"Registered {count} tools")
            Registered 42 tools
        """
        try:
            # Step 1: Get toolkit configuration
            toolkits = self.get_configured_toolkits()

            # Step 2: Fetch raw tools from Composio
            raw_tools = self.fetch_tools_from_toolkits(toolkits)

            if not raw_tools:
                self.logger.warning("No tools were fetched from any toolkit")
                return 0

            # Step 3: Create tool wrappers
            tools = self.create_tool_wrappers(raw_tools)

            # Step 4: Create executor function
            execute_tool = self.create_tool_executor()

            # Step 5: Register with agents
            tool_count = self.register_tools_with_agents(tools, execute_tool)

            self.logger.info(
                f"✅ Tool registration complete: {tool_count} tools from "
                f"{len(toolkits)} toolkits"
            )

            return tool_count

        except Exception as e:
            self.logger.error(
                f"Critical error during tool registration: {str(e)}", exc_info=True
            )
            raise


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
    # tool_count = manager.register_all_tools()
    # print(f"Ready to use {tool_count} Composio tools!")
