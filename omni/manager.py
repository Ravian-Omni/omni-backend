import autogen
from typing import List, Dict, Any, Union
from omni import prompts
from configs.llm_configs_manager import LLMConfigManager
from configs.settings import settings
from simplegmail import Gmail
from configs.settings import settings
import pandas as pd
import autogen
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager, ConversableAgent
from autogen import config_list_from_json
import os,json
from typing import List, Dict, Any
from typing import Annotated, List, Dict
from datetime import datetime
from autogen.agentchat.agent import Agent
from autogen import register_function
from capabilities.file_finder.manager import FileFinder
from capabilities.image_generator.manager import ImageGenerator
from capabilities.python_developer.manager import PythonDeveloper
from capabilities.email_manager.manager import EmailManager
from capabilities.browser_manager.manager import BrowserManager
from configs.llm_configs_manager import LLMConfigManager
from omni import prompts
from loguru import logger
from utilities.storage import update_chat_history, a_speak
import asyncio
from string import Template
from typing import List, Optional,Dict,Any
today_date = datetime.now()
from omni.response_format import AgentSelectionResponse , QuestionClassification , PlannerResponse , CapabilityRoutingResponse, AgentCallerResponse
from utilities.custom_manager import create_capability_chat
import uuid
from omni.memory import OmniMemory
from dependencies import get_websocket_manager
from omni.capability_manager import CapabilityManager, CapabilityConfig

class OmniGroupChatManager(autogen.GroupChatManager):
    """Enhanced GroupChatManager with memory, WebSocket, and voice capabilities."""
    
    def __init__(self, groupchat, llm_config, memory, chat_id: str, human_input_mode: str = "NEVER"):
        super().__init__(groupchat=groupchat, llm_config=llm_config, human_input_mode=human_input_mode)
        self.chat_id = chat_id
        self.memory = memory
        
    async def _send_websocket_message(self, message_data: dict) -> None:
        """Send message to WebSocket clients."""
        try:
            websocket_manager = await get_websocket_manager()
            await websocket_manager.send_chat_message(
                session_id=self.chat_id, 
                content=message_data, 
                source="OMNI"
            )
        except Exception as e:
            logger.error(f"WebSocket send failed for chat_id {self.chat_id}: {e}")
    
    async def _handle_voice_alert(self, agent_name: str, content: str) -> None:
        """Handle voice alerts for specific agents."""
        try:
            if agent_name == "manual_verification":
                await a_speak(content)
            elif agent_name == "process_completion_agent":
                await a_speak("Hey there! Ravian finished your task!")
        except Exception as e:
            logger.error(f"Voice alert failed for agent {agent_name}: {e}")
    
    async def _process_message_async(self, message_data: dict) -> None:
        """Process message asynchronously."""
        await self._handle_voice_alert(message_data["name"], message_data["content"])
        await self._send_websocket_message(message_data)
        await update_chat_history(self.chat_id, message_data, settings.OMNI_COLLECTION)
    
    def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
        """Override to handle received messages with enhanced processing."""
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)
        
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        message_data = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message
        }
        # Store in memory synchronously
        self.memory.push_main_message({k: message_data[k] for k in ['role', 'name', 'content']})
        
        # Process async operations
        asyncio.create_task(self._process_message_async(message_data))
            

class CustomUserProxyAgent(UserProxyAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
    def set_input_function(self, input_function):
        self.input_function = input_function
        return self.input_function
        
    
    def get_human_input(self, prompt: str) -> str:
        """Override the default input method to use websocket"""
        print(f"🔄 Waiting for user input via websocket...")
        
        # Send input request to websocket client
        # self._send_input_request(prompt)
        
        # Wait for response from websocket
        return super().get_human_input(prompt)
    
    async def a_get_human_input(self, prompt: str) -> str:
        print("🔁 Custom logic before input...")
        
        # Safely call super, assuming you have registered an async input
        # result = await super().a_get_human_input(prompt)
        return await self.input_function(prompt)
        
        # print(f"✅ Got input: {result}")
        # return await aioconsole.ainput(prompt)
    


class Omni:
    def __init__(self, chat_id: str, user_id: str = "default_user"):
        self.user_id=user_id
        self.chat_id=chat_id
        self.llm_config_mini = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.config_list_anth = LLMConfigManager.get_config("claude-3-7-sonnet-20250219")
        self.llm_config_reason = LLMConfigManager.get_config("o3-mini-reason-high")
        # self.llm_config = LLMConfigManager.get_config("deepseek")
        self.llm_config_mini_planner = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_mini_planner["response_format"] = PlannerResponse
        self.llm_config_mini_aligner = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_mini_aligner["response_format"] = AgentSelectionResponse
        self.llm_config_mini_router = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_mini_router["response_format"] = CapabilityRoutingResponse
        self.llm_config_question_class = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_question_class["response_format"] = QuestionClassification
        
        #Memory Configuration
        self.memory = OmniMemory()
        
        self.capability_manager = CapabilityManager(
            user_id=self.user_id,
            chat_id=self.chat_id,
            memory=self.memory
        )

        self.agents = self.get_agents()
        self._register_functions()
        self.get_chat_manager()
        
    
    def get_last_call_id(self):
        last_speaker = self.groupchat.messages[-1]
        if last_speaker.get("name") == "agent_caller":
            tool_calls = last_speaker.get("tool_calls")
            result = {}
            
            for index, item in enumerate(tool_calls):
                function_name = item['function']['name']
                call_info = {
                    'id': item['id'],
                    'index': index,
                    'arguments': item['function'].get('arguments', {})
                }
                
                if function_name in result:
                    result[function_name].append(call_info)
                else:
                    result[function_name] = [call_info]
            
            return result
        return None
    
    
    def find_call_id(self, capability_name: str, query: str) -> Optional[str]:
        """
        Find matching call ID for any capability
        
        Args:
            capability_name: Name of the capability (e.g., "email_sender", "file_finder")
            query: The query string to match against call arguments
            
        Returns:
            Optional[str]: The matching call ID if found, None otherwise
        """
        try:
            call_ids = self.get_last_call_id().get(capability_name, [])
            
            for item in call_ids:
                arguments_str = item.get('arguments', '')
                
                # Try to parse the arguments as JSON first
                try:
                    arguments_dict = json.loads(arguments_str)
                    # Check if query matches any value in the arguments dict
                    if isinstance(arguments_dict, dict):
                        for key, value in arguments_dict.items():
                            if isinstance(value, str) and query in value:
                                return item['id']
                    elif isinstance(arguments_dict, str) and query in arguments_dict:
                        return item['id']
                except json.JSONDecodeError:
                    # If not valid JSON, fall back to string comparison
                    if query in arguments_str:
                        return item['id']
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding {capability_name} call ID: {e}")
            return None
    
    
    async def get_image_generator(self, query: Annotated[str, "The detailed image generation prompt"]):
        call_id = self.find_call_id("image_generator", query)
        self.image_gen_config = CapabilityConfig(
            name="image_generator",
            collection=settings.IMAGE_GENERATOR_COLLECTION,
            manager_class=ImageGenerator,
            completion_agent_name="process_completion"
        )
        return await self.capability_manager.execute_capability(query, self.image_gen_config, call_id)

    async def get_web_browser(self, query: Annotated[str,"The complete search query with all the details like subject relationship with the message",],) -> Annotated[str,"The complete search query with all the details like subject relationship with the message",]:
        call_id = self.find_call_id("web_browser", query)
        self.web_browser_config = CapabilityConfig(
            name="web_browser",
            collection=settings.BROWSER_COLLECTION,
            manager_class=BrowserManager,
            completion_agent_name="process_completion",
            use_chat_messages=False 
        )
        return await self.capability_manager.execute_capability(query, self.web_browser_config, call_id)
        


    async def get_python_coder(self, query: Annotated[str,"The complete  query with all the details, on what work we have to do and what we have to return for other agents to work on",],) -> Annotated[str, "The results"]:
        call_id = self.find_call_id("python_coder", query)
        self.python_coder_config = CapabilityConfig(
            name="python_coder",
            collection=settings.PYTHON_DEV_COLLECTION,
            manager_class=PythonDeveloper,
            completion_agent_name="process_completion_agent",
            use_chat_messages=True 
        )
        return await self.capability_manager.execute_capability(query, self.python_coder_config, call_id)
       
       
    async def get_email_sender(self, query: Annotated[str, "The complete user query"]) -> dict:
        call_id = self.find_call_id("email_sender", query)
        self.email_sender_config = CapabilityConfig(
            name="email_sender",
            collection=settings.EMAIL_COLLECTION,
            manager_class=EmailManager,
            completion_agent_name="process_completion_agent",
            use_chat_messages=True 
        )
        return await self.capability_manager.execute_capability(query, self.email_sender_config, call_id)



    async def get_file_finder(self, query: Annotated[str, "The search query"]):
        call_id = self.find_call_id("file_finder", query)
        self.file_finder_config = CapabilityConfig(
            name="file_finder",
            collection=settings.FILE_FINDER_COLLECTION,
            manager_class=FileFinder,
            completion_agent_name="process_completion",
            use_chat_messages=False
        )
        return await self.capability_manager.execute_capability(query, self.file_finder_config, call_id)
        
        
    def _register_functions(self):
        
        #Wrapper functions before registring to agents
        
        async def image_generator_wrapper(query: Annotated[str, "The detailed image generation prompt"]):
            return await self.get_image_generator(query)
        
        async def web_browser_wrapper(query: Annotated[str,"The complete search query with all the details like subject relationship with the message",]) -> Annotated[str,"The complete search query with all the details like subject relationship with the message",]:
            return await self.get_web_browser(query)
        
        async def python_coder_wrapper(query: Annotated[str,"The complete search query with all the details what work we have to do and what we have to return for other agents to work on",]) -> Annotated[str, "The results"]:
            return await self.get_python_coder(query)
        
        async def email_sender_wrapper(query: Annotated[str, "The complete user query"]):
            return await self.get_email_sender(query)
        
        async def file_finder_wrapper(query: Annotated[str, "The search query"]):
            return await self.get_file_finder(query)
        
        autogen.agentchat.register_function(
            python_coder_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="python_coder",
            description="This tool will be used to write any sort of python code.",
        )

        autogen.agentchat.register_function(
            email_sender_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="email_sender",
            description="This tool will be used to send emails as per the user's request.",
        )

        autogen.agentchat.register_function(
            file_finder_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="file_finder",
            description="This tool will be used to find any file as per the user's request.",
        )


        autogen.agentchat.register_function(
            web_browser_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="web_browser",
            description="This tool will be used to search the web.",
        )

        autogen.agentchat.register_function(
            image_generator_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="image_generator",
            description="This tool will be used to generate images form textual input.",
        )
    def get_judge_question(self):
        return autogen.AssistantAgent(
            name="judge_question",
            llm_config=self.llm_config_question_class,
            system_message=prompts.judge_question #update the prompt and json output format to judge question and add to speaker selection and all the agents list
        )

    def get_conversation_agent(self):
        return autogen.AssistantAgent(
            name="conversation_agent",
            llm_config=self.llm_config,
            system_message=prompts.conversation #update the prompt and json output format to judge question
        )
  

    def get_planner(self):
        return autogen.AssistantAgent(
            name="planner_agent",
            llm_config=self.llm_config_mini_planner,
            system_message=Template(prompts.planner).substitute(today_date=today_date)
        )

    def get_get_request(self):
        return autogen.AssistantAgent(
            name="get_request",
            is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
            llm_config=self.llm_config,
            description="""This agent will get the initial request from the user""",
            system_message=prompts.get_request.format(today_date=today_date),
        )

    def get_agent_aligner(self):
        return autogen.AssistantAgent(
            name="agent_aligner",
            llm_config=self.llm_config_mini_aligner,
            description="This agent will align the whole process and will share which agent will work next. ",
            system_message=prompts.agent_aligner,
        )

    def get_agent_router(self):
        return autogen.AssistantAgent(
            name="agent_router",
            llm_config=self.llm_config_mini_router,
            description="""From the initial information route to the capability which will solve the user's question.""",
            system_message=prompts.agent_router,
        )

    def get_agent_caller(self):
        return autogen.AssistantAgent(
            name="agent_caller",
            llm_config=self.llm_config_mini,
            #system_message=prompts.agent_caller,
        )

    def get_agent_executor(self):
        return UserProxyAgent(
            "agent_executor",
            human_input_mode="NEVER",
            #description="""This agent will execute the function which are group chat on their own""",
            code_execution_config=False,
            system_message=prompts.agent_executor.format(today_date=today_date),
            #is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
        )

    def get_problem_status_checker(self):
        return autogen.AssistantAgent(
            name="problem_status_checker",
            llm_config=self.llm_config,
            description="""call this agent to check if the Task specified by the user has been completed""",
            system_message=prompts.prob_status_checker,
        )
    
    def get_manual_verification(self):
        return autogen.AssistantAgent(
            name="manual_verification",
            llm_config=self.llm_config_mini,
            system_message="Ask the question to the user and wait for the response. " 
        )

    def get_user_input(self):
        return CustomUserProxyAgent(
            name="user_input",
            llm_config=self.llm_config,
            default_auto_reply="Awaiting for manual verification",
            human_input_mode="ALWAYS",
            code_execution_config=False,
            system_message=prompts.manual_verification,
        )

    def get_process_completion(self):
        return autogen.AssistantAgent(
            name="process_completion_agent",
            llm_config=self.llm_config,
            system_message=prompts.process_completion,
        )

    def get_questions_generator(self):
        return autogen.AssistantAgent(
            "questions_generator",
            is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
            llm_config=self.llm_config,
            system_message=prompts.questions_generator.format(today_date=today_date),
        )
    # dynamic, query classification and agent selection  conditional chat routing for task agent and manual verification
    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        messages = groupchat.messages
        if len(messages) == 1:
        #judge a question and understand if the question is a task or  general conversation
                return groupchat.agent_by_name("judge_question")
        if last_speaker.name in ["judge_question"]:
            if "task_oriented" in messages[-1]["content"]:
        #if it is a task oriented question then route to planner agent
                return groupchat.agent_by_name("planner_agent")
        #if it is a general conversation then route to conversation agent
            if "conversation" in messages[-1]["content"]:
                return groupchat.agent_by_name("conversation_agent")

        #Agent Aligner will align the process and will route to the next agent    
        if last_speaker.name == "agent_aligner":
            if "agent_router" in messages[-1]["content"]:
                return groupchat.agent_by_name("agent_router")
            elif "manual_verification" in messages[-1]["content"]:
                return groupchat.agent_by_name("manual_verification")
            elif "process_completion" in messages[-1]["content"]:
                return groupchat.agent_by_name("process_completion_agent")
            

        # inner loop planner agent will report back to aligner agent
        if last_speaker.name in ["planner_agent"]:
            return groupchat.agent_by_name("agent_aligner")
        
        # inner loop manual verification agent will report back to aligner agent
        if last_speaker.name in ["manual_verification"]:
            return groupchat.agent_by_name("user_input")
        if last_speaker.name in ["user_input"]:
            return groupchat.agent_by_name("agent_aligner")
        
        # how the sequential processess will get called
        if last_speaker.name == "agent_router":
            return groupchat.agent_by_name("agent_caller")
        if last_speaker.name == "agent_caller":
            return groupchat.agent_by_name("agent_executor")
        if last_speaker.name == "agent_executor":
            return groupchat.agent_by_name("planner_agent")
        if last_speaker.name == "chat_manager":
            return groupchat.agent_by_name("judge_question")

        return None

    def get_agents(self):
        self.judge_question = self.get_judge_question()
        self.conversation_agent = self.get_conversation_agent()
        self.planner = self.get_planner()
        self.get_request = self.get_get_request()
        self.agent_aligner = self.get_agent_aligner()
        self.agent_router = self.get_agent_router()
        self.agent_caller = self.get_agent_caller()
        self.agent_executor = self.get_agent_executor()
        self.problem_status_checker = self.get_problem_status_checker()
        self.manual_verification = self.get_manual_verification()
        self.user_input = self.get_user_input()
        self.process_completion = self.get_process_completion()
        self.questions_generator = self.get_questions_generator()
        return [
            self.judge_question,
            self.conversation_agent,
            self.planner,
            self.get_request,
            self.agent_aligner,
            self.agent_router,
            self.agent_caller,
            self.agent_executor,
            self.problem_status_checker,
            self.manual_verification,
            self.user_input,
            self.process_completion,
            self.questions_generator
        ]

    def get_chat_manager(self):
        self.groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self.custom_speaker_selection_func,
            max_round=500,
        )
        self.manager = OmniGroupChatManager(
            groupchat=self.groupchat,
            llm_config=self.llm_config,
            memory=self.memory,
            human_input_mode="ALWAYS",
            chat_id=self.chat_id
        )
        return self.manager, self.groupchat
