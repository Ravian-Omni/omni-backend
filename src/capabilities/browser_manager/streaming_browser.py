import asyncio
import time
from typing import Any

from browser_use import Agent
from browser_use.agent.message_manager.utils import extract_json_from_model_output
from browser_use.agent.views import (
    ActionModel,
    ActionResult,
    AgentOutput,
    AgentStepInfo,
)
from browser_use.exceptions import LLMException
from browser_use.utils import time_execution_async
from langchain_core.messages import BaseMessage
from pydantic import ValidationError

from src.configs.routes import RoutesConfig
from src.utilities.api_client import api_client


class StreamingAgent(Agent):
    """Agent subclass that streams actions and state changes to WebSocket clients."""

    def __init__(
        self,
        task,
        browser,
        browser_session,
        max_failures,
        retry_delay,
        use_vision,
        generate_gif,
        max_input_tokens,
        validate_output,
        llm,
        controller,
        session_id,
        user_id,
        ws_manager,
        *args,
        **kwargs,
    ):
        """Initialize StreamingAgent with WebSocket support.

        Args:
            task: Task description for the agent.
            browser: Browser instance.
            browser_session: Browser session instance.
            max_failures: Maximum number of failures allowed.
            retry_delay: Delay between retries.
            use_vision: Whether to use vision capabilities.
            generate_gif: Whether to generate GIF recordings.
            max_input_tokens: Maximum input tokens allowed.
            validate_output: Whether to validate output.
            llm: Language model instance.
            controller: Controller instance.
            session_id: Unique session identifier.
            user_id: User identifier.
            ws_manager: WebSocket manager instance.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(
            task=task,
            browser=browser,
            browser_session=browser_session,
            max_failures=max_failures,
            retry_delay=retry_delay,
            use_vision=use_vision,
            generate_gif=generate_gif,
            max_input_tokens=max_input_tokens,
            validate_output=validate_output,
            llm=llm,
            controller=controller,
            *args,
            **kwargs,
        )
        self.session_id = session_id
        self.user_id = user_id
        self.websocket_manager = ws_manager
        self.llm_calls_metadata = []  # Store all LLM call metadata

    async def _deduct_tokens(
        self, model: str, input_tokens: int, output_tokens: int, total_tokens: int
    ):
        """Call API to deduct tokens from user's balance.

        Args:
            model: Model name used.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            total_tokens: Total tokens used.
        """
        try:
            # Your API call here
            # Example:
            # await your_api_client.deduct_tokens(user_id,model,input_tokens,output_tokens
            #     session_id=self.session_id,
            #     input_tokens=input_tokens,
            #     output_tokens=output_tokens,
            #     total_tokens=total_tokens,
            #     model=self.model_name,
            #     provider=self.chat_model_library
            # )
            update_result = await api_client.post(
                RoutesConfig.API_CREDIT_DEDUCT,
                params={
                    "user_id": self.user_id,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "capability": "browser_manager",
                },
                data={},
            )
            update_result = update_result.standard_response()
            if not update_result.get("success"):
                raise Exception(
                    f"Failed to update chat history: {update_result.get('message', 'Unknown error')}"
                )

            result = update_result.get("data")

            self.logger.info(
                f"💰 Tokens deducted - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens} having status {result}"
            )
        except Exception as e:
            self.logger.error(f"Failed to deduct tokens: {str(e)}")
            # Decide whether to raise or continue

    def _extract_llm_metadata(self, response) -> dict[str, Any]:
        """Extract metadata from LLM response with proper token extraction.

        Args:
            response: LLM response object.

        Returns:
            Dictionary containing extracted metadata.
        """
        if not response:
            return {}

        metadata = {
            "model": self.model_name,
            "provider": self.chat_model_library,
            "timestamp": time.time(),
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

        try:
            # OpenAI format (most common)
            if hasattr(response, "usage"):
                usage = response.usage
                metadata.update(
                    {
                        "input_tokens": getattr(usage, "prompt_tokens", 0),
                        "output_tokens": getattr(usage, "completion_tokens", 0),
                        "total_tokens": getattr(usage, "total_tokens", 0),
                        "usage_raw": {
                            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                            "completion_tokens": getattr(usage, "completion_tokens", 0),
                            "total_tokens": getattr(usage, "total_tokens", 0),
                        },
                    }
                )

            # Check response_metadata for token usage (LangChain wrapped responses)
            elif hasattr(response, "response_metadata"):
                resp_metadata = response.response_metadata

                if "token_usage" in resp_metadata:
                    usage = resp_metadata["token_usage"]
                    metadata.update(
                        {
                            "model": resp_metadata.get("model_name", "unknown"),
                            "input_tokens": usage.get("prompt_tokens", 0),
                            "output_tokens": usage.get("completion_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0),
                            "usage_raw": usage,
                        }
                    )
                elif "usage" in resp_metadata:
                    usage = resp_metadata["usage"]
                    metadata.update(
                        {
                            "model": resp_metadata.get("model_name", "unknown"),
                            "input_tokens": usage.get(
                                "input_tokens", usage.get("prompt_tokens", 0)
                            ),
                            "output_tokens": usage.get(
                                "output_tokens", usage.get("completion_tokens", 0)
                            ),
                            "total_tokens": usage.get("total_tokens", 0),
                            "usage_raw": usage,
                        }
                    )

                # Include all response metadata
                metadata["response_metadata"] = resp_metadata

            # Anthropic format
            elif hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                input_tokens = getattr(usage, "input_tokens", 0)
                output_tokens = getattr(usage, "output_tokens", 0)
                metadata.update(
                    {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                        "usage_raw": usage,
                    }
                )

            # Google format
            elif hasattr(response, "candidates") and response.candidates:
                if hasattr(response, "usage_metadata"):
                    usage = response.usage_metadata
                    metadata.update(
                        {
                            "input_tokens": getattr(usage, "prompt_token_count", 0),
                            "output_tokens": getattr(
                                usage, "candidates_token_count", 0
                            ),
                            "total_tokens": getattr(usage, "total_token_count", 0),
                            "usage_raw": usage,
                        }
                    )

            # Fallback: try to extract from any nested usage attribute
            else:
                # Look for usage in any attribute
                for attr_name in dir(response):
                    if "usage" in attr_name.lower():
                        try:
                            usage_attr = getattr(response, attr_name)
                            if hasattr(usage_attr, "prompt_tokens"):
                                metadata.update(
                                    {
                                        "input_tokens": getattr(
                                            usage_attr, "prompt_tokens", 0
                                        ),
                                        "output_tokens": getattr(
                                            usage_attr, "completion_tokens", 0
                                        ),
                                        "total_tokens": getattr(
                                            usage_attr, "total_tokens", 0
                                        ),
                                        "usage_raw": usage_attr,
                                        "usage_source": attr_name,
                                    }
                                )
                                break
                        except Exception as e:
                            self.logger.debug(
                                f"Error extracting usage from attribute {attr_name}: {e}"
                            )
                            continue

            # Debug info
            metadata["response_type"] = type(response).__name__
            metadata["response_attributes"] = [
                attr for attr in dir(response) if not attr.startswith("_")
            ]

        except Exception as e:
            metadata["extraction_error"] = str(e)
            self.logger.debug(f"Error extracting LLM metadata: {e}")

        return metadata

    def get_token_summary(self) -> dict[str, Any]:
        """Get summary of token usage across all LLM calls.

        Returns:
            Dictionary containing token usage statistics.
        """
        total_input_tokens = 0
        total_output_tokens = 0

        for metadata in self.llm_calls_metadata:
            total_input_tokens += metadata.get("input_tokens", 0)
            total_output_tokens += metadata.get("output_tokens", 0)

        return {
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "total_calls": len(self.llm_calls_metadata),
            "model_name": self.model_name,
            "provider": self.chat_model_library,
            "calls_metadata": self.llm_calls_metadata,
            "latest_call": (
                self.llm_calls_metadata[-1] if self.llm_calls_metadata else {}
            ),
        }

    def get_latest_llm_metadata(self) -> dict[str, Any]:
        """Get metadata from the most recent LLM call.

        Returns:
            Dictionary containing latest LLM metadata.
        """
        return self.llm_calls_metadata[-1] if self.llm_calls_metadata else {}

    async def get_token_details(self) -> dict[str, Any]:
        """Get current token consumption details.

        Returns:
            Dictionary containing current token details.
        """
        try:
            current_tokens = getattr(
                self._message_manager.state.history, "current_tokens", 0
            )
            total_tokens = (
                self.state.history.total_input_tokens() if self.state.history else 0
            )

            return {
                "current_tokens": current_tokens,
                "total_input_tokens": total_tokens,
                "step_number": self.state.n_steps,
                "message_count": (
                    len(self._message_manager.state.history.messages)
                    if hasattr(self._message_manager.state.history, "messages")
                    else 0
                ),
                "model_name": self.model_name,
            }
        except Exception as e:
            return {"error": f"Could not get token details: {str(e)}"}

    async def stream_action(self, action_data: dict[str, Any]):
        """Stream action to all connected clients.

        Args:
            action_data: Action data to stream.
        """
        # Add token information to every streamed action
        # token_details = await self.get_token_details()
        token_details = self.get_latest_llm_metadata()
        action_data.update(
            {
                "token_details": {
                    k: token_details.get(k, None)
                    for k in (
                        "model",
                        "provider",
                        "input_tokens",
                        "output_tokens",
                        "total_tokens",
                    )
                }
            }
        )

        await self.websocket_manager.send_chat_message(
            session_id=self.session_id, content=action_data, source="browser_logs"
        )

    async def step(self, step_info: AgentStepInfo | None = None) -> None:
        """Override step method to stream step information.

        Args:
            step_info: Step information object.
        """
        # Stream step start
        await self.stream_action(
            {
                "type": "step_start",
                "step_number": self.state.n_steps + 1,
                "max_steps": step_info.max_steps if step_info else None,
                "is_last_step": step_info.is_last_step() if step_info else False,
                "agent_id": self.task_id,
                "task": self.task,
            }
        )

        try:
            # Call the original step method
            await super().step(step_info)

            # Stream step completion
            await self.stream_action(
                {
                    "type": "step_complete",
                    "step_number": self.state.n_steps,
                    "success": True,
                    "agent_id": self.task_id,
                    "consecutive_failures": self.state.consecutive_failures,
                    "is_done": (
                        self.state.history.is_done() if self.state.history else False
                    ),
                }
            )

        except Exception as e:
            # Stream step error
            await self.stream_action(
                {
                    "type": "step_error",
                    "step_number": self.state.n_steps,
                    "error": str(e),
                    "agent_id": self.task_id,
                    "consecutive_failures": self.state.consecutive_failures,
                }
            )
            raise

    @time_execution_async("--get_next_action")
    async def get_next_action(self, input_messages: list[BaseMessage]) -> AgentOutput:
        """Override get_next_action to capture LLM metadata.

        Args:
            input_messages: List of input messages.

        Returns:
            AgentOutput with parsed action.
        """
        start_time = time.time()

        # Convert input messages
        input_messages = self._convert_input_messages(input_messages)

        # Variables to track metadata
        llm_metadata = {}
        raw_response = None

        if self.tool_calling_method == "raw":
            self._log_llm_call_info(input_messages, self.tool_calling_method)
            try:
                output = await self.llm.ainvoke(input_messages)
                raw_response = output
                response = {"raw": output, "parsed": None}
            except Exception as e:
                self.logger.error(f"Failed to invoke model: {str(e)}")
                status_code = (
                    getattr(e, "status_code", None) or getattr(e, "code", None) or 500
                )
                error_msg = f"LLM API call failed: {type(e).__name__}: {str(e)}"
                raise LLMException(status_code, error_msg) from e

            output.content = self._remove_think_tags(str(output.content))
            try:
                parsed_json = extract_json_from_model_output(output.content)
                parsed = self.AgentOutput(**parsed_json)
                response["parsed"] = parsed
            except (ValueError, ValidationError) as e:
                self.logger.warning(f"Failed to parse model output: {output} {str(e)}")
                raise ValueError("Could not parse response.")

        elif self.tool_calling_method is None:
            structured_llm = self.llm.with_structured_output(
                self.AgentOutput, include_raw=True
            )
            try:
                response: dict[str, Any] = await structured_llm.ainvoke(input_messages)
                raw_response = response.get("raw")
                parsed: AgentOutput | None = response["parsed"]
            except Exception as e:
                self.logger.error(f"Failed to invoke model: {str(e)}")
                raise LLMException(401, "LLM API call failed") from e

        else:
            self._log_llm_call_info(input_messages, self.tool_calling_method)
            structured_llm = self.llm.with_structured_output(
                self.AgentOutput, include_raw=True, method=self.tool_calling_method
            )
            response: dict[str, Any] = await structured_llm.ainvoke(input_messages)
            raw_response = response.get("raw")

        # Extract metadata from the raw response
        if raw_response:
            llm_metadata = self._extract_llm_metadata(raw_response)
            llm_metadata["step_number"] = self.state.n_steps
            llm_metadata["execution_time_ms"] = round(
                (time.time() - start_time) * 1000, 2
            )

            # Store metadata for later access
            self.llm_calls_metadata.append(llm_metadata)

            # Log current call tokens
            self.logger.info(
                f"🔢 LLM Call Tokens - Input: {llm_metadata['input_tokens']}, Output: {llm_metadata['output_tokens']}, Total: {llm_metadata['total_tokens']}"
            )
            await self._deduct_tokens(
                model=llm_metadata["model"],
                input_tokens=llm_metadata["input_tokens"],
                output_tokens=llm_metadata["output_tokens"],
                total_tokens=llm_metadata["total_tokens"],
            )

        # Handle tool call responses
        if response.get("parsing_error") and "raw" in response:
            raw_msg = response["raw"]
            if hasattr(raw_msg, "tool_calls") and raw_msg.tool_calls:
                tool_call = raw_msg.tool_calls[0]
                tool_call_name = tool_call["name"]
                tool_call_args = tool_call["args"]

                current_state = {
                    "page_summary": "Processing tool call",
                    "evaluation_previous_goal": "Executing action",
                    "memory": "Using tool call",
                    "next_goal": f"Execute {tool_call_name}",
                }

                action = {tool_call_name: tool_call_args}
                from browser_use.agent.views import AgentBrain

                parsed = self.AgentOutput(
                    current_state=AgentBrain(**current_state),
                    action=[self.ActionModel(**action)],
                )
            else:
                parsed = None
        else:
            parsed = response["parsed"]

        if not parsed:
            try:
                parsed_json = extract_json_from_model_output(response["raw"].content)
                parsed = self.AgentOutput(**parsed_json)
            except Exception as e:
                self.logger.warning(
                    f'Failed to parse model output: {response["raw"].content} {str(e)}'
                )
                raise ValueError("Could not parse response.")

        # Cut the number of actions to max_actions_per_step if needed
        if len(parsed.action) > self.settings.max_actions_per_step:
            parsed.action = parsed.action[: self.settings.max_actions_per_step]

        # Original logging
        if not (
            hasattr(self.state, "paused") and (self.state.paused or self.state.stopped)
        ):
            from browser_use.agent.service import log_response

            log_response(parsed, self.controller.registry.registry, self.logger)

        self._log_next_action_summary(parsed)
        return parsed

    async def multi_act(
        self, actions: list[ActionModel], check_for_new_elements: bool = True
    ) -> list[ActionResult]:
        """Override multi_act to stream individual action execution.

        Args:
            actions: List of actions to execute.
            check_for_new_elements: Whether to check for new elements.

        Returns:
            List of action results.
        """
        # Stream multi-action start
        await self.stream_action(
            {
                "type": "multi_action_start",
                "step_number": self.state.n_steps,
                "action_count": len(actions),
                "agent_id": self.task_id,
                "actions_summary": [
                    self._get_action_summary(action) for action in actions
                ],
            }
        )

        results = []

        # Get browser context
        browser_context = await self._get_browser_context()

        for i, action in enumerate(actions):
            # Stream individual action start
            action_summary = self._get_action_summary(action)
            await self.stream_action(
                {
                    "type": "action_start",
                    "step_number": self.state.n_steps,
                    "action_index": i + 1,
                    "total_actions": len(actions),
                    "action_name": action_summary["action_name"],
                    "action_params": action_summary["params"],
                    "action_description": action_summary["description"],
                    "agent_id": self.task_id,
                    "browser_context": browser_context,
                }
            )

            try:
                start_time = time.time()

                # Execute the action using the controller directly to get the same behavior
                result = await self.controller.act(
                    action=action,
                    browser_session=self.browser_session,
                    page_extraction_llm=self.settings.page_extraction_llm,
                    sensitive_data=self.sensitive_data,
                    available_file_paths=self.settings.available_file_paths,
                    context=self.context,
                )

                execution_time = time.time() - start_time
                results.append(result)

                # Update browser context after action
                browser_context = await self._get_browser_context()

                # Stream action completion
                await self.stream_action(
                    {
                        "type": "action_complete",
                        "step_number": self.state.n_steps,
                        "action_index": i + 1,
                        "total_actions": len(actions),
                        "action_name": action_summary["action_name"],
                        "success": not bool(result.error),
                        "execution_time_ms": round(execution_time * 1000, 2),
                        "result_content": (
                            result.extracted_content
                            if hasattr(result, "extracted_content")
                            else None
                        ),
                        "error": result.error if hasattr(result, "error") else None,
                        "is_done": (
                            result.is_done if hasattr(result, "is_done") else False
                        ),
                        "agent_id": self.task_id,
                        "browser_context": browser_context,
                    }
                )

                if result.is_done or result.error or i == len(actions) - 1:
                    break

                await asyncio.sleep(self.browser_profile.wait_between_actions)

            except Exception as e:
                execution_time = time.time() - start_time

                # Stream action error
                await self.stream_action(
                    {
                        "type": "action_error",
                        "step_number": self.state.n_steps,
                        "action_index": i + 1,
                        "total_actions": len(actions),
                        "action_name": action_summary["action_name"],
                        "error": str(e),
                        "execution_time_ms": round(execution_time * 1000, 2),
                        "agent_id": self.task_id,
                        "browser_context": browser_context,
                    }
                )

                # Add error result and break
                results.append(ActionResult(error=str(e), include_in_memory=True))
                break

        # Stream multi-action completion
        success_count = sum(1 for r in results if not (hasattr(r, "error") and r.error))
        await self.stream_action(
            {
                "type": "multi_action_complete",
                "step_number": self.state.n_steps,
                "total_actions": len(actions),
                "completed_actions": len(results),
                "success_count": success_count,
                "failure_count": len(results) - success_count,
                "agent_id": self.task_id,
            }
        )

        return results

    def _get_action_summary(self, action: ActionModel) -> dict[str, Any]:
        """Extract summary information from an action.

        Args:
            action: ActionModel instance.

        Returns:
            Dictionary containing action summary.
        """
        action_data = action.model_dump(exclude_unset=True)
        if not action_data:
            return {
                "action_name": "unknown",
                "params": {},
                "description": "Unknown action",
            }

        action_name = next(iter(action_data.keys()))
        action_params = action_data[action_name]

        # Get description from controller registry
        description = "Unknown action"
        if hasattr(self.controller, "registry") and hasattr(
            self.controller.registry, "registry"
        ):
            if action_name in self.controller.registry.registry.actions:
                description = self.controller.registry.registry.actions[
                    action_name
                ].description

        return {
            "action_name": action_name,
            "params": action_params,
            "description": description,
        }

    async def _get_browser_context(self) -> dict[str, Any]:
        """Get current browser context information.

        Returns:
            Dictionary containing browser context.
        """
        try:
            if not self.browser_session:
                return {"error": "No browser session available"}

            current_page = await self.browser_session.get_current_page()
            return {
                "current_url": current_page.url if current_page else None,
                "tab_count": len(self.browser_session.tabs),
                "current_tab_index": (
                    self.browser_session.tabs.index(current_page)
                    if current_page and current_page in self.browser_session.tabs
                    else -1
                ),
                "page_title": await current_page.title() if current_page else None,
            }
        except Exception as e:
            return {"error": f"Could not get browser context: {str(e)}"}

    async def run(self, max_steps: int = 100, on_step_start=None, on_step_end=None):
        """Override run to stream agent lifecycle events.

        Args:
            max_steps: Maximum number of steps.
            on_step_start: Callback for step start.
            on_step_end: Callback for step end.

        Returns:
            Agent execution result.
        """
        # Stream agent start
        await self.stream_action(
            {
                "type": "agent_start",
                "agent_id": self.task_id,
                "task": self.task,
                "max_steps": max_steps,
                "model_name": self.model_name,
                "use_vision": self.settings.use_vision,
                "tool_calling_method": self.tool_calling_method,
            }
        )

        try:
            result = await super().run(max_steps, on_step_start, on_step_end)

            # Stream agent completion
            await self.stream_action(
                {
                    "type": "agent_complete",
                    "agent_id": self.task_id,
                    "task": self.task,
                    "success": (
                        self.state.history.is_successful()
                        if self.state.history
                        else False
                    ),
                    "total_steps": self.state.n_steps,
                    "total_tokens": (
                        self.state.history.total_input_tokens()
                        if self.state.history
                        else 0
                    ),
                    "final_result": (
                        str(self.state.history.final_result())
                        if self.state.history
                        else None
                    ),
                }
            )

            return result

        except Exception as e:
            # Stream agent error
            await self.stream_action(
                {
                    "type": "agent_error",
                    "agent_id": self.task_id,
                    "task": self.task,
                    "error": str(e),
                    "total_steps": self.state.n_steps,
                }
            )
            raise
