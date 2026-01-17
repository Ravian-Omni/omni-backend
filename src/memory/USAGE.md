# SimpleMem Memory System

A non-blocking memory system for AutoGen multi-agent orchestration.

## Quick Start

```python
from src.memory import mem

# Fire-and-forget (use in sync code)
mem.fire(mem.add_message(chat_id, "agent_name", "message content"))

# Async usage
await mem.add_message(chat_id, speaker, content, task_id, capability)
context = await mem.get_context(chat_id, task_id, capability, query)
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Integration Layer                        │
│  src/memory/integration.py - Clean API for AutoGen managers │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Bridge Layer                            │
│  src/memory/bridge.py - Singleton orchestrator              │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌─────────────────┐
│    Store      │   │    Processor    │   │ ContextProvider │
│   (SQLite)    │   │  (Compression)  │   │   (Retrieval)   │
└───────────────┘   └─────────────────┘   └─────────────────┘
```

## API Reference

### `mem.fire(coro)`
Fire-and-forget async operation. Use in sync code.

```python
# Won't block - runs in background
mem.fire(mem.add_message(chat_id, speaker, content))
mem.fire(mem.set_goal(chat_id, task_id, goal))
```

### `mem.add_message(...)`
Store a message in memory.

```python
await mem.add_message(
    chat_id="chat_123",
    speaker="python_coder",
    content="Created main.py with Flask app",
    task_id="task_456",           # optional
    capability="python_coder",     # optional
    capability_run_id="run_789",   # optional
    raw_message={"key": "value"},  # optional
)
```

### `mem.init_task(chat_id, task_id)`
Initialize task state for a new task.

```python
await mem.init_task("chat_123", "task_456")
```

### `mem.set_goal(chat_id, task_id, goal)`
Set the user's goal for a task.

```python
await mem.set_goal("chat_123", "task_456", "Build a REST API with authentication")
```

### `mem.set_plan(chat_id, task_id, plan_items)`
Set the task plan.

```python
await mem.set_plan("chat_123", "task_456", [
    {"description": "Create database models", "capability": "python_coder"},
    {"description": "Add API routes", "capability": "python_coder"},
    {"description": "Write tests", "capability": "python_coder"},
])

# Also accepts simple strings
await mem.set_plan("chat_123", "task_456", [
    "Create database models",
    "Add API routes",
    "Write tests",
])
```

### `mem.start_run(chat_id, task_id, capability, query)`
Start tracking a capability run.

```python
run = await mem.start_run(
    "chat_123",
    "task_456",
    "python_coder",
    "Create a Flask API"
)
# Returns CapabilityRun object or None
```

### `mem.complete_run(run, chat_id, raw_result)`
Complete a capability run with results.

```python
await mem.complete_run(
    run,
    "chat_123",
    "Successfully created Flask app with 3 endpoints"
)
```

### `mem.get_context(chat_id, task_id, capability, query)`
Get context messages for capability injection.

```python
context = await mem.get_context(
    "chat_123",
    "task_456",
    "python_coder",
    "Add authentication"
)
# Returns list of AutoGen message dicts:
# [{"role": "user", "name": "context_keeper", "content": "## Goal\n..."}]
```

### `mem.flush(chat_id, task_id)`
Force flush pending messages.

```python
await mem.flush("chat_123", "task_456")
```

## Integration Points

### CustomGroupChatManager (custom_manager.py)

Messages are automatically fed to memory:

```python
def _print_received_message(self, message, sender):
    # ... existing code ...

    # Feed to SimpleMem (non-blocking)
    mem.fire(mem.add_message(
        chat_id=self.context.chat_id,
        speaker=sender.name,
        content=content,
        task_id=self.context.task_id,
        capability=self.context.capability_name,
    ))
```

### Omni Manager (manager.py)

Task state is managed automatically:

```python
def set_task_id(self, task_id):
    self.task_id = task_id
    mem.fire(mem.init_task(self.chat_id, task_id))

# In custom_speaker_selection_func:
if planner_data.get("breakdown"):
    mem.fire(mem.set_plan(self.chat_id, self.task_id, breakdown))

if user_goal:
    mem.fire(mem.set_goal(self.chat_id, self.task_id, user_goal))
```

### CapabilityManager (capability_manager.py)

Capability runs are tracked and context is injected:

```python
async def execute_capability(self, query, config, call_id):
    # Start tracking
    run = await mem.start_run(
        self.chat_id, config.task_id, config.name, query
    )

    # Get context for injection
    context = await mem.get_context(
        self.chat_id, config.task_id, config.name, query
    )

    # ... execute capability ...

    # Complete tracking
    await mem.complete_run(run, self.chat_id, result)
```

## Storage

- **Location**: `~/.ravian/memory/`
- **Database**: SQLite with WAL mode
- **Embeddings**: Stored as numpy BLOBs (no external vector DB)
- **Indexes**: Chat ID, Task ID, Capability, Timestamp

## Configuration

Default configuration in `models.py`:

```python
MemoryConfig(
    db_path="~/.ravian/memory",
    buffer_size=5,                    # Messages before compression
    compression_threshold=0.35,       # Entropy threshold
    embedding_model="text-embedding-3-small",
    embedding_dimension=1536,
    max_retrieval_k=20,
    enable_background_processing=True,
)
```

## Error Handling

All `mem` methods fail silently - they log errors at debug level and return `None` or empty lists. This ensures memory operations never block or crash the main flow.

```python
# These are safe - won't raise exceptions
await mem.add_message(...)  # Returns None on error
await mem.get_context(...)  # Returns [] on error
mem.fire(mem.set_goal(...)) # Runs in background, errors logged
```

## Troubleshooting

### Memory not working?

1. Check if SimpleMem bridge initializes:
   ```python
   from src.memory.bridge import get_memory_bridge
   bridge = await get_memory_bridge()
   print(bridge)  # Should not be None
   ```

2. Check logs for initialization errors:
   ```
   grep -i "simplemem" logs/app.log
   ```

3. Verify database exists:
   ```bash
   ls ~/.ravian/memory/
   ```

### Context not being injected?

1. Ensure `task_id` is set before capability execution
2. Check that messages are being added (query the database)
3. Verify the capability name matches

### LLM compression failing?

The processor uses `gpt_4_1_mini` config. Ensure this config exists in your LLM config manager, or modify `processor.py` to use a different config.
