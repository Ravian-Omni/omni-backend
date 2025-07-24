import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Set
import websockets
from browser_use import Agent
from browser_use.agent.views import ActionModel, ActionResult, AgentOutput, AgentStepInfo
from browser_use.browser import BrowserSession
from browser_use.controller.service import Controller
from dependencies import get_websocket_manager

class StreamingAgent(Agent):
    """Agent subclass that streams actions and state changes to WebSocket clients"""
    
    def __init__(self, task, browser, browser_session, max_failures, retry_delay, use_vision, generate_gif, max_input_tokens, validate_output, llm, controller, session_id, ws_manager, *args, **kwargs):
        super().__init__(task=task,
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
                         *args, **kwargs)
        self.session_id = session_id
        self.websocket_manager = ws_manager

    async def stream_action(self, action_data: Dict[str, Any]):
        """Stream action to all connected clients"""
        await self.websocket_manager.send_chat_message(
                session_id=self.session_id, 
                content=action_data, 
                source="browser_logs"
            )
        
                
    async def step(self, step_info: AgentStepInfo | None = None) -> None:
        """Override step method to stream step information"""
        
        # Stream step start
        await self.stream_action({
            'type': 'step_start',
            'step_number': self.state.n_steps + 1,
            'max_steps': step_info.max_steps if step_info else None,
            'is_last_step': step_info.is_last_step() if step_info else False,
            'agent_id': self.task_id,
            'task': self.task
        })
        
        try:
            # Call the original step method
            await super().step(step_info)
            
            # Stream step completion
            await self.stream_action({
                'type': 'step_complete',
                'step_number': self.state.n_steps,
                'success': True,
                'agent_id': self.task_id,
                'consecutive_failures': self.state.consecutive_failures,
                'is_done': self.state.history.is_done() if self.state.history else False
            })
            
        except Exception as e:
            # Stream step error
            await self.stream_action({
                'type': 'step_error',
                'step_number': self.state.n_steps,
                'error': str(e),
                'agent_id': self.task_id,
                'consecutive_failures': self.state.consecutive_failures
            })
            raise
    
    async def get_next_action(self, input_messages) -> AgentOutput:
        """Override get_next_action to stream LLM calls and responses"""
        
        # Stream LLM call start
        await self.stream_action({
            'type': 'llm_call_start',
            'step_number': self.state.n_steps,
            'message_count': len(input_messages),
            'model_name': self.model_name,
            'tool_calling_method': self.tool_calling_method,
            'agent_id': self.task_id,
            'current_tokens': getattr(self._message_manager.state.history, 'current_tokens', 0)
        })
        
        try:
            start_time = time.time()
            result = await super().get_next_action(input_messages)
            execution_time = time.time() - start_time
            
            # Stream LLM response
            await self.stream_action({
                'type': 'llm_response',
                'step_number': self.state.n_steps,
                'success': True,
                'execution_time_ms': round(execution_time * 1000, 2),
                'agent_id': self.task_id,
                'action_count': len(result.action) if result.action else 0,
                'evaluation': result.current_state.evaluation_previous_goal if hasattr(result, 'current_state') else None,
                'next_goal': result.current_state.next_goal if hasattr(result, 'current_state') else None,
                'memory': result.current_state.memory if hasattr(result, 'current_state') else None
            })
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            
            # Stream LLM error
            await self.stream_action({
                'type': 'llm_error',
                'step_number': self.state.n_steps,
                'error': str(e),
                'execution_time_ms': round(execution_time * 1000, 2),
                'agent_id': self.task_id
            })
            raise
    
    async def multi_act(self, actions: list[ActionModel], check_for_new_elements: bool = True) -> list[ActionResult]:
        """Override multi_act to stream individual action execution"""
        
        # Stream multi-action start
        await self.stream_action({
            'type': 'multi_action_start',
            'step_number': self.state.n_steps,
            'action_count': len(actions),
            'agent_id': self.task_id,
            'actions_summary': [self._get_action_summary(action) for action in actions]
        })
        
        results = []
        
        # Get browser context
        browser_context = await self._get_browser_context()
        
        for i, action in enumerate(actions):
            # Stream individual action start
            action_summary = self._get_action_summary(action)
            await self.stream_action({
                'type': 'action_start',
                'step_number': self.state.n_steps,
                'action_index': i + 1,
                'total_actions': len(actions),
                'action_name': action_summary['action_name'],
                'action_params': action_summary['params'],
                'action_description': action_summary['description'],
                'agent_id': self.task_id,
                'browser_context': browser_context
            })
            
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
                await self.stream_action({
                    'type': 'action_complete',
                    'step_number': self.state.n_steps,
                    'action_index': i + 1,
                    'total_actions': len(actions),
                    'action_name': action_summary['action_name'],
                    'success': not bool(result.error),
                    'execution_time_ms': round(execution_time * 1000, 2),
                    'result_content': result.extracted_content if hasattr(result, 'extracted_content') else None,
                    'error': result.error if hasattr(result, 'error') else None,
                    'is_done': result.is_done if hasattr(result, 'is_done') else False,
                    'agent_id': self.task_id,
                    'browser_context': browser_context
                })
                
                if result.is_done or result.error or i == len(actions) - 1:
                    break
                    
                await asyncio.sleep(self.browser_profile.wait_between_actions)
                
            except Exception as e:
                execution_time = time.time() - start_time
                
                # Stream action error
                await self.stream_action({
                    'type': 'action_error',
                    'step_number': self.state.n_steps,
                    'action_index': i + 1,
                    'total_actions': len(actions),
                    'action_name': action_summary['action_name'],
                    'error': str(e),
                    'execution_time_ms': round(execution_time * 1000, 2),
                    'agent_id': self.task_id,
                    'browser_context': browser_context
                })
                
                # Add error result and break
                results.append(ActionResult(error=str(e), include_in_memory=True))
                break
        
        # Stream multi-action completion
        success_count = sum(1 for r in results if not (hasattr(r, 'error') and r.error))
        await self.stream_action({
            'type': 'multi_action_complete',
            'step_number': self.state.n_steps,
            'total_actions': len(actions),
            'completed_actions': len(results),
            'success_count': success_count,
            'failure_count': len(results) - success_count,
            'agent_id': self.task_id
        })
        
        return results
    
    def _get_action_summary(self, action: ActionModel) -> Dict[str, Any]:
        """Extract summary information from an action"""
        action_data = action.model_dump(exclude_unset=True)
        if not action_data:
            return {
                'action_name': 'unknown',
                'params': {},
                'description': 'Unknown action'
            }
        
        action_name = next(iter(action_data.keys()))
        action_params = action_data[action_name]
        
        # Get description from controller registry
        description = 'Unknown action'
        if hasattr(self.controller, 'registry') and hasattr(self.controller.registry, 'registry'):
            if action_name in self.controller.registry.registry.actions:
                description = self.controller.registry.registry.actions[action_name].description
        
        return {
            'action_name': action_name,
            'params': action_params,
            'description': description
        }
    
    async def _get_browser_context(self) -> Dict[str, Any]:
        """Get current browser context information"""
        try:
            if not self.browser_session:
                return {'error': 'No browser session available'}
            
            current_page = await self.browser_session.get_current_page()
            return {
                'current_url': current_page.url if current_page else None,
                'tab_count': len(self.browser_session.tabs),
                'current_tab_index': self.browser_session.tabs.index(current_page) if current_page and current_page in self.browser_session.tabs else -1,
                'page_title': await current_page.title() if current_page else None
            }
        except Exception as e:
            return {
                'error': f'Could not get browser context: {str(e)}'
            }
    
    async def run(self, max_steps: int = 100, on_step_start=None, on_step_end=None):
        """Override run to stream agent lifecycle events"""
        
        # Stream agent start
        await self.stream_action({
            'type': 'agent_start',
            'agent_id': self.task_id,
            'task': self.task,
            'max_steps': max_steps,
            'model_name': self.model_name,
            'use_vision': self.settings.use_vision,
            'tool_calling_method': self.tool_calling_method
        })
        
        try:
            result = await super().run(max_steps, on_step_start, on_step_end)
            
            # Stream agent completion
            await self.stream_action({
                'type': 'agent_complete',
                'agent_id': self.task_id,
                'task': self.task,
                'success': self.state.history.is_successful() if self.state.history else False,
                'total_steps': self.state.n_steps,
                'total_tokens': self.state.history.total_input_tokens() if self.state.history else 0,
                'final_result': str(self.state.history.final_result()) if self.state.history else None
            })
            
            return result
            
        except Exception as e:
            # Stream agent error
            await self.stream_action({
                'type': 'agent_error',
                'agent_id': self.task_id,
                'task': self.task,
                'error': str(e),
                'total_steps': self.state.n_steps
            })
            raise
