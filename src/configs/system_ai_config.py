"""System AI configuration management for groupchat and agent configurations.

This module provides comprehensive configuration management for AI agent systems,
including groupchat settings, individual agent configurations, and LLM settings.
Uses singleton pattern to ensure consistent configuration across the application.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
            self.load_configurations()

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

    def load_configurations(self) -> None:
        """Load all configurations from local JSON file.

        Falls back to default configurations if file read fails.
        """
        try:
            config_path = (
                Path(__file__).parent.parent.parent
                / "configs"
                / "agent_configurations.json"
            )
            with open(config_path, "r") as f:
                api_response = json.load(f)
            self._parse_and_store_configurations(api_response)
        except Exception as e:
            print(f"Error loading configurations: {e}")
            self._load_default_configurations()

    async def reload_configurations(self) -> None:
        """Reload all configurations from file.

        Fetch fresh configurations, replacing current configurations.
        """
        self.load_configurations()
        """return {
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
            "chat": {
                "groupchat_settings": {"max_round": 500},
                "agents": {
                    "chat_agent": {"llm_config": "gpt_4_1_mini"},
                    "process_completion_agent": {"llm_config": "gpt_4_1_mini"},
                },
            },
        }"""

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

