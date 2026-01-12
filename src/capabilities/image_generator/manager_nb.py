import asyncio
import os
import time
from typing import Annotated, Any, Optional

import autogen
import google.generativeai as genai
from autogen import AssistantAgent, UserProxyAgent
from autogen.agentchat.agent import Agent
from loguru import logger
from PIL import Image

from src.capabilities.image_generator import prompts
from src.capabilities.image_generator.response_format import ProcessCompletionResponse
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.system_ai_config import GroupchatConfigurationManager
from src.utilities.custom_manager import ChatContext, CustomGroupChatManager
from src.utilities.storage import ensure_path


class ImageGenerator:
    """Manager for image generation capabilities using AI models."""

    def __init__(self, context: ChatContext):
        self.context = context
        self.groupchat_config = (
            GroupchatConfigurationManager.get_instance().get_groupchat_configuration(
                "image_generator"
            )
        )
        self.image_dir = ensure_path(os.path.join(self.context.chat_dir, "images"))
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        image_llm_config = LLMConfigManager.get_config("image_gemini_llm")
        self.image_llm_config = image_llm_config.get("config_list", [])[0]
        
        # Configure Gemini API
        genai.configure(api_key=self.image_llm_config.get("api_key"))
        self.client = genai.Client()
        
        self.agents = self.get_agents()
        self._register_functions()
        self.get_chat_manager()

    def _check_cancellation(self):
        """Check if the chat should be cancelled."""
        if (
            self.context.cancellation_token
            and self.context.cancellation_token.is_cancelled()
        ):
            raise asyncio.CancelledError(
                f"Group chat cancelled for session {self.context.chat_id}"
            )
        
    def flux_image_generator(
        self,
        prompt: Annotated[str, "The image generation prompt"],
        filename: Annotated[str, "The filename to save the image as"],
        source_image_path: Annotated[Optional[str], "Optional path to source image for image-to-image generation"] = None,
    ):
        """
        Generate an image using Google Gemini's image generation model (nano banana).
        
        Args:
            prompt: The image generation prompt
            filename: The filename to save the image as
            source_image_path: Optional path to source image for image-to-image generation
            
        Returns:
            str: Success or error message
        """

        try:
            # Prepare the content for the API call
            contents = []
            
            # If source image is provided, add it for image-to-image generation
            if source_image_path and os.path.exists(source_image_path):
                logger.info(f"Using source image from {source_image_path} for image-to-image generation")
                
                # Load the source image
                source_image = Image.open(source_image_path)
                
                # Add both the image and the prompt
                contents = [
                    source_image,
                    f"Transform this image: {prompt}"
                ]
            else:
                # Text-to-image generation
                contents = [prompt]
            
            # Get the model name from config or use default
            model_name = self.image_llm_config.get("model")
            
            logger.info(f"Generating image with model: {model_name}")
            
            # Generate the image using Gemini
            response = self.client.models.generate_content(
                model=model_name,
                contents=contents,
            )
            
            # Check if image was generated
            if not response.candidates or not response.candidates[0].content.parts:
                raise ValueError("No image generated in response")
            
            # Extract the image from the response
            # Gemini returns the image in the parts of the response
            image_part = None
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    image_part = part.inline_data
                    break
            
            if not image_part:
                raise ValueError("No image data found in response")
            
            # Generate filename if not provided
            filename = (
                filename
                if filename
                else f"{self.context.capability_id}_{int(time.time())}.png"
            )
            
            # Ensure filename has correct extension
            if not filename.endswith(('.png', '.jpg', '.jpeg')):
                filename += '.png'
            
            file_path = os.path.join(self.image_dir, filename)
            
            # Save the image
            with open(file_path, "wb") as f:
                f.write(image_part.data)
            
            generation_type = "image-to-image" if source_image_path else "text-to-image"
            logger.info(f"Image successfully generated ({generation_type}) and saved at {file_path}")
            
            return f"Image successfully generated ({generation_type}) and saved at {file_path}"

        except FileNotFoundError as e:
            error_message = f"Source image file not found: {str(e)}"
            logger.error(error_message)
            return error_message
        except ValueError as e:
            error_message = f"Image generation error: {str(e)}"
            logger.error(error_message)
            return error_message
        except Exception as e:
            error_message = f"Error generating image: {str(e)}"
            logger.error(error_message)
            return error_message
        
    def _register_functions(self):
        """Register image generation functions with the agents."""
        
        def flux_image_generator_wrapper(
            query: Annotated[str, "The image generation prompt"],
            filename: Annotated[str, "The filename to save the image as"],
            source_image_path: Annotated[Optional[str], "Optional path to source image for image-to-image generation"] = None,
        ):
            return self.flux_image_generator(query, filename, source_image_path)

        autogen.agentchat.register_function(
            flux_image_generator_wrapper,
            caller=self.image_generator_caller,
            executor=self.image_generator,
            name="flux_image_generator",
            description="Generate images using Google Gemini (nano banana). Supports both text-to-image generation and image-to-image transformation. Provide source_image_path parameter for image-to-image generation.",
        )

    def get_context_keeper(self):
        """Get the context keeper agent."""
        return autogen.AssistantAgent(name="context_keeper", llm_config=self.llm_config)
    
    def get_user_intent_agent(self):
        """Get the user intent classification agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("user_intent").llm_config
            or "default"
        )
        llm_user_intent = LLMConfigManager.get_config(llm_config_name)
        return AssistantAgent(
            name="user_intent",
            system_message=prompts.user_intent,
            llm_config=llm_user_intent,
        )
    
    def get_image_prompt_generator_agent(self):
        """Get the image prompt generator agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("image_prompt_generator").llm_config
            or "default"
        )
        llm_image_prompt_generator = LLMConfigManager.get_config(llm_config_name)
        return AssistantAgent(
            name="image_prompt_generator",
            system_message=prompts.image_prompt_generator,
            llm_config=llm_image_prompt_generator,
        )
    
    def get_image_generator_caller_agent(self):
        """Get the image generator caller agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("image_generator_caller").llm_config
            or "default"
        )
        llm_image_generator_caller = LLMConfigManager.get_config(llm_config_name)
        return AssistantAgent(
            name="image_generator_caller",
            # system_message=prompts.image_generator_caller,
            llm_config=llm_image_generator_caller,
        )
    
    def get_image_generator_agent(self):
        """Get the image generator executor agent."""
        return UserProxyAgent(
            name="image_generator",
            human_input_mode="NEVER",
            code_execution_config=False,
            llm_config=self.llm_config,
        )

    def get_process_completion_agent(self):
        """Get the process completion agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("process_completion").llm_config
            or "default"
        )
        llm_process_completion = LLMConfigManager.get_config(llm_config_name)
        llm_process_completion["response_format"] = ProcessCompletionResponse
        return AssistantAgent(
            name="process_completion",
            llm_config=llm_process_completion,
            description="Let group manager know that the process is completed. ",
            system_message=prompts.process_completion,
        )
    
    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        """Select the next speaker in the group chat based on conversation flow."""
        try:
            self._check_cancellation()

            messages = groupchat.messages

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

        except asyncio.CancelledError:
            logger.info(
                f"Speaker selection cancelled for session {self.context.chat_id}"
            )
            # Return process_completion to gracefully end the chat
            raise

    def get_agents(self) -> list[Agent]:
        """Initialize and return all agents for the image generation workflow."""
        self.user_intent = self.get_user_intent_agent()
        self.context_keeper = self.get_context_keeper()
        self.image_prompt_generator = self.get_image_prompt_generator_agent()
        self.image_generator_caller = self.get_image_generator_caller_agent()
        self.image_generator = self.get_image_generator_agent()
        self.process_completion = self.get_process_completion_agent()
        return [
            self.user_intent,
            self.context_keeper,
            self.image_prompt_generator,
            self.image_generator_caller,
            self.image_generator,
            self.process_completion,
        ]

    def get_chat_manager(self):
        """Initialize and return the group chat manager."""
        self.groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self.custom_speaker_selection_func,
            max_round=500,
        )
        self.manager = CustomGroupChatManager(
            groupchat=self.groupchat,
            llm_config=self.llm_config,
            chat_context=self.context,
            human_input_mode="ALWAYS",
        )
        return self.groupchat, self.manager
