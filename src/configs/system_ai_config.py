"""System AI configuration management for groupchat and agent configurations.

This module provides comprehensive configuration management for AI agent systems,
including groupchat settings, individual agent configurations, and LLM settings.
Uses singleton pattern to ensure consistent configuration across the application.
"""

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from src.utilities.async_helpers import async_to_sync


@dataclass
class AgentConfiguration:
    """Configuration for individual AI agents.

    Stores all settings for a single agent including LLM configuration,
    system messages, and behavior settings.

    Attributes:
        name: Unique name identifier for the agent.
        llm_config: Reference key to LLM configuration.
        system_message: System prompt/message for the agent.
        description: Human-readable description of agent's purpose.
        max_consecutive_auto_reply: Maximum consecutive auto-replies allowed.
        human_input_mode: When to request human input (NEVER, TERMINATE, ALWAYS).
        code_execution_config: Configuration for code execution capabilities.
        custom_properties: Additional custom properties for the agent.
    """

    name: str
    llm_config: str | None = None  # Reference to LLM config key
    system_message: str = ""
    description: str = ""
    max_consecutive_auto_reply: int | None = None
    human_input_mode: str = "NEVER"
    code_execution_config: dict[str, Any] | None = None
    custom_properties: dict[str, Any] = field(default_factory=dict)

    def get_system_message_with_substitutions(self, **kwargs) -> str:
        """Get system message with dynamic variable substitutions.

        Replace placeholders in system message with provided values.
        Supports both {variable} and $variable format.

        Args:
            **kwargs: Variable names and values for substitution.

        Returns:
            System message with substitutions applied, or original if
            substitution fails.
        """
        if not self.system_message:
            return ""

        # Support both {variable} and $variable format
        try:
            # First try format method for {variable}
            formatted = self.system_message.format(**kwargs)
            # Then handle $variable format
            from string import Template

            template = Template(formatted)
            return template.safe_substitute(**kwargs)
        except (KeyError, ValueError):
            return self.system_message


@dataclass
class GroupchatConfiguration:
    """Configuration for a specific groupchat type.

    Stores all settings for a groupchat including agents, settings, and
    function descriptions.

    Attributes:
        groupchat_key: Unique identifier for the groupchat type.
        groupchat_settings: Dictionary of groupchat-level settings.
        agents_config: Dictionary mapping agent names to configurations.
        function_descriptions: Dictionary of function descriptions.
        custom_properties: Additional custom properties for the groupchat.
    """

    groupchat_key: str  # e.g., "python_developer", "file_finder"
    groupchat_settings: dict[str, Any] = field(default_factory=dict)
    agents_config: dict[str, AgentConfiguration] = field(default_factory=dict)
    function_descriptions: dict[str, str] = field(default_factory=dict)
    custom_properties: dict[str, Any] = field(default_factory=dict)

    def get_agent_config(self, agent_name: str) -> AgentConfiguration | None:
        """Get configuration for a specific agent.

        Args:
            agent_name: Name of the agent to retrieve.

        Returns:
            AgentConfiguration if found, None otherwise.
        """
        return self.agents_config.get(agent_name)

    def get_max_round(self) -> int:
        """Get maximum conversation rounds setting.

        Returns:
            Maximum number of conversation rounds. Defaults to 500.
        """
        return self.groupchat_settings.get("max_round", 500)

    def get_human_input_mode(self) -> str:
        """Get human input mode setting.

        Returns:
            Human input mode string. Defaults to "ALWAYS".
        """
        return self.groupchat_settings.get("human_input_mode", "ALWAYS")

    def get_function_description(self, function_name: str) -> str | None:
        """Get description for a specific function.

        Args:
            function_name: Name of the function.

        Returns:
            Function description string if found, None otherwise.
        """
        return self.function_descriptions.get(function_name)


class GroupchatConfigurationManager:
    """Singleton manager for all groupchat configurations.

    Manages loading, parsing, and accessing groupchat configurations from the API.
    Uses singleton pattern to ensure consistent configuration state across the
    application.

    Attributes:
        configurations: Dictionary mapping groupchat keys to configurations.
        llm_configs: Dictionary of LLM configurations.
        global_settings: Dictionary of global application settings.
        api_client: API client instance for fetching configurations.
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        """Ensure only one instance exists using __new__ magic method.

        Returns:
            The singleton GroupchatConfigurationManager instance.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the configuration manager.

        Initialize only once per singleton instance, loading configurations
        from the API.
        """
        if not GroupchatConfigurationManager._initialized:
            self.configurations: dict[str, GroupchatConfiguration] = {}
            self.llm_configs: dict[str, dict[str, Any]] = {}
            self.global_settings: dict[str, Any] = {}
            self.api_client = None
            GroupchatConfigurationManager._initialized = True
            async_to_sync(self.load_configurations_from_api())

    @classmethod
    def get_instance(cls) -> "GroupchatConfigurationManager":
        """Get the singleton instance.

        Returns:
            The singleton GroupchatConfigurationManager instance.
        """
        return cls()

    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance.

        Clear the singleton instance and initialization flag. Useful for testing
        or forcing a fresh configuration load.
        """
        cls._instance = None
        cls._initialized = False

    async def load_configurations_from_api(self) -> None:
        """Load all configurations from API.

        Fetch configurations from the API and parse them. Falls back to default
        configurations if API fetch fails.

        Raises:
            Logs error if API fetch fails, then loads defaults.
        """
        try:
            api_response = await self._fetch_all_configs_from_api()
            self._parse_and_store_configurations(api_response)
        except Exception as e:
            print(f"Error loading configurations from API: {e}")
            self._load_default_configurations()

    async def _fetch_all_configs_from_api(self) -> dict[str, Any]:
        """Fetch all configurations from the API.

        Currently returns hardcoded configuration data. In production, this should
        make an actual API call to fetch configurations.

        Returns:
            Dictionary containing all groupchat configurations.
        """
        # Replace this with your actual API call
        # result = await api_client.get("/chats/configurations")
        # result = result.standard_response()
        # if not result.get("success"):
        #     raise Exception(f"Failed: {result.get('message', 'Unknown error')}")

        # return result.get("data")
        return {
            "omni": {
                "groupchat_settings": {"max_round": 500},
                "agents": {
                    "judge_question": {"llm_config": "gpt_4_1_mini"},
                    "conversation_agent": {"llm_config": "gpt_4_1_mini"},
                    "planner_agent": {"llm_config": "gpt_4_1_mini"},
                    "agent_aligner": {"llm_config": "gpt_4_1_mini"},
                    "agent_router": {"llm_config": "gpt_4_1_mini"},
                    "agent_caller": {"llm_config": "claude-sonnet-4-20250514"},
                    "manual_verification": {"llm_config": "gpt_4_1_mini"},
                    "process_completion_agent": {"llm_config": "gpt_4_1_mini"},
                },
            },
            "web_browser": {
                "groupchat_settings": {"max_round": 5},
                "agents": {
                    "browser_planner": {
                        "llm_config": "claude-3-7-sonnet-20250219",
                        "system_message": "You are a planning agent that creates execution strategies. Work directory: {chart_location}",
                        "description": "Plans the execution strategy for tasks",
                        "max_consecutive_auto_reply": 5,
                    },
                    "browser_reader": {
                        "llm_config": "claude-3-7-sonnet-20250219",
                        "system_message": "You are a code writer that implements solutions based on plans.",
                        "description": "Writes code based on planning requirements",
                    },
                    "process_completion": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a debugging specialist. Fix code issues and errors. Work directory: {chart_location}",
                        "max_consecutive_auto_reply": 5,
                    },
                },
                "function_description": {
                    "email_sender": "This function sends an email to the specified recipient with the given subject and body.",
                    "python_coder": "This function writes, executes, and debugs Python code based on the provided requirements.",
                },
            },
            "email_sender": {
                "groupchat_settings": {"max_round": 5},
                "agents": {
                    "planner_agent": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a planning agent that creates execution strategies. Work directory: {chart_location}",
                        "description": "Plans the execution strategy for tasks",
                        "max_consecutive_auto_reply": 5,
                    },
                    "intent_classifier_agent": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a planning agent that creates execution strategies. Work directory: {chart_location}",
                        "description": "Plans the execution strategy for tasks",
                        "max_consecutive_auto_reply": 5,
                    },
                    "content_writer_agent": {
                        "llm_config": "claude-3-7-sonnet-20250219",
                        "system_message": "You are a code writer that implements solutions based on plans.",
                        "description": "Writes code based on planning requirements",
                    },
                    "email_caller_agent": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a debugging specialist. Fix code issues and errors. Work directory: {chart_location}",
                        "max_consecutive_auto_reply": 5,
                    },
                    "process_completion_agent": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a debugging specialist. Fix code issues and errors. Work directory: {chart_location}",
                        "max_consecutive_auto_reply": 5,
                    },
                },
                "function_description": {
                    "email_sender": "This function sends an email to the specified recipient with the given subject and body.",
                    "python_coder": "This function writes, executes, and debugs Python code based on the provided requirements.",
                },
            },
            "file_finder": {
                "groupchat_settings": {"max_round": 5},
                "agents": {
                    "file_finder_planner": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a planning agent that creates execution strategies. Work directory: {chart_location}",
                        "description": "Plans the execution strategy for tasks",
                        "max_consecutive_auto_reply": 5,
                    },
                    "file_finder": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a planning agent that creates execution strategies. Work directory: {chart_location}",
                        "description": "Plans the execution strategy for tasks",
                        "max_consecutive_auto_reply": 5,
                    },
                    "prob_status_checker": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a code writer that implements solutions based on plans.",
                        "description": "Writes code based on planning requirements",
                    },
                    "process_completion": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a debugging specialist. Fix code issues and errors. Work directory: {chart_location}",
                        "max_consecutive_auto_reply": 5,
                    },
                },
                "function_description": {
                    "email_sender": "This function sends an email to the specified recipient with the given subject and body.",
                    "python_coder": "This function writes, executes, and debugs Python code based on the provided requirements.",
                },
            },
            "image_generator": {
                "groupchat_settings": {"max_round": 5},
                "agents": {
                    "user_intent": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a planning agent that creates execution strategies. Work directory: {chart_location}",
                        "description": "Plans the execution strategy for tasks",
                        "max_consecutive_auto_reply": 5,
                    },
                    "image_prompt_generator": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a planning agent that creates execution strategies. Work directory: {chart_location}",
                        "description": "Plans the execution strategy for tasks",
                        "max_consecutive_auto_reply": 5,
                    },
                    "image_generator_caller": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a code writer that implements solutions based on plans.",
                        "description": "Writes code based on planning requirements",
                    },
                    "process_completion": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a debugging specialist. Fix code issues and errors. Work directory: {chart_location}",
                        "max_consecutive_auto_reply": 5,
                    },
                },
                "function_description": {
                    "email_sender": "This function sends an email to the specified recipient with the given subject and body.",
                    "python_coder": "This function writes, executes, and debugs Python code based on the provided requirements.",
                },
                "custom_properties": {
                    "image_api": {
                        "llm_config": "image_together_llm",
                        "configuration": {"width": 768, "height": 432, "steps": 30},
                    }
                },
            },
            "python_coder": {
                "groupchat_settings": {"max_round": 5},
                "agents": {
                    "planner_agent": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a planning agent that creates execution strategies. Work directory: {chart_location}",
                        "description": "Plans the execution strategy for tasks",
                        "max_consecutive_auto_reply": 5,
                    },
                    "code_writer_agent": {
                        "llm_config": "claude-sonnet-4-20250514",
                        "system_message": "You are a planning agent that creates execution strategies. Work directory: {chart_location}",
                        "description": "Plans the execution strategy for tasks",
                        "max_consecutive_auto_reply": 5,
                    },
                    "code_debugger_agent": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a code writer that implements solutions based on plans.",
                        "description": "Writes code based on planning requirements",
                    },
                    "problem_status_checker_agent": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a debugging specialist. Fix code issues and errors. Work directory: {chart_location}",
                        "max_consecutive_auto_reply": 5,
                    },
                    "process_completion_agent": {
                        "llm_config": "gpt_4_1_mini",
                        "system_message": "You are a debugging specialist. Fix code issues and errors. Work directory: {chart_location}",
                        "max_consecutive_auto_reply": 5,
                    },
                },
                "function_description": {
                    "email_sender": "This function sends an email to the specified recipient with the given subject and body.",
                    "python_coder": "This function writes, executes, and debugs Python code based on the provided requirements.",
                },
            },
        }

    def _parse_and_store_configurations(self, api_data: dict[str, Any]) -> None:
        """Parse API response and store configurations.

        Extract groupchat configurations from API data and store them internally.

        Args:
            api_data: Dictionary containing all groupchat configuration data.
        """
        # Clear existing configurations
        self.configurations.clear()

        # Parse each groupchat configuration
        for groupchat_key, config_data in api_data.items():
            groupchat_config = self._parse_groupchat_config(groupchat_key, config_data)
            self.configurations[groupchat_key] = groupchat_config

        print(
            f"Loaded {len(self.configurations)} groupchat configurations: {list(self.configurations.keys())}"
        )

    def _parse_groupchat_config(
        self, groupchat_key: str, config_data: dict[str, Any]
    ) -> GroupchatConfiguration:
        """Parse individual groupchat configuration.

        Convert raw configuration data into structured GroupchatConfiguration.

        Args:
            groupchat_key: Unique identifier for the groupchat.
            config_data: Raw configuration data for the groupchat.

        Returns:
            Parsed GroupchatConfiguration instance.
        """

        # Parse agent configurations
        agents_config = {}
        for agent_name, agent_data in config_data.get("agents", {}).items():
            agent_config = AgentConfiguration(
                name=agent_name,
                llm_config=agent_data.get("llm_config"),
                system_message=agent_data.get("system_message", ""),
                description=agent_data.get("description", ""),
                max_consecutive_auto_reply=agent_data.get("max_consecutive_auto_reply"),
                human_input_mode=agent_data.get("human_input_mode", "NEVER"),
                code_execution_config=agent_data.get("code_execution_config"),
                custom_properties=agent_data.get("custom_properties", {}),
            )
            agents_config[agent_name] = agent_config

        # Create groupchat configuration
        return GroupchatConfiguration(
            groupchat_key=groupchat_key,
            groupchat_settings=config_data.get("groupchat_settings", {}),
            agents_config=agents_config,
            function_descriptions=config_data.get("function_description", {}),
            custom_properties=config_data.get("custom_properties", {}),
        )

    def _load_default_configurations(self) -> None:
        """Load default configurations as fallback.

        Create minimal default configuration when API fetch fails.
        """
        default_config = GroupchatConfiguration(
            groupchat_key="default",
            groupchat_settings={"max_round": 500},
            agents_config={},
            function_descriptions={},
        )
        self.configurations["default"] = default_config

    def get_groupchat_configuration(
        self, groupchat_key: str
    ) -> GroupchatConfiguration | None:
        """Get configuration for a specific groupchat type.

        Args:
            groupchat_key: Unique identifier for the groupchat.

        Returns:
            GroupchatConfiguration if found, None otherwise.
        """
        return self.configurations.get(groupchat_key)

    def set_llm_config(self, config_key: str, llm_config: dict[str, Any]) -> None:
        """Set LLM configuration for a specific key.

        Args:
            config_key: Unique identifier for the LLM configuration.
            llm_config: Dictionary containing LLM configuration settings.
        """
        self.llm_configs[config_key] = llm_config

    def get_llm_config(self, config_key: str) -> dict[str, Any] | None:
        """Get LLM configuration by key.

        Args:
            config_key: Unique identifier for the LLM configuration.

        Returns:
            LLM configuration dictionary if found, None otherwise.
        """
        return self.llm_configs.get(config_key)

    def set_global_settings(self, settings: dict[str, Any]) -> None:
        """Set global settings.

        Update global settings with provided values. Merges with existing settings.

        Args:
            settings: Dictionary of settings to update or add.
        """
        self.global_settings.update(settings)

    def get_global_settings(self) -> dict[str, Any]:
        """Get global settings.

        Returns:
            Copy of global settings dictionary.
        """
        return self.global_settings.copy()

    def list_groupchat_keys(self) -> list[str]:
        """Get list of all available groupchat keys.

        Returns:
            List of groupchat key strings.
        """
        return list(self.configurations.keys())

    def has_configuration(self, groupchat_key: str) -> bool:
        """Check if configuration exists for groupchat key.

        Args:
            groupchat_key: Unique identifier for the groupchat.

        Returns:
            True if configuration exists, False otherwise.
        """
        return groupchat_key in self.configurations

    async def reload_configurations(self) -> None:
        """Reload all configurations from API.

        Fetch fresh configurations from the API, replacing current configurations.
        """
        await self.load_configurations_from_api()


# Enhanced AgentChat class that uses the singleton configuration manager
class ConfigurableAgentChat:
    """AgentChat implementation using singleton configuration manager.

    Provides a configurable agent chat system that retrieves settings from
    the singleton GroupchatConfigurationManager. Manages agent creation,
    groupchat setup, and speaker selection.

    Attributes:
        chat_id: Unique identifier for this chat instance.
        groupchat_key: Key identifying which groupchat configuration to use.
        config_manager: Reference to singleton configuration manager.
        groupchat_config: Configuration for this specific groupchat.
        cancellation_token: Token for cancelling operations.
        llm_config: LLM configuration settings.
        agents: List of agent instances.
        groupchat: Groupchat instance.
        manager: GroupChat manager instance.
    """

    def __init__(self, chat_id: str, groupchat_key: str):
        """Initialize the configurable agent chat.

        Args:
            chat_id: Unique identifier for this chat instance.
            groupchat_key: Key identifying which groupchat configuration to use.
        """
        self.chat_id = chat_id
        self.groupchat_key = groupchat_key

        # Get the singleton configuration manager
        self.config_manager = GroupchatConfigurationManager.get_instance()
        self.groupchat_config: GroupchatConfiguration | None = None

        self.cancellation_token = None
        self.llm_config = None
        self.agents = []
        self.groupchat = None
        self.manager = None

    async def initialize(self) -> None:
        """Initialize the chat with configuration.

        Load configuration for this groupchat type, set up default LLM configs,
        and create agents and chat manager.

        Raises:
            ValueError: If no configuration found for the groupchat key.
        """
        # Get configuration for this groupchat type
        self.groupchat_config = self.config_manager.get_groupchat_configuration(
            self.groupchat_key
        )

        if not self.groupchat_config:
            raise ValueError(
                f"No configuration found for groupchat key: {self.groupchat_key}"
            )

        # Set up default LLM config if not already set
        self._setup_default_llm_configs()

        # Create agents using your existing methods but with config
        self.agents = self.get_agents()
        self.get_chat_manager()

    def _setup_default_llm_configs(self) -> None:
        """Setup default LLM configurations if not already set.

        Initialize default LLM configurations for various agent types using
        OpenAI API settings from environment variables.
        """
        default_llm_config = {
            "api_type": "openai",
            "model": "gpt-4o",
            "api_key": os.environ.get("OPENAI_API_KEY"),
        }

        # Set default configs for different agent types if not already set
        llm_config_keys = [
            "llm_planner",
            "llm_code_writer",
            "llm_code_debugger",
            "llm_default",
        ]

        for key in llm_config_keys:
            if not self.config_manager.get_llm_config(key):
                self.config_manager.set_llm_config(key, default_llm_config)

        # Set global settings
        self.config_manager.set_global_settings({"chart_location": os.getcwd()})

    def _get_agent_llm_config(self, agent_name: str):
        """Get LLM configuration for a specific agent.

        Retrieve the LLM configuration for the specified agent, falling back
        to default if agent-specific config is not found.

        Args:
            agent_name: Name of the agent.

        Returns:
            LLMConfig instance if found, None otherwise.
        """
        from autogen import LLMConfig

        agent_config = self.groupchat_config.get_agent_config(agent_name)
        if agent_config and agent_config.llm_config:
            llm_config_dict = self.config_manager.get_llm_config(
                agent_config.llm_config
            )
            if llm_config_dict:
                return LLMConfig(**llm_config_dict)

        # Fallback to default
        default_config = self.config_manager.get_llm_config("llm_default")
        return LLMConfig(**default_config) if default_config else None

    def get_planner(self):
        """Create and configure the planner agent.

        Returns:
            Configured AssistantAgent for planning tasks.

        Raises:
            ValueError: If planner_agent configuration is not found.
        """
        import autogen

        agent_config = self.groupchat_config.get_agent_config("planner_agent")
        if not agent_config:
            raise ValueError("planner_agent configuration not found")

        system_message = agent_config.get_system_message_with_substitutions(
            **self.config_manager.get_global_settings()
        )

        return autogen.AssistantAgent(
            name="planner_agent",
            llm_config=self._get_agent_llm_config("planner_agent"),
            system_message=system_message,
            description=agent_config.description,
            max_consecutive_auto_reply=agent_config.max_consecutive_auto_reply,
        )

    def get_code_writer(self):
        """Create and configure the code writer agent.

        Returns:
            Configured AssistantAgent for writing code.

        Raises:
            ValueError: If code_writer_agent configuration is not found.
        """
        import autogen

        agent_config = self.groupchat_config.get_agent_config("code_writer_agent")
        if not agent_config:
            raise ValueError("code_writer_agent configuration not found")

        system_message = agent_config.get_system_message_with_substitutions(
            **self.config_manager.get_global_settings()
        )

        return autogen.AssistantAgent(
            name="code_writer_agent",
            llm_config=self._get_agent_llm_config("code_writer_agent"),
            system_message=system_message,
            description=agent_config.description,
        )

    def get_code_executor(self):
        """Create and configure the code executor agent.

        Returns:
            Configured UserProxyAgent for executing code.
        """
        from autogen import UserProxyAgent

        agent_config = self.groupchat_config.get_agent_config("code_executor_agent")

        return UserProxyAgent(
            name="code_executor_agent",
            human_input_mode=agent_config.human_input_mode if agent_config else "NEVER",
            code_execution_config=(
                agent_config.code_execution_config
                if agent_config
                else {
                    "work_dir": os.getcwd(),
                    "use_docker": False,
                }
            ),
            llm_config=self._get_agent_llm_config("code_executor_agent"),
        )

    def get_code_debugger(self):
        """Create and configure the code debugger agent.

        Returns:
            Configured AssistantAgent for debugging code.

        Raises:
            ValueError: If code_debugger_agent configuration is not found.
        """
        import autogen

        agent_config = self.groupchat_config.get_agent_config("code_debugger_agent")
        if not agent_config:
            raise ValueError("code_debugger_agent configuration not found")

        system_message = agent_config.get_system_message_with_substitutions(
            **self.config_manager.get_global_settings()
        )

        return autogen.AssistantAgent(
            name="code_debugger_agent",
            llm_config=self._get_agent_llm_config("code_debugger_agent"),
            max_consecutive_auto_reply=agent_config.max_consecutive_auto_reply or 5,
            system_message=system_message,
        )

    def get_agent_aligner(self):
        """Create and configure the agent aligner.

        Returns:
            Configured AssistantAgent for aligning agent responses.

        Raises:
            ValueError: If agent_aligner configuration is not found.
        """
        import autogen

        agent_config = self.groupchat_config.get_agent_config("agent_aligner")
        if not agent_config:
            raise ValueError("agent_aligner configuration not found")

        return autogen.AssistantAgent(
            name="agent_aligner",
            llm_config=self._get_agent_llm_config("agent_aligner"),
            description=agent_config.description,
            system_message=agent_config.system_message,
        )

    def get_process_completion(self):
        """Create and configure the process completion agent.

        Returns:
            Configured AssistantAgent for completing processes.

        Raises:
            ValueError: If process_completion_agent configuration is not found.
        """
        import autogen

        agent_config = self.groupchat_config.get_agent_config(
            "process_completion_agent"
        )
        if not agent_config:
            raise ValueError("process_completion_agent configuration not found")

        return autogen.AssistantAgent(
            name="process_completion_agent",
            llm_config=self._get_agent_llm_config("process_completion_agent"),
            system_message=agent_config.system_message,
        )

    def get_agents(self):
        """Create all agents using configuration.

        Initialize all agent instances for this chat including planner,
        aligner, code writer, executor, debugger, and completion agents.

        Returns:
            List of all configured agent instances.
        """
        self.planner = self.get_planner()
        self.agent_aligner = self.get_agent_aligner()
        self.code_writer = self.get_code_writer()
        self.code_executor = self.get_code_executor()
        self.code_debugger = self.get_code_debugger()
        self.process_completion = self.get_process_completion()

        return [
            self.planner,
            self.agent_aligner,
            self.code_writer,
            self.code_executor,
            self.code_debugger,
            self.process_completion,
        ]

    def get_chat_manager(self):
        """Create group chat manager with configuration.

        Initialize the groupchat and manager with configured agents and settings.

        Returns:
            Tuple of (manager, groupchat) instances.
        """
        import autogen

        self.groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self.custom_speaker_selection_func,
            max_round=self.groupchat_config.get_max_round(),
        )

        # You'll need to import your CustomGroupChatManager
        # from your_module import CustomGroupChatManager

        # For now, using standard GroupChatManager
        self.manager = autogen.GroupChatManager(
            groupchat=self.groupchat,
            llm_config=self._get_agent_llm_config("agent_aligner"),
            human_input_mode=self.groupchat_config.get_human_input_mode(),
        )
        return self.manager, self.groupchat

    def custom_speaker_selection_func(self, last_speaker, groupchat):
        """Custom speaker selection logic for groupchat.

        Determine the next speaker based on conversation state and last speaker.

        Args:
            last_speaker: The agent that spoke last.
            groupchat: The groupchat instance.

        Returns:
            Next agent to speak, or None for default selection.
        """
        # Your original logic here
        messages = groupchat.messages

        if len(messages) == 1 or last_speaker.name == "chat_manager":
            return groupchat.agent_by_name("agent_aligner")

        # Add your existing logic here
        return None

    def set_input_function(self, input_function):
        """Set input function for user proxy agents.

        Configure how user input is collected by proxy agents.

        Args:
            input_function: Function to call for user input.

        Returns:
            The configured input function.
        """
        self.input_function = input_function
        return self.input_function

    def get_function_description(self, function_name: str) -> str | None:
        """Get function description from configuration.

        Args:
            function_name: Name of the function.

        Returns:
            Function description string if found, None otherwise.
        """
        return self.groupchat_config.get_function_description(function_name)


# Example usage and demonstration
async def main():
    """Demonstrate usage of the configuration management system.

    Example function showing how to initialize and use the groupchat
    configuration manager and configurable agent chats.
    """
    # Initialize the singleton configuration manager
    config_manager = GroupchatConfigurationManager.get_instance()

    # Load configurations from API
    await config_manager.load_configurations_from_api()

    print("Available groupchat configurations:")
    for key in config_manager.list_groupchat_keys():
        print(f"  - {key}")

    # Create different chat instances using different configurations
    python_chat = ConfigurableAgentChat(
        chat_id="chat_001", groupchat_key="python_developer"
    )
    file_finder_chat = ConfigurableAgentChat(
        chat_id="chat_002", groupchat_key="file_finder"
    )

    # Initialize chats
    await python_chat.initialize()
    await file_finder_chat.initialize()

    # Both chats use the same configuration manager instance
    print(
        f"Same config manager: {python_chat.config_manager is file_finder_chat.config_manager}"
    )

    # Access function descriptions
    email_desc = python_chat.get_function_description("email_sender")
    print(f"Email sender function: {email_desc}")

    # You can also access the global configuration manager directly
    global_manager = GroupchatConfigurationManager.get_instance()
    python_config = global_manager.get_groupchat_configuration("python_developer")

    if python_config:
        planner_config = python_config.get_agent_config("planner_agent")
        print(f"Planner agent description: {planner_config.description}")

    # Reload configurations if needed
    # await config_manager.reload_configurations()


if __name__ == "__main__":
    asyncio.run(main())
