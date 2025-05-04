import os
from configs.settings import settings
from langchain_anthropic import ChatAnthropic
import nest_asyncio
# Default to ./results, but allow override via env var
results_dir = os.path.join(settings.ROOT_DIR, "browser","results")
# results_dir = os.environ.get("RESULTS_PATH", "./results")
os.makedirs(results_dir, exist_ok=True)

import json
from datetime import datetime
from autogen import config_list_from_json
from typing import List, Dict, Any
from autogen import (
    AssistantAgent,
    UserProxyAgent,
    GroupChat,
    GroupChatManager,
    register_function,
)

from langchain_openai import ChatOpenAI

from browser_use import Agent, Browser, BrowserConfig, Controller, ActionResult
from browser_use.browser.context import BrowserContextConfig
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
from capabilities.browser_manager import prompts
from utilities.external_memory import get_last_entry, get_all_messages
from configs.llm_configs_manager import LLMConfigManager

llm_config = LLMConfigManager.get_config("gpt4o")


class Post(BaseModel):
    caption: str
    post_url: str


class Posts(BaseModel):
    posts: List[Post]


# vision_llm = ChatOpenAI(model='gpt-4o-2024-08-06',
#     temperature=0.2,
#     api_key='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')
llm_config_anth = LLMConfigManager.get_config("claude-3-7-sonnet-20250219")

vision_llm = ChatAnthropic(
    model_name="claude-3-5-sonnet-20241022",
    temperature=0.1,
    api_key=settings.ANTHROPIC_API_KEY,
)

browser = Browser(
    config=BrowserConfig(
        chrome_instance_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        new_context_config=BrowserContextConfig(highlight_elements=False),
    )
)

controller = Controller(output_model=Posts)


@controller.action("Ask user for information")
def ask_human(question: str) -> str:
    answer = input(f"\n{question}\nInput: ")
    return ActionResult(extracted_content=answer)


async def browser_search(task: str) -> str:
    """Search the web for information using a browser and save results to JSON.

    Args:
        task: The task description (e.g., "Check school website for fee structure")

    Returns:
        The search results as a string

    Creates:
        A JSON file with all result details in ./results/ directory
    """
    print(f"filename path: {results_dir}")
    os.makedirs(results_dir, exist_ok=True)
    max_failures = 5
    retry_delay = 3
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(results_dir, f"search_result_{timestamp}.json")

    agent = Agent(
        task=task,
        # browser=browser, uncomment for chrome.
        max_failures=max_failures,
        retry_delay=retry_delay,
        validate_output=True,
        llm=vision_llm,
        controller=controller,
    )

    try:
        result = await agent.run()

        # IMPORTANT FIX: Call the final_result() method if it's a method
        final_result = (
            result.final_result()
            if callable(result.final_result)
            else result.final_result
        )

        result_data: Dict[str, Any] = {
            "task": task,
            "timestamp": timestamp,
            "status": "success",
            "result": final_result,
            "metadata": {
                "max_failures": max_failures,
                "retry_delay": retry_delay,
                "llm": str(vision_llm.__class__.__name__),
                "controller": str(controller.__class__.__name__),
            },
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)

        # return f'Here is the final result -->',{final_result}, 'We have saved the data in the following file --> ', {result_data}  # Ensure we return a string
        return f"Here is the final result --> {final_result}. We have saved the data in: {filename}"

    except Exception as e:
        error_data = {
            "task": task,
            "timestamp": timestamp,
            "status": "error",
            "error": str(e),
            "metadata": {"max_failures": max_failures, "retry_delay": retry_delay},
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(error_data, f, indent=2)

        return f"Error: {str(e)}"  # Return error message as string

    finally:
        await browser.close()



browser_searcher = UserProxyAgent(
    name="browser_searcher",
    llm_config=llm_config,
    code_execution_config=False,
    human_input_mode="NEVER",
)

web_browser_planner = AssistantAgent(
    name="web_browser_planner",
    llm_config=llm_config,
    system_message=prompts.planner.format(
        get_last_entry=get_last_entry, get_all_messages=get_all_messages
    ),
)

judge_question = AssistantAgent(
    name="judge_question", llm_config=llm_config, system_message=prompts.judge_question
)

easy_question = AssistantAgent(
    "easy_question",
    is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
    llm_config=llm_config,
    description="""
        When this agent will be called upon --> THIS AGENT WILL ASK QUESTIONS TO BETTER UNDERSTAND THE GIVEN SCENARIO
        What this agent will do --> This agent will ask as many question as it can to better understand the situation.
        If the agents are repeating same information and doesnt know how to proceed call this agent .
        If the situation is not clear and for better understanding we need to ask some self exploratory questions then call this agent.
        """,
    system_message=prompts.easy_question,
)

normal_question = AssistantAgent(
    "normal_question",
    is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
    llm_config=llm_config,
    description="""
        When this agent will be called upon --> THIS AGENT WILL ASK QUESTIONS TO BETTER UNDERSTAND THE GIVEN SCENARIO
        What this agent will do --> This agent will ask as many question as it can to better understand the situation.
        If the agents are repeating same information and doesnt know how to proceed call this agent .
        If the situation is not clear and for better understanding we need to ask some self exploratory questions then call this agent.
        """,
    system_message=prompts.normal_question,
)

tough_question = AssistantAgent(
    "tough_question",
    is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
    llm_config=llm_config,
    description="""
        When this agent will be called upon --> THIS AGENT WILL ASK QUESTIONS TO BETTER UNDERSTAND THE GIVEN SCENARIO
        What this agent will do --> This agent will ask as many question as it can to better understand the situation.
        If the agents are repeating same information and doesnt know how to proceed call this agent .
        If the situation is not clear and for better understanding we need to ask some self exploratory questions then call this agent.
        """,
    system_message=prompts.tough_question,
)

complex_question = AssistantAgent(
    "complex_question",
    is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
    llm_config=llm_config,
    description="""
        When this agent will be called upon --> THIS AGENT WILL ASK QUESTIONS TO BETTER UNDERSTAND THE GIVEN SCENARIO
        What this agent will do --> This agent will ask as many question as it can to better understand the situation.
        If the agents are repeating same information and doesnt know how to proceed call this agent .
        If the situation is not clear and for better understanding we need to ask some self exploratory questions then call this agent.
        """,
    system_message=prompts.complex_question,
)

broswer_reader = AssistantAgent(
    name="broswer_reader", llm_config=llm_config, system_message=prompts.browser_reader
)

process_completion = AssistantAgent(
    name="process_completion",
    llm_config=llm_config_anth,
    description="Let group manager know that the process is completed. ",
    system_message=prompts.process_completion,
)

nest_asyncio.apply()


def custom_speaker_selection_func(last_speaker: Any, groupchat: Any) -> Any:
    messages = groupchat.messages
    if len(messages) == 1:
        return groupchat.agent_by_name("web_browser_planner")
    if last_speaker.name == "web_browser_planner":
        return groupchat.agent_by_name("judge_question")
    if last_speaker.name == "judge_question":
        if "easy_question".lower() in messages[-1]["content"]:
            return groupchat.agent_by_name("easy_question")
        if "normal_question" in messages[-1]["content"]:
            return groupchat.agent_by_name("normal_question")
        if "tough_question" in messages[-1]["content"]:
            return groupchat.agent_by_name("tough_question")
        if "complex_question" in messages[-1]["content"]:
            return groupchat.agent_by_name("complex_question")
    if last_speaker.name == "easy_question":
        return groupchat.agent_by_name("broswer_reader")
    if last_speaker.name == "normal_question":
        return groupchat.agent_by_name("broswer_reader")
    if last_speaker.name == "tough_question":
        return groupchat.agent_by_name("broswer_reader")
    if last_speaker.name == "complex_question":
        return groupchat.agent_by_name("broswer_reader")
    if last_speaker.name == "broswer_reader":
        return groupchat.agent_by_name("browser_searcher")
    if last_speaker.name == "browser_searcher":
        return groupchat.agent_by_name("process_completion")
    return None


register_function(
    browser_search,
    caller=broswer_reader,
    executor=browser_searcher,
    name="web_search_tool",
    description=""" 
This tool will be used to search on the web regarding any question that user has asked, and needs to search on the web. 
TRY TO ADD AS MANY QUESTIONS AS YOU CAN TO COMBINE COMPLETE CONTEXT OF THE QUESTION.
""",
)

browser_gc = GroupChat(
    [
        browser_searcher,
        judge_question,
        web_browser_planner,
        broswer_reader,
        process_completion,
        easy_question,
        normal_question,
        tough_question,
        complex_question,
    ],
    speaker_selection_method=custom_speaker_selection_func,
    messages=[],
    max_round=500,
)

browser_manager = GroupChatManager(
    browser_gc,
    llm_config=llm_config,
)
