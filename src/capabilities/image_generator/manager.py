import asyncio
import os
import time
from typing import Annotated, Any

import aiofiles
import autogen
import httpx
from autogen import AssistantAgent, UserProxyAgent
from autogen.agentchat.agent import Agent
from loguru import logger
from together import Together

from src.capabilities.image_generator import prompts
from src.capabilities.image_generator.response_format import ProcessCompletionResponse
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.system_ai_config import GroupchatConfigurationManager
from src.utilities.async_errors import (
    AsyncErrorCode,
    create_error,
    handle_async_errors,
)
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
        self.llm_config = LLMConfigManager.get_config("default")
        image_llm_config = LLMConfigManager.get_config("image_together_llm")
        self.image_llm_config = image_llm_config.get("config_list", [])[0]
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

    @handle_async_errors("image_generation", AsyncErrorCode.HTTP_DOWNLOAD_FAILED)
    async def flux_image_generator(
        self,
        prompt: Annotated[str, "The image generation prompt"],
        filename: Annotated[str, "The filename to save the image as"],
        width: Annotated[int, "Width of the image"] = 1792,
        height: Annotated[int, "Height of the image"] = 1792,
    ):
        """Generate an image using the Flux model.

        Uses async HTTP client and async file I/O for non-blocking operations.

        Args:
            prompt: The image generation prompt
            filename: The filename to save the image as
            width: Width of the image (default: 1792)
            height: Height of the image (default: 1792)

        Returns:
            Success message with file path or error details
        """
        try:
            client = Together(api_key=self.image_llm_config.get("api_key"))
            response = client.images.generate(
                prompt=prompt,
                model=self.image_llm_config.get("model"),
                width=width,
                height=height,
                steps=40,
                guidance_scale=18,
            )

            # Download the image using async HTTP client (non-blocking)
            image_url = response.data[0].url

            async with httpx.AsyncClient(timeout=300.0) as http_client:
                image_response = await http_client.get(image_url)
                image_response.raise_for_status()

            filename = (
                filename
                if filename
                else f"{self.context.capability_id}_{int(time.time())}.jpg"
            )

            file_path = os.path.join(self.image_dir, filename)

            # Save the image using async file I/O (non-blocking)
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(image_response.content)

            return f"Image successfully generated and saved at {file_path}"

        except httpx.TimeoutException as e:
            error = create_error(
                AsyncErrorCode.OPERATION_TIMEOUT,
                "image_download",
                user_message="Image download timed out. Please try again.",
                technical_message=str(e),
                context={"prompt": prompt[:100], "timeout": 300},
            )
            logger.error(f"[{error.code.value}] Image download timeout: {e}")
            return {
                "status": "error",
                "error_code": error.code.value,
                "message": error.user_message,
                "support_reference": f"Contact support with code: {error.code.value}",
            }
        except httpx.HTTPStatusError as e:
            error = create_error(
                AsyncErrorCode.HTTP_DOWNLOAD_FAILED,
                "image_download",
                user_message="Failed to download generated image. Please try again.",
                technical_message=f"HTTP {e.response.status_code}: {str(e)}",
                context={"prompt": prompt[:100], "status_code": e.response.status_code},
            )
            logger.error(f"[{error.code.value}] Image download failed: {e}")
            return {
                "status": "error",
                "error_code": error.code.value,
                "message": error.user_message,
                "support_reference": f"Contact support with code: {error.code.value}",
            }
        except OSError as e:
            error = create_error(
                AsyncErrorCode.FILE_WRITE_FAILED,
                "image_save",
                user_message="Failed to save the image. Please check storage permissions.",
                technical_message=str(e),
                context={"filename": filename},
            )
            logger.error(f"[{error.code.value}] Image save failed: {e}")
            return {
                "status": "error",
                "error_code": error.code.value,
                "message": error.user_message,
                "support_reference": f"Contact support with code: {error.code.value}",
            }
        except Exception as e:
            error = create_error(
                AsyncErrorCode.TASK_EXECUTION_FAILED,
                "image_generation",
                user_message="Image generation failed. Please try again.",
                technical_message=str(e),
                context={"prompt": prompt[:100] if prompt else "N/A"},
            )
            logger.error(f"[{error.code.value}] Image generation error: {e}")
            return {
                "status": "error",
                "error_code": error.code.value,
                "message": error.user_message,
                "support_reference": f"Contact support with code: {error.code.value}",
            }

    def _register_functions(self):
        """Register image generation functions with the agents."""
        # Wrapper functions before registering to agents

        async def flux_image_generator_wrapper(
            query: Annotated[str, "The image generation prompt"],
            filename: Annotated[str, "The filename to save the image as"],
            width: Annotated[int, "Width of the image"] = 1792,
            height: Annotated[int, "Height of the image"] = 1792,
        ):
            return await self.flux_image_generator(
                prompt=query, filename=filename, width=width, height=height
            )

        autogen.agentchat.register_function(
            flux_image_generator_wrapper,
            caller=self.image_generator_caller,
            executor=self.image_generator,
            name="flux_image_generator",
            description="This tool will be used to generate images based on the information.",
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
            # file_path_provided = any("file path" in msg["content"].lower() for msg in messages)

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
