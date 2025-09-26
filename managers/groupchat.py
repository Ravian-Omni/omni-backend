from composio import Composio
from composio_autogen import AutogenProvider
from together import Together
from typing import Annotated, List, Dict
from tavily import TavilyClient
from autogen import LLMConfig
from capabilities.chat_mode import prompts
from capabilities.chat_mode.helpers import async_to_sync
from dependencies import get_websocket_manager
import autogen
from autogen import UserProxyAgent
import os
import json
from typing import List, Dict, Any
from datetime import datetime
import asyncio
from string import Template
from typing import List, Optional, Dict, Any
today_date = datetime.now()

from dotenv import load_dotenv

load_dotenv()

class CustomGroupChatManager(autogen.GroupChatManager):
    def __init__(self, groupchat, llm_config, chat_id=None, human_input_mode="NEVER", queue: Optional[asyncio.Queue] = None):
        super().__init__(groupchat=groupchat, llm_config=llm_config,
                         human_input_mode=human_input_mode)
        self.queue = queue
        self.chat_id = chat_id

    async def send_websocket(self, message):
        ws_manager = await get_websocket_manager()
        await ws_manager.send_chat_message(session_id=self.chat_id, content=message, source="AgentChat")
        return

    def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
        super()._print_received_message(message, sender)
        content = message.get("content", "") if isinstance(
            message, dict) else str(message)
        db_content = {"role": "user", "name": sender.name, "content": content}
        db_content["raw_message"] = message
        async_to_sync(self.send_websocket(db_content))


class CustomUserProxyAgent(UserProxyAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def set_input_function(self, input_function):
        self.input_function = input_function
        return self.input_function

    async def a_get_human_input(self, prompt: str) -> str:
        print("🔁 Custom logic before input...")

        prompt = json.dumps({"agent": self.name, "prompt": prompt})
        return await self.input_function(prompt)


class AgentChat:
    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        self.cancellation_token = None
        self.llm_config = LLMConfig(
            api_type="openai", model="gpt-4.1-mini", api_key=os.environ["OPENAI_API_KEY"])

        self.agents = self.get_agents()
        self._register_functions()
        self.get_chat_manager()

    def set_input_function(self, input_function):
        self.input_function = input_function
        return self.input_function

    def _set_cancellation_token(self, cancellation_token):
        self.cancellation_token = cancellation_token

    def _check_cancellation(self):
        """Check if operations should be cancelled"""
        if self.cancellation_token and self.cancellation_token.is_cancelled():
            raise asyncio.CancelledError(
                f"OMNI operation cancelled for session {self.chat_id}")

    def get_chat_agent(self):
        return autogen.AssistantAgent(
            name="chat_agent",
            llm_config=self.llm_config,
            is_termination_msg=lambda msg: msg.get(
                "content", "").strip().upper() == "TERMINATE",
            system_message=prompts.chat_agent.format(
                today=today_date.strftime("%Y-%m-%d"))
        )

    def get_agent_executor(self):
        return UserProxyAgent(
            "agent_executor",
            human_input_mode="NEVER",
            # description="""This agent will execute the function which are group chat on their own""",
            code_execution_config=False,
            # is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
        )

    async def get_web_browser(self, query: Annotated[str, "The complete search query with all the details like subject relationship with the message"]):
        """API-based search tool using Tavily."""
        try:
            tavilyclient = TavilyClient(
                api_key="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")
            response = tavilyclient.search(
                query, search_depth="advanced", include_favicon=True, max_results=5, days=180)

            if response and 'results' in response:
                result_text = f"Query: {response.get('query', query)}\n"
                result_text += f"Found {len(response['results'])} results:\n\n"

                for i, result in enumerate(response['results'][:5], 1):
                    result_text += f"{i}. {result.get('title', 'No title')}\n"
                    result_text += f"   URL: {result.get('url', 'No URL')}\n"
                    result_text += f"   Content: {result.get('content', 'No content')[:800]}...\n\n"

                return result_text
            else:
                return "No results found"

        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            print(error_msg)
            return error_msg

    async def get_image_generator(self, prompt: Annotated[str, "The image generation prompt"], filename: Annotated[str, "The filename to save the image as"] = None):
        try:
            import requests
            import time
            together_api_key = "06db08babf63e2c871ca8b7709d82f753728e7144e1e32d22b1469b0238a8331"
            client = Together(api_key=together_api_key)
            response = client.images.generate(
                prompt=prompt,
                model="black-forest-labs/FLUX.1-dev",
                n=1,
                width=1024,
                height=1024,
                steps=30
            )

            # Download and save the image with the generated filename
            image_url = response.data[0].url
            image_response = requests.get(image_url)

            # Use current timestamp if no filename provided
            filename = filename if filename else f"{int(time.time())}.jpg"

            # to be updated with project creation path
            file_name = os.path.join(os.path.abspath("."), filename)
            with open(file_name, "wb") as f:
                f.write(image_response.content)

            return f"Image successfully generated and saved at {file_name}"

        except Exception as e:
            error_message = f"Error generating image: {str(e)}"
            return error_message

    def _register_functions(self):
        composio_api_key = os.environ.get("COMPOSIO_API_KEY", "")
        composio = Composio(api_key=composio_api_key)

        # User ID must be a valid UUID format
        # Replace with actual user UUID from your database
        user_id = "9239298d-389c-5315-905c-464469e5d397"
        # Wrapper functions before registring to agents
        toolset = AutogenProvider()
        raw_tools = composio.tools.get(user_id=user_id, toolkits=["GMAIL",])

        print(f"Got {len(raw_tools)} tools")

        def create_tool_wrapper(tool_data):
            class ToolObject:
                def __init__(self, data):
                    function_info = data.get('function', {})
                    self.slug = function_info.get('name')
                    self.description = function_info.get('description', '')
                    self.input_parameters = function_info.get('parameters', {})
            return ToolObject(tool_data)

        tools = [create_tool_wrapper(tool) for tool in raw_tools]

        def execute_tool(slug: str, arguments: dict) -> dict:
            """Execute Composio action using the correct API"""
            try:
                print(f"Executing tool: {slug} with arguments: {arguments}")

                # Use the correct Composio API pattern
                result = composio.tools.execute(
                    slug=slug,  # or just slug if action parameter name is different
                    user_id=user_id,
                    arguments=arguments
                )

                print(f"Successfully executed: {slug}")
                return result

            except Exception as e:
                error_msg = f"Failed to execute {slug}: {str(e)}"
                print(error_msg)
                return {
                    "error": str(e),
                    "tool": slug,
                    "arguments": arguments
                }

        # Wrap and register tools
        function_tools = toolset.wrap_tools(
            tools=tools, execute_tool=execute_tool)
        toolset.register_tools(
            caller=self.chat_agent,
            executor=self.agent_executor,
            tools=function_tools,
        )

        print(f"✅ Successfully registered {len(function_tools)} Gmail tools")

        # Print some tool names for verification
        for i, tool in enumerate(tools[:5]):
            print(f"  {i+1}. {tool.slug}")
        if len(tools) > 5:
            print(f"  ... and {len(tools) - 5} more tools")

        async def image_generator_wrapper(prompt: Annotated[str, "The image generation prompt"], filename: Annotated[str, "The filename to save the image as"]):
            return await self.get_image_generator(prompt=prompt, filename=filename)

        async def web_browser_wrapper(query: Annotated[str, "The complete search query with all the details like subject relationship with the message",]) -> Annotated[str, "The complete search query with all the details like subject relationship with the message",]:
            return await self.get_web_browser(query)

        autogen.agentchat.register_function(
            web_browser_wrapper,
            caller=self.chat_agent,
            executor=self.agent_executor,
            name="web_browser",
            description="Find, Search and extract any information from the internet",
        )
        autogen.agentchat.register_function(
            image_generator_wrapper,
            caller=self.chat_agent,
            executor=self.agent_executor,
            name="image_generator",
            # description="This tool will be used to write any sort of python code.",
            description="This tool will be used to generate images",
        )

    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        try:
            self._check_cancellation()

            messages = groupchat.messages

            if len(messages) == 1 or last_speaker.name == "chat_manager":
                return groupchat.agent_by_name("chat_agent")
            if last_speaker.name == "chat_agent" and messages[-1].get('content', None) in [None, "", 'None']:
                return groupchat.agent_by_name("agent_executor")
            if last_speaker.name == "agent_executor":
                return groupchat.agent_by_name("chat_agent")
            return None
        except asyncio.CancelledError:
            raise

    def get_agents(self):
        self.chat_agent = self.get_chat_agent()
        self.agent_executor = self.get_agent_executor()
        return [
            self.chat_agent,
            self.agent_executor,
        ]

    def get_chat_manager(self):
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
            chat_id=self.chat_id
        )
        return self.manager, self.groupchat
