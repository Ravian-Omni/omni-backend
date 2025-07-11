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
from PIL import Image
import httpx
import time
from io import BytesIO
import base64
from capabilities.image_generator import prompts
from configs.settings import settings
from configs.llm_configs_manager import LLMConfigManager
from utilities.custom_manager import CustomGroupChatManager
from utilities.storage import ensure_path
from capabilities.image_generator.response_format import image_data

import requests
from together import Together



class ImageGenerator:
    def __init__(self, chat_id, call_id, capability_id, omni_memory):
        self.chat_id = chat_id
        self.call_id = call_id
        self.capability_id = capability_id
        self.omni_memory = omni_memory
        self.image_dir = ensure_path(os.path.join(settings.ROOT_DIR, "images", self.chat_id))
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_pc = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_pc["response_format"] = image_data
        self.agents = self.get_agents()
        self._register_functions()
        self.get_chat_manager()
        
    def flux_image_generator(self, prompt: Annotated[str, "The image generation prompt"], num_images: Annotated[int, "Number of images to generate"] = 1) -> str:
        try:
            client = Together(api_key=settings.TOGETHER_API_KEY)
            response = client.images.generate(
                prompt=prompt,
                model="black-forest-labs/FLUX.1-dev",
                n=num_images,
                width=768,
                height=432,
                steps=30
            )

            # Download and save the image with the generated filename
            list_of_images = []
            for i,image in enumerate(response.data):
                image_url = image.url
                image_response = requests.get(image_url)
                filename = os.path.join(self.image_dir,f"{self.capability_id}_{i}_{int(time.time())}.jpg") # to be updated with project creation path
                with open(filename, "wb") as f:
                    f.write(image_response.content)
                list_of_images.append(filename)

                return f"Image successfully generated and saved at {list_of_images}"

        except Exception as e:
            error_message = f"Error generating image: {str(e)}"
            return error_message
        
    def _register_functions(self):
        
        #Wrapper functions before registring to agents
        
        def flux_image_generator_wrapper(query: Annotated[str, "The image generation prompt"], num_images: Annotated[int, "Number of images to generate"] = 1) -> str:
            return self.flux_image_generator(query,num_images)
        
        autogen.agentchat.register_function(
            flux_image_generator_wrapper,
            caller=self.image_generator_caller,
            executor=self.image_generator,
            name="flux_image_generator",
            description="This tool will be used to generate images based on the information.",
        )

    def get_user_intent_agent(self):
        return AssistantAgent(
            name="user_intent",
            system_message=prompts.user_intent,
            llm_config=self.llm_config
        )
    
    def get_image_prompt_generator_agent(self):
        return AssistantAgent(
            name="image_prompt_generator",
            system_message=prompts.image_prompt_generator,
            llm_config=self.llm_config
        )
    def get_image_generator_caller_agent(self):
        return AssistantAgent(
            name="image_generator_caller",
            #system_message=prompts.image_generator_caller,
            llm_config=self.llm_config
        )
    def get_image_generator_agent(self):
        return UserProxyAgent(
            name="image_generator",
            human_input_mode="NEVER",
            code_execution_config=False,
            llm_config=self.llm_config,
        )
    
    def get_process_completion_agent(self):
        return AssistantAgent(
            name="process_completion",
            llm_config=self.llm_config_pc, #llm_config_pc. llm_config
            description="Let group manager know that the process is completed. ",
            system_message=prompts.process_completion
        )



    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        messages = groupchat.messages
        #file_path_provided = any("file path" in msg["content"].lower() for msg in messages)

        if len(messages) == 1 or last_speaker.name == "chat_manager":
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



    def get_agents(self) -> List[Agent]:
        self.user_intent = self.get_user_intent_agent()
        self.image_prompt_generator = self.get_image_prompt_generator_agent()
        self.image_generator_caller = self.get_image_generator_caller_agent()
        self.image_generator = self.get_image_generator_agent()
        self.process_completion = self.get_process_completion_agent()
        return [
            self.user_intent,
            self.image_prompt_generator,
            self.image_generator_caller,
            self.image_generator,
            self.process_completion
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
            omni_memory=self.omni_memory,
            capability_name=settings.IMAGE_GENERATOR_COLLECTION,
            capability_id=self.capability_id,
            chat_id=self.chat_id,
            call_id=self.call_id,
            human_input_mode="ALWAYS"
        )
        return  self.groupchat , self.manager