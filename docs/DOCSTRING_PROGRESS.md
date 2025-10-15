# Docstring Addition Progress

## Docstring Standard
- **Style**: Google-style docstrings
- **Tool**: pydocstyle with `--convention=google`
- **Checker**: Added to `.pre-commit-config.yaml`

## Files Status

### Core Files
- [ ] `src/main.py` - Main application entry point
- [ ] `src/dependencies.py` - Dependency injection

### Routers
- [ ] `src/routers/chat.py` - Chat management endpoints
- [ ] `src/routers/config.py` - Configuration endpoints
- [ ] `src/routers/ws.py` - WebSocket endpoints

### Managers
- [ ] `src/managers/connection.py` - WebSocket connection management
- [ ] `src/managers/cancellation_token.py` - Cancellation token handling

### Utilities
- [ ] `src/utilities/async_helpers.py` - Async utility functions
- [ ] `src/utilities/custom_manager.py` - Custom manager utilities
- [ ] `src/utilities/logging.py` - Logging configuration
- [ ] `src/utilities/storage.py` - Storage utilities
- [ ] `src/utilities/api_client.py` - API client wrapper
- [ ] `src/utilities/venv_config.py` - Virtual environment configuration

### Configurations
- [ ] `src/configs/settings.py` - Application settings
- [ ] `src/configs/llm_configs_manager.py` - LLM configuration management
- [ ] `src/configs/system_ai_config.py` - System AI configuration

### Capabilities
- [ ] `src/capabilities/browser_manager/manager.py`
- [ ] `src/capabilities/email_manager/manager.py`
- [ ] `src/capabilities/file_finder/manager.py`
- [ ] `src/capabilities/image_generator/manager.py`
- [ ] `src/capabilities/python_developer/manager.py`
- [ ] `src/capabilities/python_developer/executor.py`

### Omni Core
- [ ] `src/omni/manager.py` - Main omni manager
- [ ] `src/omni/memory.py` - Memory management
- [ ] `src/omni/capability_manager.py` - Capability orchestration
- [ ] `src/omni/response_format.py` - Response formatting
- [ ] `src/omni/omni_handlers.py` - Event handlers

## Commands

Check missing docstrings:
```bash
python3 add_docstrings.py
```

Check docstring style:
```bash
pydocstyle src/ --convention=google
```

Run pre-commit with docstring checks:
```bash
pre-commit run pydocstyle --all-files
```

## Guidelines

1. Every module needs a module docstring
2. Every class needs a docstring
3. Every public function/method needs a docstring
4. Private functions (_func) need docstrings if complex
5. Use Google-style format
6. Keep under 88 characters per line (black standard)

See [docs/docstring-style-guide.md](docs/docstring-style-guide.md) for examples.
