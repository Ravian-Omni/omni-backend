"""Example usage of the LangGraph Agent capability.

This file demonstrates how to use the LangGraph agent in various scenarios.
"""

import asyncio
import os
import uuid

from src.capabilities.langgraph_agent import LangGraphAgentManager
from src.managers.cancellation_token import CancellationToken
from src.omni.memory import OmniMemory
from src.utilities.custom_manager import ChatContext


async def example_basic_chat():
    """Example 1: Basic chat with the agent."""
    print("\n=== Example 1: Basic Chat ===\n")

    # Create a chat context
    context = ChatContext(
        user_id="demo_user",
        chat_id=f"chat_{uuid.uuid4().hex[:8]}",
        chat_dir=os.path.join(os.getcwd(), "demo_chats"),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
        capability_id="cap_langgraph_demo",
        capability_name="langgraph_agent",
        collection_name="langgraph_chats",
        omni_memory=OmniMemory(),
        cancellation_token=None,
        task_id=None,
        manager_kwargs={
            "llm_config": "default",  # Use your LLM config name
        },
    )

    # Create the agent
    agent = LangGraphAgentManager(context)

    # Chat with the agent
    print("User: Hello! What can you help me with?")
    response = await agent.chat("Hello! What can you help me with?")
    print(f"Agent: {response}\n")

    # Ask about tools
    print("User: What tools do you have access to?")
    response = await agent.chat("What tools do you have access to?")
    print(f"Agent: {response}\n")

    # Get usage summary
    usage = agent.get_usage_summary()
    print(f"Token Usage: {usage}")


async def example_with_tools():
    """Example 2: Using tools with the agent."""
    print("\n=== Example 2: Using Tools ===\n")

    context = ChatContext(
        user_id="demo_user",
        chat_id=f"chat_{uuid.uuid4().hex[:8]}",
        chat_dir=os.path.join(os.getcwd(), "demo_chats"),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
        capability_id="cap_langgraph_demo",
        capability_name="langgraph_agent",
        collection_name="langgraph_chats",
        omni_memory=OmniMemory(),
        manager_kwargs={"llm_config": "default"},
    )

    agent = LangGraphAgentManager(context)

    # Ask agent to list files
    print("User: Can you list the files in the current directory?")
    response = await agent.chat("Can you list the files in the current directory?")
    print(f"Agent: {response}\n")

    # Ask agent to get current time
    print("User: What's the current date and time?")
    response = await agent.chat("What's the current date and time?")
    print(f"Agent: {response}\n")


async def example_with_custom_instructions():
    """Example 3: Using custom instructions."""
    print("\n=== Example 3: Custom Instructions ===\n")

    context = ChatContext(
        user_id="demo_user",
        chat_id=f"chat_{uuid.uuid4().hex[:8]}",
        chat_dir=os.path.join(os.getcwd(), "demo_chats"),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
        capability_id="cap_langgraph_demo",
        capability_name="langgraph_agent",
        collection_name="langgraph_chats",
        omni_memory=OmniMemory(),
        manager_kwargs={"llm_config": "default"},
    )

    agent = LangGraphAgentManager(context)

    # Load custom instructions
    agent.load_custom_instructions("""
    You are a Python expert who always:
    1. Provides code examples
    2. Explains concepts clearly
    3. Mentions best practices
    4. Uses emojis to make responses friendly
    """)

    print("User: How do I read a JSON file in Python?")
    response = await agent.chat("How do I read a JSON file in Python?")
    print(f"Agent: {response}\n")


async def example_conversation_resume():
    """Example 4: Resume a previous conversation."""
    print("\n=== Example 4: Resume Conversation ===\n")

    context = ChatContext(
        user_id="demo_user",
        chat_id=f"chat_{uuid.uuid4().hex[:8]}",
        chat_dir=os.path.join(os.getcwd(), "demo_chats"),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
        capability_id="cap_langgraph_demo",
        capability_name="langgraph_agent",
        collection_name="langgraph_chats",
        omni_memory=OmniMemory(),
        manager_kwargs={"llm_config": "default"},
    )

    agent = LangGraphAgentManager(context)

    # Simulate previous conversation
    previous_messages = [
        {"role": "user", "content": "My name is Alice"},
        {"role": "assistant", "content": "Hello Alice! Nice to meet you."},
        {"role": "user", "content": "I'm working on a Python project"},
        {
            "role": "assistant",
            "content": "That's great! What kind of Python project are you working on?",
        },
    ]

    # Load the history
    agent.load_history(previous_messages)

    # Continue the conversation
    print("User: What was my name again?")
    response = await agent.chat("What was my name again?")
    print(f"Agent: {response}\n")


async def example_with_cancellation():
    """Example 5: Using cancellation tokens."""
    print("\n=== Example 5: Cancellation Support ===\n")

    # Create cancellation token
    token = CancellationToken()

    context = ChatContext(
        user_id="demo_user",
        chat_id=f"chat_{uuid.uuid4().hex[:8]}",
        chat_dir=os.path.join(os.getcwd(), "demo_chats"),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
        capability_id="cap_langgraph_demo",
        capability_name="langgraph_agent",
        collection_name="langgraph_chats",
        omni_memory=OmniMemory(),
        cancellation_token=token,
        manager_kwargs={"llm_config": "default"},
    )

    agent = LangGraphAgentManager(context)

    # Start a task and cancel it
    async def chat_task():
        try:
            response = await agent.chat(
                "Please write a very long essay about Python programming"
            )
            print(f"Agent: {response}\n")
        except asyncio.CancelledError:
            print("Agent: Operation was cancelled!\n")

    task = asyncio.create_task(chat_task())

    # Simulate cancellation after a short delay
    await asyncio.sleep(0.5)
    print("User: Cancel the operation!")
    token.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass


async def example_manager_wrapper():
    """Example 6: Using the manager wrapper for compatibility."""
    print("\n=== Example 6: Manager Wrapper (Compatibility) ===\n")

    context = ChatContext(
        user_id="demo_user",
        chat_id=f"chat_{uuid.uuid4().hex[:8]}",
        chat_dir=os.path.join(os.getcwd(), "demo_chats"),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
        capability_id="cap_langgraph_demo",
        capability_name="langgraph_agent",
        collection_name="langgraph_chats",
        omni_memory=OmniMemory(),
        manager_kwargs={"llm_config": "default"},
    )

    # Create agent
    agent = LangGraphAgentManager(context)

    # Use the wrapper (compatible with existing capability pattern)
    print("User: Hello from the manager wrapper!")
    await agent.manager.a_initiate_chat(
        agent.manager, message="Hello from the manager wrapper!", clear_history=False
    )

    print("Agent: (Response sent via WebSocket or stored)\n")


async def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("LangGraph Agent - Usage Examples")
    print("=" * 60)

    try:
        # Run examples
        await example_basic_chat()
        await example_with_tools()
        await example_with_custom_instructions()
        await example_conversation_resume()
        await example_with_cancellation()
        await example_manager_wrapper()

        print("\n" + "=" * 60)
        print("All examples completed successfully!")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\nError running examples: {e}\n")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    # Note: This example requires proper LLM configuration
    # Make sure you have set up your API keys and LLM configs
    print("\nNote: These examples require proper LLM configuration.")
    print("Make sure you have set up your API keys in LLMConfigManager.\n")

    # Uncomment to run examples
    # asyncio.run(main())
