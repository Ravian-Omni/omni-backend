# Chat Service Project Structure

## Complete Directory Structure

```
chat-service/
├── src/
│   ├── __init__.py
│   ├── main.py                    # FastAPI entry point
│   ├── dependencies.py            # Dependency injection
│   │
│   ├── chat/                      # Core chat logic
│   │   ├── __init__.py
│   │   ├── manager.py             # Chat class & GroupChatManager
│   │   ├── prompts.py             # Chat prompts
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── brave.py           # Brave search integration
│   │       ├── composio.py        # Composio tools
│   │       └── together_image.py  # Image generation
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── chat.py                # REST API routes
│   │   └── websocket.py           # WebSocket routes
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── chat_service.py        # Chat business logic
│   │   └── websocket_service.py   # WebSocket helpers
│   │
│   ├── managers/
│   │   ├── __init__.py
│   │   ├── connection.py          # WebSocket manager
│   │   └── cancellation_token.py  # Task cancellation
│   │
│   ├── configs/
│   │   ├── __init__.py
│   │   ├── settings.py            # Application settings
│   │   ├── routes.py              # API routes config
│   │   ├── datetime_utils.py      # Date/time utilities
│   │   ├── llm_configs_manager.py # LLM configuration
│   │   └── system_ai_config.py    # AI system config
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── chat.py                # Pydantic models
│   │
│   └── utilities/
│       ├── __init__.py
│       ├── api_client.py          # External API client
│       ├── async_helpers.py       # Async utilities
│       ├── logging.py             # Logging setup
│       └── storage.py             # File storage utilities
│
├── templates/
│   └── chat.html                  # WebSocket test UI
│
├── logs/
│   └── .gitkeep
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_chat_routes.py
│   ├── test_websocket.py
│   └── test_chat_service.py
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
├── README.md
└── main.py                        # Root entry point
```

## File Mapping (Original → New)

| Original File | New Location | Changes Required |
|--------------|--------------|------------------|
| `src/chat/*` | `src/chat/*` | Minimal - update imports |
| `src/routers/chat.py` | `src/routers/chat.py` | Remove non-chat routes |
| `src/routers/websocket.py` | `src/routers/websocket.py` | Keep only chat websocket |
| `src/services/chat_service.py` | `src/services/chat_service.py` | Keep only chat methods |
| `src/managers/connection.py` | `src/managers/connection.py` | Keep chat_mode_initiate |
| `src/configs/*` | `src/configs/*` | Simplify settings |
| `src/utilities/*` | `src/utilities/*` | Copy as-is |
| `src/dependencies.py` | `src/dependencies.py` | Simplify |
| `src/main.py` | `src/main.py` | New simplified version |

## Import Path Changes

All imports should use the `src.` prefix:

```python
# ✅ Correct
from src.chat.manager import Chat
from src.configs.settings import settings
from src.managers.connection import WebSocketManager

# ❌ Incorrect
from chat.manager import Chat
from configs.settings import settings
```
