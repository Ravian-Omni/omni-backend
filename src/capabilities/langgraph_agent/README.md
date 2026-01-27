# LangGraph Agent Capability

A **production-grade** conversational AI agent built with LangGraph, designed for seamless integration with FastAPI and Electron-based applications. This implementation provides a robust, scalable, and easy-to-use agent system with comprehensive features for real-world deployments.

## Features

### 🚀 Core Capabilities
- **LangGraph Single Agent** - Efficient single-agent workflow with tool use
- **Async/Await Native** - Full async support for non-blocking operations
- **WebSocket Streaming** - Real-time message streaming to clients
- **MongoDB Persistence** - Automatic conversation storage and retrieval
- **Configurable LLMs** - Support for OpenAI, Anthropic, and custom models
- **Token Tracking** - Detailed per-call token usage tracking
- **Context Management** - Automatic context window management
- **Stop/Resume** - Pause and resume conversations seamlessly
- **Error Handling** - Comprehensive error handling and recovery
- **Performance Monitoring** - Built-in performance metrics

### 🛠️ Tool System
- **Easy Integration** - Simple decorator-based tool registration
- **Async Tools** - Native async support for all tools
- **Built-in Tools** - File operations, command execution, web fetching, and more
- **Extensible** - Add custom tools effortlessly

### 📊 Production Ready
- **Thread-Safe** - Safe for concurrent access
- **Cancellation Support** - Graceful cancellation of operations
- **Database Integration** - Seamless MongoDB integration via API
- **WebSocket Support** - Real-time communication with frontend
- **Error Recovery** - Automatic error detection and recovery strategies
- **Logging** - Comprehensive logging with Loguru

## Architecture

```
langgraph_agent/
├── __init__.py           # Package exports
├── manager.py            # Main agent manager and wrapper
├── state.py              # LangGraph state definition
├── tools.py              # Async tool implementations
├── prompts.py            # System prompts and instructions
├── response_format.py    # Pydantic response models
└── README.md            # This file
```

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

The following packages will be installed:
- `langgraph>=0.2.0` - LangGraph framework
- `langgraph-checkpoint>=2.0.0` - State persistence
- `langchain>=0.3.25` - LangChain core
- `langchain-openai>=0.3.30` - OpenAI integration
- `langchain-core>=0.3.0` - Core utilities

### 2. Configure LLM

The agent uses your existing LLM configuration system. Ensure you have a valid configuration in `LLMConfigManager`:

```python
# Example configuration
{
    "config_list": [
        {
            "model": "gpt-4",
            "api_key": "your-api-key",
            "temperature": 0.7,
            "max_tokens": 4000,
            "base_url": "https://api.openai.com/v1"  # Optional
        }
    ]
}
```

## Usage

### Basic Usage

```python
from src.capabilities.langgraph_agent import LangGraphAgentManager
from src.utilities.custom_manager import ChatContext
from src.omni.memory import OmniMemory

# Create chat context
context = ChatContext(
    user_id="user123",
    chat_id="chat456",
    chat_dir="/path/to/chat/dir",
    call_id="call789",
    capability_id="cap_langgraph",
    capability_name="langgraph_agent",
    collection_name="langgraph_chats",
    omni_memory=OmniMemory(),
    cancellation_token=None,
    task_id=None,
    manager_kwargs={
        "websocket_manager": websocket_manager,  # Optional
        "llm_config": "default",  # LLM config name
    },
)

# Create agent
agent = LangGraphAgentManager(context)

# Chat with agent
response = await agent.chat("Hello! Can you help me read a file?")
print(response)
```

### WebSocket Integration

```python
# In your WebSocket handler
async def handle_langgraph_chat(websocket, chat_id, initial_message):
    # Create context with WebSocket manager
    context = ChatContext(
        user_id=user_id,
        chat_id=chat_id,
        # ... other fields ...
        manager_kwargs={
            "websocket_manager": websocket_manager,
            "llm_config": "gpt-4",
        },
    )

    # Create agent
    agent = LangGraphAgentManager(context)

    # Use the manager wrapper for compatibility
    await agent.manager.a_initiate_chat(
        agent.manager,
        message=initial_message,
        clear_history=False,
    )
```

### Resume Conversation

```python
# Load previous messages
previous_messages = [
    {"role": "user", "content": "Hello!"},
    {"role": "assistant", "content": "Hi! How can I help you?"},
]

# Resume conversation
agent = LangGraphAgentManager(context)
agent.load_history(previous_messages)

# Continue chatting
response = await agent.chat("What was my last question?")
```

### Custom Instructions

```python
# Add custom instructions
agent = LangGraphAgentManager(context)
agent.load_custom_instructions("""
You are a Python expert specialized in data science.
Always provide code examples and explain concepts clearly.
""")

response = await agent.chat("How do I use pandas?")
```

### Token Usage Tracking

```python
# Get usage summary
usage = agent.get_usage_summary()
print(f"Total tokens: {usage['total_tokens']}")
print(f"Prompt tokens: {usage['prompt_tokens']}")
print(f"Completion tokens: {usage['completion_tokens']}")
print(f"Iterations: {usage['iteration_count']}")
```

## Configuration

### LLM Configuration

Configure which LLM to use:

```python
context.manager_kwargs = {
    "llm_config": "gpt-4",  # or "claude-sonnet", "default", etc.
    "websocket_manager": websocket_manager,
}
```

### State Configuration

Customize max iterations and context window:

```python
# In state.py, modify create_initial_state defaults:
state = create_initial_state(
    user_id=user_id,
    chat_id=chat_id,
    call_id=call_id,
    capability_id=capability_id,
    task_id=task_id,
    max_iterations=50,  # Increase max iterations
    max_context_tokens=150000,  # Increase context window
)
```

### Custom System Prompt

Modify `prompts.py` to customize the agent's behavior:

```python
# In prompts.py
SYSTEM_PROMPT = """Your custom system prompt here..."""
```

## Adding Custom Tools

Tools are easy to add using LangChain's `@tool` decorator:

### Step 1: Define the Tool

```python
# In tools.py

from langchain_core.tools import tool
from loguru import logger

@tool
async def my_custom_tool(param1: str, param2: int) -> str:
    """Description of what your tool does.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Description of return value.
    """
    try:
        # Your async tool implementation
        result = await some_async_operation(param1, param2)
        return f"Success: {result}"
    except Exception as e:
        logger.error(f"Error in my_custom_tool: {e}")
        return f"Error: {str(e)}"
```

### Step 2: Register the Tool

```python
# In tools.py, add to ALL_TOOLS list

ALL_TOOLS = [
    # Existing tools...
    read_file_tool,
    write_file_tool,

    # Your custom tool
    my_custom_tool,
]
```

### Step 3: Use the Tool

The agent will automatically have access to your tool!

```python
agent = LangGraphAgentManager(context)
response = await agent.chat("Please use my_custom_tool with 'test' and 42")
```

## Available Tools

The agent comes with these built-in tools:

### File Operations
- `read_file_tool` - Read file contents
- `write_file_tool` - Write to a file
- `list_directory_tool` - List directory contents
- `create_directory_tool` - Create directories
- `delete_file_tool` - Delete files/directories

### Command Execution
- `execute_command_tool` - Execute shell commands
- `search_files_tool` - Search for text in files

### Web & API
- `fetch_url_tool` - Fetch content from URLs
- `api_request_tool` - Make HTTP API requests

### Data Processing
- `calculate_tool` - Perform calculations
- `parse_json_tool` - Parse and format JSON

### Utilities
- `get_current_time_tool` - Get current date/time

## Error Handling

The agent includes comprehensive error handling:

```python
try:
    response = await agent.chat(user_message)
except asyncio.CancelledError:
    print("Operation was cancelled")
except Exception as e:
    print(f"Error: {e}")
    # Agent state is preserved, can retry or recover
```

## Performance Optimization

### Context Window Management

The agent automatically trims old messages when approaching context limits:

```python
# Automatic trimming happens at 80% of max_context_tokens
# Configure in state.py:
max_context_tokens=100000  # Adjust based on your LLM
```

### Iteration Limits

Prevent infinite loops with iteration limits:

```python
max_iterations=25  # Agent stops after 25 iterations
```

### WebSocket Streaming

Messages are streamed in real-time for better UX:

```python
# Streaming is automatic when websocket_manager is provided
# Chunks are sent as they arrive from the LLM
```

## MongoDB Integration

Conversations are automatically saved to MongoDB:

```python
# Message format in MongoDB:
{
    "user_id": "user123",
    "chat_id": "chat456",
    "call_id": "call789",
    "capability_id": "cap_langgraph",
    "messages": [
        {"role": "user", "name": "user", "content": "..."},
        {"role": "assistant", "name": "langgraph_agent", "content": "..."}
    ],
    "raw_messages": [
        {
            "role": "user",
            "name": "user",
            "raw_message": {...},
            "usage": {...},
            "timestamp": "2024-01-01T00:00:00Z",
            "task_id": "task123"
        }
    ],
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
}
```

## Cancellation Support

Gracefully cancel long-running operations:

```python
from src.managers.cancellation_token import CancellationToken

# Create cancellation token
token = CancellationToken()

# Pass to context
context.cancellation_token = token

# Later, cancel the operation
token.cancel()

# Agent will stop at next checkpoint
```

## Testing

```python
import asyncio
from src.capabilities.langgraph_agent import LangGraphAgentManager

async def test_agent():
    # Create mock context
    context = create_test_context()

    # Create agent
    agent = LangGraphAgentManager(context)

    # Test chat
    response = await agent.chat("Hello!")
    assert "hello" in response.lower()

    # Test tools
    response = await agent.chat("What files are in the current directory?")
    assert "[FILE]" in response or "[DIR]" in response

    # Test usage tracking
    usage = agent.get_usage_summary()
    assert usage["total_tokens"] > 0

# Run test
asyncio.run(test_agent())
```

## Troubleshooting

### Agent Not Responding

1. Check LLM configuration is valid
2. Verify API key is set
3. Check network connectivity
4. Review logs for errors

### Token Limit Exceeded

1. Reduce `max_context_tokens` in state configuration
2. Enable more aggressive message trimming
3. Use a model with larger context window

### WebSocket Not Streaming

1. Verify `websocket_manager` is provided in context
2. Check WebSocket connection is active
3. Ensure `streaming=True` in LLM config

### Tools Not Working

1. Verify tool is in `ALL_TOOLS` list
2. Check tool function signature is correct
3. Ensure tool has proper type hints
4. Review tool error logs

## Best Practices

### 1. Always Provide Context
```python
# Good
context = ChatContext(
    user_id=user_id,
    chat_id=chat_id,
    # ... all required fields
)

# Bad
context = ChatContext(user_id=user_id)  # Missing fields
```

### 2. Handle Errors Gracefully
```python
try:
    response = await agent.chat(message)
except Exception as e:
    logger.error(f"Agent error: {e}")
    # Provide fallback response
```

### 3. Monitor Token Usage
```python
usage = agent.get_usage_summary()
if usage["total_tokens"] > 50000:
    logger.warning("High token usage detected")
```

### 4. Use Cancellation Tokens
```python
# For long-running operations
token = CancellationToken()
context.cancellation_token = token

# Cancel if needed
if should_cancel:
    token.cancel()
```

### 5. Clean Up Resources
```python
# Agent resources are automatically cleaned up
# But explicitly reset if reusing:
agent.reset_conversation()
```

## API Reference

### LangGraphAgentManager

Main agent manager class.

#### Methods

- `__init__(context: ChatContext)` - Initialize agent
- `chat(user_message: str) -> str` - Process message and return response
- `load_history(messages: list) -> None` - Load previous conversation
- `load_custom_instructions(instructions: str) -> None` - Set custom instructions
- `set_task_id(task_id: str) -> None` - Set task identifier
- `reset_conversation() -> None` - Clear conversation history
- `get_usage_summary() -> dict` - Get token usage statistics

### LangGraphAgentManagerWrapper

Wrapper for compatibility with existing capability pattern.

#### Methods

- `a_initiate_chat(recipient, message, clear_history=False, **kwargs)` - Start chat
- `resume(messages: list) -> None` - Resume conversation

## Contributing

### Adding New Features

1. Create feature branch
2. Add implementation
3. Update tests
4. Update documentation
5. Submit PR

### Code Style

- Follow PEP 8
- Use type hints
- Add docstrings
- Include error handling

## License

See main project license.

## Support

For issues or questions:
1. Check this README
2. Review existing issues
3. Create new issue with details

## Changelog

### v1.0.0 (Initial Release)
- LangGraph single agent implementation
- Async/await support
- WebSocket streaming
- MongoDB persistence
- Token tracking
- Context management
- Stop/resume capability
- Comprehensive error handling
- Built-in tools
- Easy tool integration
- Production-ready architecture
