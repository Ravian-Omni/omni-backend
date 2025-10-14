# Omni Backend Architecture

## Directory Structure

```
omni-backend/
├── src/                           # Main application source code
│   ├── capabilities/             # AI capability modules
│   │   ├── browser_manager/     # Web scraping and browser automation
│   │   ├── email_manager/       # Email composition and management
│   │   ├── file_finder/         # Intelligent file search
│   │   ├── image_generator/     # AI-powered image generation
│   │   └── python_developer/    # Python code generation and assistance
│   ├── configs/                  # Configuration management
│   │   ├── settings.py          # Application settings
│   │   ├── llm_configs_manager.py  # LLM configuration
│   │   └── system_ai_config.py  # System AI configuration
│   ├── managers/                 # Connection and session managers
│   │   ├── connection.py        # WebSocket connection management
│   │   └── cancellation_token.py  # Cancellation token handling
│   ├── routers/                  # API route definitions
│   │   ├── chat.py              # Chat management endpoints
│   │   ├── config.py            # Configuration endpoints
│   │   └── ws.py                # WebSocket endpoints
│   ├── utilities/                # Helper utilities and common functions
│   │   ├── logging.py           # Logging configuration
│   │   ├── storage.py           # Storage utilities
│   │   ├── api_client.py        # External API client
│   │   ├── async_helpers.py     # Async utility functions
│   │   ├── custom_manager.py    # Custom manager utilities
│   │   └── venv_config.py       # Virtual environment configuration
│   ├── omni/                     # Core omni logic and handlers
│   │   ├── manager.py           # Main omni manager
│   │   ├── memory.py            # Memory management
│   │   ├── capability_manager.py  # Capability orchestration
│   │   ├── response_format.py   # Response formatting
│   │   ├── prompts.py           # Prompt templates
│   │   └── country_data.py      # Country data utilities
│   ├── main.py                   # FastAPI application entry point
│   └── dependencies.py           # Dependency injection setup
├── scripts/                       # Build and deployment scripts
│   ├── build.py                  # Main build script
│   └── build_scripts/            # Nuitka build scripts
│       ├── nuitka_build.py
│       ├── nuitka_optimized.py
│       └── nuitka_build_executable.py
├── docs/                          # Documentation
│   ├── architecture.md           # This file
│   └── pre-commit-guide.md       # Pre-commit setup guide
├── templates/                     # HTML templates for WebSocket UI
│   ├── index.html                # Main WebSocket test UI
│   └── capability.html           # Capability test UI
├── logs/                          # Application logs (gitignored)
├── main.py                        # Root entry point (imports from src/)
├── requirements.txt               # Python dependencies
├── .gitignore                     # Git ignore rules
├── .pre-commit-config.yaml       # Pre-commit hook configuration
└── README.md                      # Project documentation
```

## Key Components

### 1. Capabilities System

Each capability is a self-contained module with:
- **manager.py** - Main capability logic and orchestration
- **prompts.py** - LLM prompt templates
- **response_format.py** - Structured response formats
- **executor.py** (optional) - Code execution handling

Available capabilities:
- **Python Developer**: Code generation, debugging, and Python assistance
- **File Finder**: Intelligent file search and management
- **Email Manager**: Email composition and sending
- **Image Generator**: AI-powered image generation
- **Browser Manager**: Web scraping and browser automation

### 2. Connection Management

The WebSocket manager handles:
- Client connection lifecycle
- Session management
- Message routing
- Input/output streaming
- Cancellation tokens

### 3. Configuration

- **settings.py**: Central configuration using Pydantic
- **llm_configs_manager.py**: LLM provider configuration and caching
- Environment variables loaded from `.env`

### 4. API Routes

- **Chat Management** (`/chats`): Create, retrieve, delete chat sessions
- **WebSocket** (`/ws`): Real-time bidirectional communication
- **Settings** (`/settings`): Application configuration
- **Health** (`/health`): Service health checks

## Application Flow

1. **Startup**:
   - Load environment variables
   - Initialize logging
   - Setup WebSocket manager
   - Register API routes

2. **WebSocket Connection**:
   - Client connects to `/ws/omni/{chat_id}` or `/ws/capability/{chat_id}`
   - Load chat history from API
   - Initialize appropriate capability/omni instance
   - Setup input/output streams

3. **Message Processing**:
   - Receive message from client
   - Route to appropriate handler (start, stop, input_response, etc.)
   - Process with capability manager
   - Stream responses back to client

4. **Shutdown**:
   - Close all WebSocket connections
   - Cleanup managers
   - Flush logs

## Design Patterns

### Dependency Injection
FastAPI's dependency injection system manages:
- WebSocket manager instances
- Configuration objects
- Shared resources

### Singleton Pattern
Global manager instances ensure single connection pools:
- WebSocket manager
- Configuration cache

### Factory Pattern
Capability classes instantiated based on capability type from configuration.

### Observer Pattern
WebSocket connections observe capability execution and stream results in real-time.

## Running the Application

### Development
```bash
# From root directory
python main.py

# Or directly with uvicorn
uvicorn src.main:app --reload
```

### Production
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html
```

## Building

```bash
# Build executable with Nuitka
python scripts/build.py
```

## Import Structure

All imports within the `src/` directory use the `src.` prefix:

```python
# Correct
from src.configs.settings import settings
from src.managers.connection import WebSocketManager

# Incorrect
from configs.settings import settings
from managers.connection import WebSocketManager
```

The root `main.py` adds `src/` to the Python path for convenience when running from the root directory.

## Adding New Capabilities

1. Create new directory in `src/capabilities/`
2. Implement required files:
   - `manager.py` - Main capability class
   - `prompts.py` - Prompt templates
   - `response_format.py` - Response models
   - `__init__.py` - Package initialization

3. Register in `src/routers/ws.py`:
   ```python
   CAPABILITY_CLASS_MAP = {
       "your_capability": YourCapabilityClass,
   }
   ```

4. Add to `src/configs/settings.py` if needed

## Security Considerations

- JWT authentication via AWS Cognito
- CORS middleware configured
- Environment variables for sensitive data
- Input validation on all endpoints
- WebSocket connection verification

## Performance Optimization

- Connection pooling for WebSockets
- LLM configuration caching
- Async/await throughout
- Streaming responses for real-time feedback
- Background task processing

## Monitoring and Logging

- Structured logging with loguru
- Request/response logging
- Error tracking
- Health check endpoint
- Log rotation and archival
