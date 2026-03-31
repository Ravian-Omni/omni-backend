"""Streaming browser agent with WebSocket support and token deduction."""

import asyncio
import time
from typing import TYPE_CHECKING, Any

from browser_use import ActionModel, ActionResult, Agent
from browser_use.agent.views import AgentStepInfo
from loguru import logger


if TYPE_CHECKING:
    from src.managers.cancellation_token import CancellationToken


class StreamingAgent(Agent):
    """Agent subclass that streams actions and state changes to WebSocket clients.

    Extends browser-use v0.11.5 Agent with:
    - Real-time action/step/lifecycle streaming via WebSocket
    - Per-step token deduction via external API
    - Cancellation support via CancellationToken
    """

    def __init__(
        self,
        task,
        browser_session,
        max_failures,
        use_vision,
        generate_gif,
        llm,
        controller,
        session_id,
        user_id,
        ws_manager,
        cancellation_token: "CancellationToken | None" = None,
        *args,
        **kwargs,
    ):
        """Initialize StreamingAgent with WebSocket support and cancellation.

        Args:
            task: Task description for the agent.
            browser_session: Browser session instance.
            max_failures: Maximum number of failures allowed.
            use_vision: Whether to use vision capabilities.
            generate_gif: Whether to generate GIF recordings.
            llm: Language model instance (browser_use.llm.base.BaseChatModel).
            controller: Controller/Tools instance.
            session_id: Unique session identifier.
            user_id: User identifier.
            ws_manager: WebSocket manager instance.
            cancellation_token: Token for cancelling browser operations.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        self._custom_session_id = session_id
        self.user_id = user_id
        self.websocket_manager = ws_manager
        self.cancellation_token = cancellation_token
        self.llm_calls_metadata: list[dict[str, Any]] = []
        self._is_shutting_down = False
        self._browser_session_ref = browser_session
        self._last_deducted_idx = 0

        # Build the should-stop callback for cancellation integration
        agent_ref = self

        async def _should_stop() -> bool:
            """Check if the agent should stop due to cancellation."""
            if agent_ref._is_shutting_down:
                return True
            if (
                agent_ref.cancellation_token
                and agent_ref.cancellation_token.is_cancelled()
            ):
                agent_ref._is_shutting_down = True
                return True
            return False

        super().__init__(
            task=task,
            browser_session=browser_session,
            max_failures=max_failures,
            use_vision=use_vision,
            generate_gif=generate_gif,
            llm=llm,
            controller=controller,
            calculate_cost=True,
            register_should_stop_callback=_should_stop,
            *args,
            **kwargs,
        )

        # Register browser cleanup callback on cancellation
        if self.cancellation_token:
            self.cancellation_token.add_callback(self._on_cancellation)

    @property
    def session_id(self) -> str:
        """Return the custom session ID for WebSocket communication.

        Note: browser-use Agent also has a session_id attribute (UUID7).
        We use _custom_session_id to avoid conflicts.
        """
        return self._custom_session_id

    def _on_cancellation(self) -> None:
        """Callback executed when cancellation token is triggered.

        Sets shutdown flag and schedules immediate browser closure.
        """
        logger.info(f"Cancellation triggered for session {self._custom_session_id}")
        self._is_shutting_down = True

        # Schedule immediate browser closure
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_cleanup_browser())
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._async_cleanup_browser())
                else:
                    asyncio.run(self._async_cleanup_browser())
            except Exception as e:
                logger.warning(f"Could not schedule browser cleanup: {e}")

    async def _async_cleanup_browser(self) -> None:
        """Asynchronously cleanup browser resources on cancellation.

        Uses BrowserSession.stop() which handles all CDP cleanup in v0.11.5.
        """
        try:
            if self._browser_session_ref:
                logger.info(
                    f"Closing browser for cancelled session {self._custom_session_id}"
                )
                if hasattr(self._browser_session_ref, "stop"):
                    await self._browser_session_ref.stop()
        except Exception as e:
            logger.warning(f"Error during browser cleanup on cancel: {e}")

    async def _deduct_tokens(
        self, model: str, input_tokens: int, output_tokens: int, total_tokens: int
    ):
        """Record token usage locally.

        Args:
            model: Model name used.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            total_tokens: Total tokens used.
        """
        try:
            from src.services.token_usage_service import TokenUsageService

            await TokenUsageService.record_usage(
                chat_id=self._custom_session_id,
                model_name=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                agent_name="browser_automation",
                capability="browser",
            )

            self.logger.info(
                f"Token usage recorded - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}"
            )
        except Exception as e:
            self.logger.error(f"Failed to record token usage: {str(e)}")

    async def _deduct_tokens_from_step(self):
        """Deduct tokens using the built-in token cost service after each step.

        Reads new entries from token_cost_service.usage_history since the last
        deduction and calls the external API for each.
        """
        try:
            usage_history = self.token_cost_service.usage_history
            if not usage_history:
                return

            # Only process entries since our last deduction
            new_entries = usage_history[self._last_deducted_idx :]
            self._last_deducted_idx = len(usage_history)

            for entry in new_entries:
                input_tokens = entry.usage.prompt_tokens
                output_tokens = entry.usage.completion_tokens
                total_tokens = input_tokens + output_tokens

                metadata = {
                    "model": entry.model,
                    "provider": self.llm.provider,
                    "timestamp": entry.timestamp.timestamp(),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "step_number": self.state.n_steps,
                }
                self.llm_calls_metadata.append(metadata)

                await self._deduct_tokens(
                    model=entry.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                )
        except Exception as e:
            self.logger.error(f"Failed to deduct tokens from step: {e}")

    def get_token_summary(self) -> dict[str, Any]:
        """Get summary of token usage across all LLM calls.

        Returns:
            Dictionary containing token usage statistics.
        """
        total_input_tokens = sum(
            m.get("input_tokens", 0) for m in self.llm_calls_metadata
        )
        total_output_tokens = sum(
            m.get("output_tokens", 0) for m in self.llm_calls_metadata
        )

        return {
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "total_calls": len(self.llm_calls_metadata),
            "model_name": self.llm.model,
            "provider": self.llm.provider,
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

    async def stream_action(self, action_data: dict[str, Any]):
        """Stream action to all connected clients.

        Args:
            action_data: Action data to stream.
        """
        # Add token information to every streamed action
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
            session_id=self._custom_session_id,
            content=action_data,
            source="browser_logs",
        )

    async def step(self, step_info: AgentStepInfo | None = None) -> None:
        """Override step method to stream step information.

        Args:
            step_info: Step information object.

        Raises:
            InterruptedError: If agent has been stopped via callback.
            asyncio.CancelledError: If cancellation has been requested.
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
                    "is_done": (self.history.is_done() if self.history else False),
                }
            )

        except (asyncio.CancelledError, InterruptedError):
            # Stream cancellation notification
            await self.stream_action(
                {
                    "type": "step_cancelled",
                    "step_number": self.state.n_steps,
                    "agent_id": self.task_id,
                    "message": "Step cancelled by user",
                }
            )
            raise

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

    async def multi_act(self, actions: list[ActionModel]) -> list[ActionResult]:
        """Override multi_act to stream individual action execution.

        Args:
            actions: List of actions to execute.

        Returns:
            List of action results.

        Raises:
            InterruptedError: If agent has been stopped via callback.
            asyncio.CancelledError: If cancellation has been requested.
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
            # Check for stop/pause via parent's method
            await self._check_stop_or_pause()

            # Enforce done-action-only-as-single (matches parent behavior)
            if i > 0:
                action_data = action.model_dump(exclude_unset=True)
                if action_data.get("done") is not None:
                    self.logger.debug(
                        f"Done action is allowed only as a single action - stopped after action {i} / {len(actions)}."
                    )
                    break

            # Wait between actions (only after first action)
            if i > 0:
                await asyncio.sleep(self.browser_profile.wait_between_actions)

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

                # Execute via tools.act() (v0.11.5 API)
                result = await self.tools.act(
                    action=action,
                    browser_session=self.browser_session,
                    page_extraction_llm=self.settings.page_extraction_llm,
                    sensitive_data=self.sensitive_data,
                    available_file_paths=self.available_file_paths,
                    file_system=self.file_system,
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
                        "result_content": result.extracted_content,
                        "error": result.error,
                        "is_done": result.is_done,
                        "agent_id": self.task_id,
                        "browser_context": browser_context,
                    }
                )

                if result.is_done or result.error or i == len(actions) - 1:
                    break

            except (asyncio.CancelledError, InterruptedError):
                # Stream cancellation notification
                await self.stream_action(
                    {
                        "type": "action_cancelled",
                        "step_number": self.state.n_steps,
                        "action_index": i + 1,
                        "total_actions": len(actions),
                        "action_name": action_summary["action_name"],
                        "agent_id": self.task_id,
                        "message": "Action cancelled by user",
                    }
                )
                raise

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
        success_count = sum(1 for r in results if not r.error)
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

        # Get description from tools registry
        description = "Unknown action"
        if hasattr(self, "tools") and hasattr(self.tools, "registry"):
            registry = self.tools.registry
            if hasattr(registry, "registry") and hasattr(registry.registry, "actions"):
                if action_name in registry.registry.actions:
                    description = registry.registry.actions[action_name].description

        return {
            "action_name": action_name,
            "params": action_params,
            "description": description,
        }

    async def _get_browser_context(self) -> dict[str, Any]:
        """Get current browser context information via CDP.

        Returns:
            Dictionary containing browser context.
        """
        try:
            if not self.browser_session:
                return {"error": "No browser session available"}

            current_url = await self.browser_session.get_current_page_url()
            page_title = await self.browser_session.get_current_page_title()

            # Get tab count via CDP page targets
            page_targets = self.browser_session.get_page_targets()
            tab_count = len(page_targets)

            return {
                "current_url": current_url,
                "tab_count": tab_count,
                "current_tab_index": 0,
                "page_title": page_title,
            }
        except Exception as e:
            return {"error": f"Could not get browser context: {str(e)}"}

    async def run(self, max_steps: int = 100, on_step_start=None, on_step_end=None):
        """Override run to stream agent lifecycle events with token deduction.

        Args:
            max_steps: Maximum number of steps.
            on_step_start: Callback for step start.
            on_step_end: Callback for step end.

        Returns:
            Agent execution result (AgentHistoryList).

        Raises:
            InterruptedError: If agent has been stopped via callback.
            asyncio.CancelledError: If cancellation has been requested.
        """
        # Stream agent start
        await self.stream_action(
            {
                "type": "agent_start",
                "agent_id": self.task_id,
                "task": self.task,
                "max_steps": max_steps,
                "model_name": self.llm.model,
                "use_vision": self.settings.use_vision,
            }
        )

        # Create combined on_step_end that does token deduction
        original_on_step_end = on_step_end

        async def _combined_on_step_end(agent):
            """Combined step end hook: deduct tokens then call original."""
            await self._deduct_tokens_from_step()
            if original_on_step_end:
                await original_on_step_end(agent)

        try:
            result = await super().run(max_steps, on_step_start, _combined_on_step_end)

            # Stream agent completion
            await self.stream_action(
                {
                    "type": "agent_complete",
                    "agent_id": self.task_id,
                    "task": self.task,
                    "success": (
                        self.history.is_successful() if self.history else False
                    ),
                    "total_steps": self.state.n_steps,
                    "total_tokens": (
                        self.history.usage.total_tokens
                        if self.history and self.history.usage
                        else 0
                    ),
                    "final_result": (
                        str(self.history.final_result()) if self.history else None
                    ),
                }
            )

            return result

        except (asyncio.CancelledError, InterruptedError):
            # Stream agent cancellation
            logger.info(
                f"Browser agent cancelled for session {self._custom_session_id}"
            )
            await self.stream_action(
                {
                    "type": "agent_cancelled",
                    "agent_id": self.task_id,
                    "task": self.task,
                    "total_steps": self.state.n_steps,
                    "message": "Browser agent cancelled by user",
                }
            )
            raise

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
