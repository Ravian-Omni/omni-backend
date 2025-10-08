import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utilities.async_helpers import async_to_sync


@dataclass
class AgentConfiguration:
    """Holds configuration for individual agents"""

    name: str
    llm_config: Optional[str] = None  # Reference to LLM config key
    system_message: str = ""
    description: str = ""
    max_consecutive_auto_reply: Optional[int] = None
    human_input_mode: str = "NEVER"
    code_execution_config: Optional[Dict[str, Any]] = None
    custom_properties: Dict[str, Any] = field(default_factory=dict)

    def get_system_message_with_substitutions(self, **kwargs) -> str:
        """Get system message with dynamic substitutions"""
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
    """Holds configuration for a specific groupchat type"""

    groupchat_key: str  # e.g., "python_developer", "file_finder"
    groupchat_settings: Dict[str, Any] = field(default_factory=dict)
    agents_config: Dict[str, AgentConfiguration] = field(default_factory=dict)
    function_descriptions: Dict[str, str] = field(default_factory=dict)
    custom_properties: Dict[str, Any] = field(default_factory=dict)

    def get_agent_config(self, agent_name: str) -> Optional[AgentConfiguration]:
        """Get configuration for a specific agent"""
        return self.agents_config.get(agent_name)

    def get_max_round(self) -> int:
        """Get max round setting"""
        return self.groupchat_settings.get("max_round", 500)

    def get_human_input_mode(self) -> str:
        """Get human input mode setting"""
        return self.groupchat_settings.get("human_input_mode", "ALWAYS")

    def get_function_description(self, function_name: str) -> Optional[str]:
        """Get description for a specific function"""
        return self.function_descriptions.get(function_name)


class GroupchatConfigurationManager:
    """Singleton class that manages all groupchat configurations"""

    _instance = None
    _initialized = False

    def __new__(cls):
        """Ensure only one instance exists using __new__ magic method"""
        if cls._instance is None:
            cls._instance = super(GroupchatConfigurationManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize only once"""
        if not GroupchatConfigurationManager._initialized:
            self.configurations: Dict[str, GroupchatConfiguration] = {}
            self.llm_configs: Dict[str, Dict[str, Any]] = {}
            self.global_settings: Dict[str, Any] = {}
            self.api_client = None
            GroupchatConfigurationManager._initialized = True
            async_to_sync(self.load_configurations_from_api())

    @classmethod
    def get_instance(cls) -> "GroupchatConfigurationManager":
        """Get the singleton instance"""
        return cls()

    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance (useful for testing)"""
        cls._instance = None
        cls._initialized = False

    async def load_configurations_from_api(self) -> None:
        """Load all configurations from API"""
        try:
            api_response = await self._fetch_all_configs_from_api()
            self._parse_and_store_configurations(api_response)
        except Exception as e:
            print(f"Error loading configurations from API: {e}")
            self._load_default_configurations()

    async def _fetch_all_configs_from_api(self) -> Dict[str, Any]:
        """Fetch all configurations from your API"""
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

    def _parse_and_store_configurations(self, api_data: Dict[str, Any]) -> None:
        """Parse API response and store configurations"""
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
        self, groupchat_key: str, config_data: Dict[str, Any]
    ) -> GroupchatConfiguration:
        """Parse individual groupchat configuration"""

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
        """Load default configurations as fallback"""
        default_config = GroupchatConfiguration(
            groupchat_key="default",
            groupchat_settings={"max_round": 500},
            agents_config={},
            function_descriptions={},
        )
        self.configurations["default"] = default_config

    def get_groupchat_configuration(
        self, groupchat_key: str
    ) -> Optional[GroupchatConfiguration]:
        """Get configuration for a specific groupchat type"""
        return self.configurations.get(groupchat_key)

    def set_llm_config(self, config_key: str, llm_config: Dict[str, Any]) -> None:
        """Set LLM configuration for a specific key"""
        self.llm_configs[config_key] = llm_config

    def get_llm_config(self, config_key: str) -> Optional[Dict[str, Any]]:
        """Get LLM configuration by key"""
        return self.llm_configs.get(config_key)

    def set_global_settings(self, settings: Dict[str, Any]) -> None:
        """Set global settings like chart_location"""
        self.global_settings.update(settings)

    def get_global_settings(self) -> Dict[str, Any]:
        """Get global settings"""
        return self.global_settings.copy()

    def list_groupchat_keys(self) -> List[str]:
        """Get list of all available groupchat keys"""
        return list(self.configurations.keys())

    def has_configuration(self, groupchat_key: str) -> bool:
        """Check if configuration exists for groupchat key"""
        return groupchat_key in self.configurations

    async def reload_configurations(self) -> None:
        """Reload all configurations from API"""
        await self.load_configurations_from_api()


# Enhanced AgentChat class that uses the singleton configuration manager
class ConfigurableAgentChat:
    """AgentChat class that uses configurations from the singleton manager"""

    def __init__(self, chat_id: str, groupchat_key: str):
        self.chat_id = chat_id
        self.groupchat_key = groupchat_key

        # Get the singleton configuration manager
        self.config_manager = GroupchatConfigurationManager.get_instance()
        self.groupchat_config: Optional[GroupchatConfiguration] = None

        self.cancellation_token = None
        self.llm_config = None
        self.agents = []
        self.groupchat = None
        self.manager = None

    async def initialize(self) -> None:
        """Initialize the chat with configuration"""
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
        """Setup default LLM configurations if not already set"""
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
        """Get LLM config for a specific agent"""
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
        """Create agents using configuration"""
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
        """Create group chat manager with configuration"""
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
        """Your existing speaker selection logic"""
        # Your original logic here
        messages = groupchat.messages

        if len(messages) == 1 or last_speaker.name == "chat_manager":
            return groupchat.agent_by_name("agent_aligner")

        # Add your existing logic here
        return None

    def set_input_function(self, input_function):
        """Set input function for user proxy agents"""
        self.input_function = input_function
        return self.input_function

    def get_function_description(self, function_name: str) -> Optional[str]:
        """Get function description from configuration"""
        return self.groupchat_config.get_function_description(function_name)


# Example usage and demonstration
async def main():
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
