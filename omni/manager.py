import autogen
from typing import List, Dict, Any, Union
from omni import prompts
from configs.llm_configs_manager import LLMConfigManager
from configs.settings import settings
from simplegmail import Gmail
from configs.settings import settings
import pandas as pd
import autogen
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager
from autogen import config_list_from_json
import os,json
from typing import List, Dict, Any
from typing import Annotated, List, Dict
from datetime import datetime
from autogen.agentchat.agent import Agent
from autogen import register_function
# from omni_newton import cs_groupchat,cs_manager
# from capabilities.file_finder.controller import ff_groupchat, ff_manager
from capabilities.file_finder.manager import FileFinder
#from capabilities.image_generator.controller import ig_groupchat, ig_manager
from capabilities.image_generator.manager import ImageGenerator
# from omni_birbal import birbal_groupchat, birbal_manager
# from capabilities.python_developer.controller import pcw_groupchat, pcw_manager
from capabilities.python_developer.manager import PythonDeveloper
from capabilities.email_manager.manager import EmailManager
# from omni_dashboarding import dash_groupchat, dash_manager
from capabilities.browser_manager.manager import BrowserManager
from configs.llm_configs_manager import LLMConfigManager
from omni import prompts
from loguru import logger
from utilities.storage import update_db
import asyncio
from string import Template
from typing import List, Optional,Dict,Any
today_date = datetime.now()
from omni.response_format import AgentSelectionResponse , QuestionClassification , PlannerResponse , CapabilityRoutingResponse, AgentCallerResponse
from utilities.custom_manager import create_capability_chat
import uuid
from omni.memory import OmniMemory
import aioconsole
# Load configuration
config_list_anth = LLMConfigManager.get_config("claude-3-7-sonnet-20250219")
llm_config_reason = LLMConfigManager.get_config("o3-mini-reason-high")
llm_config = LLMConfigManager.get_config("deepseek")
llm_config_mini_planner = LLMConfigManager.get_config("gpt_4_1_mini")
llm_config_mini_planner["response_format"] = PlannerResponse
llm_config_mini_aligner = LLMConfigManager.get_config("gpt_4_1_mini")
llm_config_mini_aligner["response_format"] = AgentSelectionResponse
llm_config_mini_router = LLMConfigManager.get_config("gpt_4_1_mini")
llm_config_mini_router["response_format"] = CapabilityRoutingResponse

llm_config_question_class = LLMConfigManager.get_config("gpt_4_1_mini")
llm_config_question_class["response_format"] = QuestionClassification

llm_config_mini = LLMConfigManager.get_config("gpt_4_1_mini")

llm_config_agent_caller = LLMConfigManager.get_config("gpt_4_1_mini")
llm_config_agent_caller["response_format"] = AgentCallerResponse
from managers.connection import WebSocketManager
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from dependencies import get_websocket_manager

class OmniGroupChatManager(autogen.GroupChatManager):
    def __init__(self, groupchat, llm_config, memory: OmniMemory, human_input_mode: str = "NEVER", chat_id: str = None, queue: Optional[asyncio.Queue] = None):
        super().__init__(groupchat=groupchat, llm_config=llm_config, human_input_mode=human_input_mode)
        self.chat_id = chat_id
        self.memory = memory
        
    async def send_websocket(self, message):
        ws_manager = await get_websocket_manager()
        await ws_manager.send_chat_message(session_id=self.chat_id, content=message, source="OMNI")
        return
        
    def generate_reply(
        self,
        messages: Optional[list[dict[str, Any]]] = None,
        sender: Optional["Agent"] = None,
        **kwargs: Any,
    ) -> Union[str, dict[str, Any], None]:
        """Generate a reply based on the received messages.

        Args:
            messages (list[dict[str, Any]]): a list of messages received from other agents.
                The messages are dictionaries that are JSON-serializable and
                follows the OpenAI's ChatCompletion schema.
            sender: sender of an Agent instance.
            **kwargs: Additional keyword arguments.

        Returns:
            str or dict or None: the generated reply. If None, no reply is generated.
        """
        super().generate_reply(messages, sender,**kwargs)

    async def a_generate_reply(
        self,
        messages: Optional[list[dict[str, Any]]] = None,
        sender: Optional["Agent"] = None,
        **kwargs: Any,
    ) -> Union[str, dict[str, Any], None]:
        """(Async) Generate a reply based on the received messages.

        Args:
            messages (list[dict[str, Any]]): a list of messages received from other agents.
                The messages are dictionaries that are JSON-serializable and
                follows the OpenAI's ChatCompletion schema.
            sender: sender of an Agent instance.
            **kwargs: Additional keyword arguments.

        Returns:
            str or dict or None: the generated reply. If None, no reply is generated.
        """
        await super().a_generate_reply(messages, sender, **kwargs)
    
    def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        db_content = {"role":"user","name":sender.name,"content":content}
        self.memory.push_main_message(db_content)
        db_content["raw_message"] = message
        asyncio.run(self.send_websocket(db_content))
        asyncio.create_task(update_db(chat_id=self.chat_id,message=db_content,capability=settings.OMNI_COLLECTION))
            
            
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
    def __init__(self,chat_id):
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

        self.agents = self.get_agents()
        self._register_functions()
        self.get_chat_manager()
        
    
    def get_last_call_id(self):
        last_speaker = self.groupchat.messages[-1]
        if last_speaker.get("name") == "agent_caller":
            tool_calls = last_speaker.get("tool_calls")
            result = {item['function']['name']: item['id'] for item in tool_calls}
            return result
        return None
        
    async def get_image_generator(self, query: Annotated[str, "The detailed image generation prompt"]):
        call_id = self.get_last_call_id().get("image_generator")
        capability_id = str(uuid.uuid4())
        await create_capability_chat(chat_id=self.chat_id,call_id=call_id,capability=settings.IMAGE_GENERATOR_COLLECTION, capability_id=capability_id)
        image_generator = ImageGenerator(chat_id=self.chat_id, call_id=call_id, capability_id=capability_id)
        response = image_generator.manager.initiate_chat(image_generator.manager, message=query)
        messages = image_generator.groupchat.messages
        for msg in reversed(messages):
            if msg.get("name") == "process_completion":
                # add_entry("image_generator", msg["content"])
                return msg["content"]
        # add_entry("image_generator", "No completion message found")
        return f"The image generation process got into a runtime error, please check the logs for more details. . Process that encountered the error > : {query}"


    async def get_web_browser(self, query: Annotated[str,"The complete search query with all the details like subject relationship with the message",],) -> Annotated[str,"The complete search query with all the details like subject relationship with the message",]:
        call_id = self.get_last_call_id().get("web_browser")
        capability_id = str(uuid.uuid4())
        result = await create_capability_chat(chat_id=self.chat_id,call_id=call_id,capability=settings.BROWSER_COLLECTION, capability_id=capability_id)
        browser_manager = BrowserManager(chat_id=self.chat_id, call_id=call_id, capability_id=capability_id, omni_memory=self.memory)
        # messages = self.memory.pull_recent_from_chat_manager()
        # if self.memory.get_last_capability():
        #     last_content = next((d['content'] for d in self.memory.pull_last_capability_messages() if d.get('name') == 'process_completion'), None)
        #     if last_content:
        #         messages.append({"role":"user","name":"chat_manager","content":last_content})
        # last_agent, last_message = browser_manager.manager.resume(messages=messages)
        response = browser_manager.manager.initiate_chat(browser_manager.manager, message=query, clear_history=False)
        # response = browser_manager.initiate_chat(browser_manager, message=query)
        messages = browser_manager.groupchat.messages
        for msg in reversed(messages):
            if msg.get("name") == "process_completion":
                # add_entry("Web_browser", msg["content"])
                return msg["content"]
        # add_entry("Web_browser", "No completion message found")
        return f"The web browsing process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"


    async def get_python_coder(self, query: Annotated[str,"The complete  query with all the details, on what work we have to do and what we have to return for other agents to work on",],) -> Annotated[str, "The results"]:
        call_id = self.get_last_call_id().get("python_coder")
        capability_id = str(uuid.uuid4())
        await create_capability_chat(chat_id=self.chat_id, call_id=call_id, capability=settings.PYTHON_DEV_COLLECTION, capability_id=capability_id)
        python_dev= PythonDeveloper(chat_id=self.chat_id, call_id=call_id, capability_id=capability_id, omni_memory=self.memory)
        messages = self.memory.pull_recent_from_chat_manager()
        if self.memory.get_last_capability():
            last_content = next((d['content'] for d in self.memory.pull_last_capability_messages() if d.get('name') == 'process_completion'), None)
            if last_content:
                messages.append({"role":"user","name":"chat_manager","content":last_content})
        last_agent, last_message = python_dev.manager.resume(messages=messages)
        response = python_dev.manager.initiate_chat(python_dev.manager, message=query, clear_history=False)
        # Get messages directly from cs_groupchat
        messages = python_dev.groupchat.messages
        # Find the last process_completion message
        for msg in reversed(messages):
            if msg.get("name") == "process_completion_agent":
                # add_entry("python_coder", msg["content"])
                return msg["content"]
        # add_entry("python_coder", "No completion message found")
        return f"The python coding process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"


    async def get_email_sender(self, query: Annotated[str, "The complete user query"]) -> dict:
        call_id = self.get_last_call_id().get("email_sender")
        capability_id = str(uuid.uuid4())
        await create_capability_chat(chat_id=self.chat_id,call_id=call_id,capability=settings.EMAIL_COLLECTION, capability_id=capability_id)
        emailer = EmailManager(chat_id=self.chat_id, call_id=call_id, capability_id=capability_id, omni_memory=self.memory)
        messages = self.memory.pull_recent_from_chat_manager()
        if self.memory.get_last_capability():
            last_content = next((d['content'] for d in self.memory.pull_last_capability_messages() if d.get('name') == 'process_completion'), None)
            if last_content:
                messages.append({"role":"user","name":"chat_manager","content":last_content})
        last_agent, last_message = emailer.manager.resume(messages=messages)
        response = emailer.manager.initiate_chat(emailer.manager, message=query, clear_history=False)
        messages = emailer.groupchat.messages
        for msg in reversed(messages):
            if (
                msg.get("name") == "process_completion_agent"
            ): 
                return msg["content"]

        return f"The email sending process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"



    async def get_file_finder(self, query: Annotated[str, "The search query"]):
        call_id = self.get_last_call_id().get("file_finder")
        capability_id = str(uuid.uuid4())
        await create_capability_chat(chat_id=self.chat_id,call_id=call_id,capability=settings.FILE_FINDER_COLLECTION, capability_id=capability_id)
        file_finder = FileFinder(chat_id=self.chat_id,call_id=call_id, capability_id=capability_id, omni_memory=self.memory)
        # messages = self.memory.pull_recent_from_chat_manager()
        # if self.memory.get_last_capability():
        #     last_content = next((d['content'] for d in self.memory.pull_last_capability_messages() if d.get('name') == 'process_completion'), None)
        #     if last_content:
        #         messages.append({"role":"user","name":"chat_manager","content":last_content})
        # last_agent, last_message = file_finder.manager.resume(messages=messages)
        response = file_finder.manager.initiate_chat(file_finder.manager, message=query, clear_history=False)
        messages = file_finder.groupchat.messages
        for msg in reversed(messages):
            if msg.get("name") == "process_completion":
                # add_entry("file_finder", msg["content"])
                return msg["content"]
        # add_entry("email_sender", "No completion message found")
        return f"The file finder  process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"

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
            llm_config=llm_config_agent_caller,
            #system_message=prompts.agent_caller,
        )

    def get_agent_executor(self):
        return autogen.UserProxyAgent(
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
