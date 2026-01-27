# LangGraph Agent - Quick Start Guide

Get up and running with the LangGraph agent in 5 minutes!

## Prerequisites

1. Python 3.12+
2. Valid LLM API key (OpenAI, Anthropic, etc.)
3. MongoDB instance (for conversation storage)

## Step 1: Install Dependencies

```bash
cd /path/to/omni-backend
pip install -r requirements.txt
```

This will install:
- `langgraph>=0.2.0`
- `langchain>=0.3.25`
- `langchain-openai>=0.3.30`
- And all other required packages

## Step 2: Configure Your LLM

The agent uses your existing `LLMConfigManager`. Ensure you have a configuration set up:

```python
# Your LLM config should look like this:
{
    "config_list": [
        {
            "model": "gpt-4",
            "api_key": "your-api-key-here",
            "temperature": 0.7,
            "max_tokens": 4000
        }
    ]
}
```

## Step 3: Create Your First Agent

```python
import asyncio
import os
import uuid
from src.capabilities.langgraph_agent import LangGraphAgentManager
from src.utilities.custom_manager import ChatContext
from src.omni.memory import OmniMemory

async def quick_start():
    # Create context
    context = ChatContext(
        user_id="demo_user",
        chat_id=f"chat_{uuid.uuid4().hex[:8]}",
        chat_dir=os.path.join(os.getcwd(), "demo_chats"),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
        capability_id="cap_langgraph",
        capability_name="langgraph_agent",
        collection_name="langgraph_chats",
        omni_memory=OmniMemory(),
        manager_kwargs={
            "llm_config": "default",  # Your LLM config name
        },
    )

    # Create agent
    agent = LangGraphAgentManager(context)

    # Chat!
    response = await agent.chat("Hello! Can you help me?")
    print(response)

    # Get usage
    usage = agent.get_usage_summary()
    print(f"Tokens used: {usage['total_tokens']}")

# Run it
asyncio.run(quick_start())
```

## Step 4: Integrate with WebSocket (Optional)

For real-time streaming in your FastAPI app:

```python
# In your WebSocket endpoint
@app.websocket("/ws/langgraph/{chat_id}")
async def websocket_endpoint(websocket: WebSocket, chat_id: str):
    await websocket_manager.connect(websocket, chat_id)

    try:
        context = ChatContext(
            # ... your context setup ...
            manager_kwargs={
                "websocket_manager": websocket_manager,
                "llm_config": "default",
            },
        )

        agent = LangGraphAgentManager(context)

        # Messages will stream in real-time to the client!
        await agent.manager.a_initiate_chat(
            agent.manager,
            message=initial_message,
            clear_history=False,
        )

    except WebSocketDisconnect:
        await websocket_manager.disconnect(chat_id)
```

## Step 5: Add Custom Tools (Optional)

```python
# In tools.py, add your tool:

@tool
async def my_weather_tool(city: str) -> str:
    """Get weather for a city.

    Args:
        city: Name of the city.

    Returns:
        Weather information.
    """
    # Your implementation
    return f"Weather in {city}: Sunny, 75°F"

# Add to ALL_TOOLS list
ALL_TOOLS = [
    # ... existing tools ...
    my_weather_tool,
]
```

That's it! Your agent now has the new tool.

## Common Use Cases

### 1. File Operations
```python
response = await agent.chat("Read the contents of config.json")
```

### 2. Command Execution
```python
response = await agent.chat("Run 'pip list' and show me what's installed")
```

### 3. Web Scraping
```python
response = await agent.chat("Fetch the content from https://example.com")
```

### 4. Data Processing
```python
response = await agent.chat("Calculate: (123 + 456) * 789")
```

### 5. Multi-Step Tasks
```python
response = await agent.chat("""
1. List all Python files in the current directory
2. Count how many lines of code are in each file
3. Give me a summary
""")
```

## Tips for Success

### 1. Context Management
The agent automatically trims old messages when approaching the context limit. You can configure this in [state.py](state.py):

```python
max_context_tokens=100000  # Adjust based on your LLM
```

### 2. Error Handling
Always wrap agent calls in try/except:

```python
try:
    response = await agent.chat(message)
except asyncio.CancelledError:
    print("Operation cancelled")
except Exception as e:
    logger.error(f"Agent error: {e}")
```

### 3. Token Monitoring
Check token usage regularly:

```python
usage = agent.get_usage_summary()
if usage["total_tokens"] > 50000:
    logger.warning("High token usage!")
```

### 4. Resume Conversations
Load previous conversation history:

```python
agent.load_history(previous_messages)
response = await agent.chat("What did we discuss earlier?")
```

### 5. Custom Instructions
Tailor the agent's behavior:

```python
agent.load_custom_instructions("""
You are a senior Python developer.
Always provide code examples.
Use best practices.
""")
```

## Troubleshooting

### Problem: Agent not responding
**Solution:** Check your LLM API key and network connectivity.

### Problem: WebSocket not streaming
**Solution:** Ensure `websocket_manager` is provided in `manager_kwargs`.

### Problem: Token limit exceeded
**Solution:** Reduce `max_context_tokens` or use a model with larger context window.

### Problem: Tools not working
**Solution:** Verify tool is in `ALL_TOOLS` list and has proper type hints.

## Next Steps

1. Read the full [README.md](README.md) for detailed documentation
2. Check out [example_usage.py](example_usage.py) for more examples
3. Explore the codebase to understand the architecture
4. Add your own custom tools
5. Integrate with your Electron frontend

## Need Help?

- Review the [README.md](README.md) for comprehensive documentation
- Check the code comments for implementation details
- Look at [example_usage.py](example_usage.py) for working examples

## What's Next?

The LangGraph agent is production-ready! Here are some ideas:

1. **Add domain-specific tools** - Create tools for your specific use case
2. **Customize prompts** - Modify `prompts.py` to change behavior
3. **Add response formatting** - Use `response_format.py` for structured outputs
4. **Implement checkpointing** - Use LangGraph's checkpointing for persistence
5. **Add human-in-the-loop** - Implement approval flows for sensitive operations

Happy coding! 🚀
