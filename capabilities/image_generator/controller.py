import autogen
from pathlib import Path
import os
import json
from datetime import datetime
from autogen import register_function
from autogen.agentchat.agent import Agent
from typing import List, Dict, Any
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager
from typing import List, Dict, Optional, Union
from typing import Annotated, List, Dict
from utilities.external_memory import get_last_entry, get_all_messages
from PIL import Image
import httpx
import time
from io import BytesIO
import base64
from capabilities.image_generator import prompts
from configs.settings import settings
from configs.llm_configs_manager import LLMConfigManager
config_list_anth = LLMConfigManager.get_config("claude-3-7-sonnet-20250219")
llm_config_reason = LLMConfigManager.get_config("o3-mini-reason-high")
llm_config = LLMConfigManager.get_config("gpt4o")
model_id = "4w59rxjq"
baseten_api_key = "IPY0OlMw.q04XmZdd8TgEv3hgDawsZHGuiLkehyuc"


file_location = os.path.join(settings.ROOT_DIR, "images")
os.makedirs(file_location, exist_ok=True)






def flux_image_generator(prompt: Annotated[str, "The image generation prompt"]):
    model_id = "4w59rxjq"
    baseten_api_key = "IPY0OlMw.q04XmZdd8TgEv3hgDawsZHGuiLkehyuc"
    data = {
        "prompt": prompt
        }

    try:
        res = httpx.post(
            f"https://model-{model_id}.api.baseten.co/production/predict",
            headers={"Authorization": f"Api-Key {baseten_api_key}"},
            json=data,
            timeout=300.0
            )

        res_json = res.json()
        output = res_json.get("data")

        if not output:
            return "Error: No image data received from the model."

        img = Image.open(BytesIO(base64.b64decode(output)))
        timestamp = int(time.time())
        filename = f"/Users/user/Library/Application Support/omni-mac-app-electron/image/generated_image_{timestamp}.jpg"
        img.save(filename)
        return f"Image successfully generated and saved at {filename}"

    except Exception as e:
        error_message = f"Error generating image: {str(e)}"
        return error_message


user_intent = AssistantAgent(
    name="user_intent",
    description="""intent understanding""",
    system_message=prompts.user_intent.format(get_last_entry=get_last_entry,get_all_messages=get_all_messages),
    llm_config=llm_config
    )

image_prompt_generator = AssistantAgent(
    name="image_prompt_generator",
    description="""prompt creator""",
    system_message=prompts.image_prompt_generator,

    llm_config=llm_config
    )

image_generator_caller = AssistantAgent(
        name="image_generator_caller",
        system_message = prompts.image_generator_caller,
        llm_config=llm_config
)
    

image_generator = UserProxyAgent(
    name="image_generator",
    human_input_mode="NEVER",
    code_execution_config=False,
    llm_config=llm_config,
    )

process_completion = AssistantAgent(
    name="process_completion",
    llm_config=llm_config,
    description="Let group manager know that the process is completed. ",
    system_message=prompts.process_completion
    )




def custom_speaker_selection_func(last_speaker: Any, groupchat: Any) -> Any:
    messages = groupchat.messages
    #file_path_provided = any("file path" in msg["content"].lower() for msg in messages)

    if len(messages) == 1:
        return groupchat.agent_by_name("user_intent")
    if last_speaker.name == "user_intent":
        return groupchat.agent_by_name("image_prompt_generator")
    if last_speaker.name == "image_prompt_generator":
        return groupchat.agent_by_name("image_generator_caller")
    if last_speaker.name == "image_generator_caller":
        return groupchat.agent_by_name("image_generator")
    if last_speaker.name == "image_generator":
        if "error".lower() in messages[-1]["content"]:
            return groupchat.agent_by_name("image_prompt_generator")
        else:
            return groupchat.agent_by_name("process_completion")
    return None



register_function(flux_image_generator,
    caller=image_prompt_generator,
    executor=image_generator,
    name="image_generator",
    description="This tool will be used to generate images based on the information.",
    )

ig_groupchat = GroupChat([user_intent,
                          image_prompt_generator,
                          image_generator_caller,
                          image_generator,
                          process_completion,
                           ],
                          speaker_selection_method=custom_speaker_selection_func,
                           messages=[],
                           max_round=20
                           )

ig_manager = GroupChatManager(ig_groupchat, llm_config=llm_config)

