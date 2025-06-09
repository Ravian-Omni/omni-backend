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
from capabilities.file_finder.controller import ff_groupchat, ff_manager
from capabilities.image_generator.controller import ig_groupchat, ig_manager
# from omni_birbal import birbal_groupchat, birbal_manager
from capabilities.python_developer.controller import pcw_groupchat, pcw_manager
from capabilities.email_manager.manager import EmailManager
# from omni_dashboarding import dash_groupchat, dash_manager
from capabilities.browser_manager.controller import browser_gc, browser_manager
from configs.llm_configs_manager import LLMConfigManager
from omni import prompts
from utilities.logging import logger
from utilities.storage import omni_storage
import asyncio
from typing import List, Optional,Dict,Any
today_date = datetime.now()
from omni.response_format import AgentSelectionResponse , QuestionClassification , PlannerResponse , CapabilityRoutingResponse
# from omni.response_format import PlannerResponse
# from omni.response_format import CapabilityRoutingResponse

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


class OmniGroupChatManager(autogen.GroupChatManager):
    def __init__(self, groupchat, llm_config, human_input_mode="NEVER", queue: Optional[asyncio.Queue] = None):
        super().__init__(groupchat=groupchat, llm_config=llm_config, human_input_mode=human_input_mode)
        self.queue = queue
    
    def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        try:
            omni_storage.add_main_message(role="user",agent_name=sender.name,content=content)
            logger.debug(f"Queued from {sender.name}: {content}")
        except Exception as e:
            logger.error(f"Error {e}, could not queue message from {sender.name}: {content}")

def image_generator(query: Annotated[str, "The detailed image generation prompt"]):
    omni_storage.start_new_iteration("image_generator")
    response = ig_manager.initiate_chat(ig_manager, message=query)
    messages = ig_groupchat.messages
    for msg in reversed(messages):
        if msg.get("name") == "process_completion":
            # add_entry("image_generator", msg["content"])
            return msg["content"]
    # add_entry("image_generator", "No completion message found")
    return f"The image generation process got into a runtime error, please check the logs for more details. . Process that encountered the error > : {query}"


def web_browser(query: Annotated[str,"The complete search query with all the details like subject relationship with the message",],) -> Annotated[str,"The complete search query with all the details like subject relationship with the message",]:
    omni_storage.start_new_iteration("web_browser")
    response = browser_manager.initiate_chat(browser_manager, message=query)
    messages = browser_gc.messages
    for msg in reversed(messages):
        if msg.get("name") == "process_completion":
            # add_entry("Web_browser", msg["content"])
            return msg["content"]
    # add_entry("Web_browser", "No completion message found")
    return f"The web browsing process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"


def python_coder(query: Annotated[str,"The complete search query with all the details what work we have to do and what we have to return for other agents to work on",],) -> Annotated[str, "The results"]:
    # Initiate the chat
    omni_storage.start_new_iteration("python_code")
    response = pcw_manager.initiate_chat(pcw_manager, message=query)
    # Get messages directly from cs_groupchat
    messages = pcw_groupchat.messages
    # Find the last process_completion message
    for msg in reversed(messages):
        if msg.get("name") == "ProcessCompletion":
            # add_entry("python_coder", msg["content"])
            return msg["content"]
    # add_entry("python_coder", "No completion message found")
    return f"The python coding process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"


def email_sender(query: Annotated[str, "The complete user query"]) -> dict:
    omni_storage.start_new_iteration("email_sender")
    print("%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%")
    recent_capability = omni_storage.get_most_recently_updated_capability()
    print(recent_capability)
    print(omni_storage.get_latest_iteration_agent_messages(capability_name=recent_capability,agent_name="process_completion_agent"))
    print("%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%")
    emailer = EmailManager()
    response = emailer.manager.initiate_chat(emailer.manager, message=query)
    messages = emailer.groupchat.messages
    for msg in reversed(messages):
        if (
            msg.get("name") == "process_completion_agent"
        ):  # Make sure there's no extra space
            # add_entry("email_sender", msg["content"])
            return msg["content"]
    # add_entry("email_sender", "No completion message found")
    return f"The email sending process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"


def file_finder(query: Annotated[str, "The search query"]):
    omni_storage.start_new_iteration("file_finder")
    response = ff_manager.initiate_chat(ff_manager, message=query)
    messages = ff_groupchat.messages
    for msg in reversed(messages):
        if msg.get("name") == "process_completion":
            # add_entry("file_finder", msg["content"])
            return msg["content"]
    # add_entry("email_sender", "No completion message found")
    return f"The file finder  process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"


class Omni:
    def __init__(self):
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.config_list_anth = LLMConfigManager.get_config("claude-3-7-sonnet-20250219")
        self.llm_config_reason = LLMConfigManager.get_config("o3-mini-reason-high")
        self.llm_config = LLMConfigManager.get_config("deepseek")
        self.llm_config_mini_planner = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_mini_planner["response_format"] = PlannerResponse
        self.llm_config_mini_aligner = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_mini_aligner["response_format"] = AgentSelectionResponse
        self.llm_config_mini_router = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_mini_router["response_format"] = CapabilityRoutingResponse
        self.llm_config_question_class = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_question_class["response_format"] = QuestionClassification

        self.agents = self.get_agents()
        self.function_registration()
        self.get_chat_manager()

    def function_registration(self):
        autogen.agentchat.register_function(
            python_coder,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="python_coder",
            description="This tool will be used to write any sort of python code.",
        )

        autogen.agentchat.register_function(
            email_sender,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="email_sender",
            description="This tool will be used to send emails as per the user's request.",
        )

        autogen.agentchat.register_function(
            file_finder,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="file_finder",
            description="This tool will be used to find any file as per the user's request.",
        )


        autogen.agentchat.register_function(
            web_browser,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="web_browser",
            description="This tool will be used to search the web.",
        )

        autogen.agentchat.register_function(
            image_generator,
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
            system_message=prompts.planner
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
            llm_config=self.llm_config,
            description="""From the initial information route to the capability which will solve the user's question.""",
            system_message=prompts.agent_caller,
        )

    def get_agent_executor(self):
        return autogen.UserProxyAgent(
            "agent_executor",
            human_input_mode="NEVER",
            description="""This agent will execute the function which are group chat on their own""",
            code_execution_config=False,
            system_message=prompts.agent_executor.format(today_date=today_date),
            is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
        )

    def get_problem_status_checker(self):
        return autogen.AssistantAgent(
            name="problem_status_checker",
            llm_config=self.llm_config,
            description="""call this agent to check if the Task specified by the user has been completed""",
            system_message=prompts.prob_status_checker,
        )

    def get_manual_verification(self):
        return autogen.UserProxyAgent(
            name="manual_verification",
            llm_config=self.llm_config,
            human_input_mode="ALWAYS",
            code_execution_config=False,
            description="You will take input from user if needed for any manual intervention or verification ",
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

    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        messages = groupchat.messages
        # file_path_provided = any("file path" in msg["content"].lower() for msg in messages)
        if len(messages) == 1:
                return groupchat.agent_by_name("judge_question")
        if last_speaker.name in ["judge_question"]:
            if "task_oriented" in messages[-1]["content"]:
                return groupchat.agent_by_name("planner_agent")
            if "conversation" in messages[-1]["content"]:
                return groupchat.agent_by_name("conversation_agent")
            
        if last_speaker.name == "agent_aligner":
            if "agent_router" in messages[-1]["content"]:
                return groupchat.agent_by_name("agent_router")
            elif "manual_verification" in messages[-1]["content"]:
                return groupchat.agent_by_name("manual_verification")
            elif "process_completion" in messages[-1]["content"]:
                return groupchat.agent_by_name("process_completion_agent")

        if last_speaker.name in ["planner_agent"]:
            return groupchat.agent_by_name("agent_aligner")
        
        if last_speaker.name in ["manual_verification"]:
            return groupchat.agent_by_name("agent_aligner")

        if last_speaker.name == "agent_router":
            return groupchat.agent_by_name("agent_caller")
        if last_speaker.name == "agent_caller":
            return groupchat.agent_by_name("agent_executor")
        if last_speaker.name == "agent_executor":
            return groupchat.agent_by_name("planner_agent")
        # if last_speaker.name == "process_completion_agent":
        #     return "Process Completed"

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
            human_input_mode="ALWAYS",
        )
        return self.manager, self.groupchat
