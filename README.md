# Omni Backend

A FastAPI-based backend service providing AI-powered capabilities through WebSocket and REST APIs.

## Overview

Omni Backend is a modular FastAPI application that provides various AI-powered capabilities including:
- Python development assistance
- File finding and management
- Email management
- Image generation
- Browser automation

## Architecture

```
omni-backend/
├── src/                    # Main application source code
│   ├── capabilities/      # AI capability modules
│   ├── configs/           # Configuration management
│   ├── managers/          # Connection and session managers
│   ├── routers/           # API route definitions
│   ├── utilities/         # Helper utilities and common functions
│   └── omni/              # Core omni logic and handlers
├── scripts/               # Build and deployment scripts
├── docs/                  # Documentation
├── templates/             # HTML templates for WebSocket UI
└── logs/                  # Application logs (gitignored)
```

## Features

- **WebSocket Support**: Real-time bidirectional communication
- **Multiple AI Capabilities**: Modular capability system for different AI tasks
- **CORS Enabled**: Cross-origin resource sharing for web clients
- **Health Monitoring**: Built-in health check endpoints
- **Comprehensive Logging**: Structured logging with file rotation
- **JWT Authentication**: AWS Cognito integration for secure access

## Prerequisites

- Python 3.9+
- Virtual environment (recommended)
- Required dependencies (see [requirements.txt](requirements.txt))

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd omni-backend
```

2. Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

## Configuration

Create a `.env` file in the root directory with the following variables:

```env
# Application Settings
PORT=8000
PROJECT_NAME="Omni Backend"

# API Keys (add as needed)
OPENAI_API_KEY=your_key_here

# AWS Cognito (if using authentication)
AWS_REGION=us-east-1
COGNITO_USER_POOL_ID=your_pool_id
```

## Running the Application

### Development Mode

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### Production Mode

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API Documentation

Once the application is running, access the interactive API documentation at:

- Swagger UI: `http://localhost:8000/autogen/api/v1/docs`
- WebSocket Test UI: `http://localhost:8000/`
- Capability Test UI: `http://localhost:8000/capability`

## API Endpoints

### Health Check
- `GET /health` - Service health status

### Chat Management
- `POST /chats` - Create new chat session
- `GET /chats/{id}` - Get chat details
- `DELETE /chats/{id}` - Delete chat session

### WebSocket
- `WS /ws/omni/{chat_id}` - WebSocket connection for Omni
- `WS /ws/capability/{chat_id}` - WebSocket connection for specific capabilities

### Settings
- `GET /settings` - Get application settings
- `PUT /settings` - Update application settings

## Available Capabilities

1. **Python Developer** - Code generation and Python development assistance
2. **File Finder** - Intelligent file search and management
3. **Email Manager** - Email composition and management
4. **Image Generator** - AI-powered image generation
5. **Browser Manager** - Web scraping and browser automation

## Development

### Pre-commit Hooks

This project uses pre-commit hooks for code quality. See [docs/pre-commit-guide.md](docs/pre-commit-guide.md) for setup instructions.

```bash
pre-commit install
pre-commit run --all-files
```

### Building Executables

Build scripts are available in the `scripts/` directory for creating standalone executables using Nuitka. See [docs/build-guide.md](docs/build-guide.md) for detailed instructions.

```bash
# Full build
python scripts/build.py

# Or quick optimized build
python scripts/build_scripts/nuitka_optimized.py
```

## Project Structure

- **src/capabilities/** - Modular AI capabilities with managers, prompts, and response formats
- **src/configs/** - Application configuration and settings
- **src/managers/** - Connection pooling, WebSocket management, and session handling
- **src/routers/** - FastAPI route definitions organized by feature
- **src/utilities/** - Common utilities for logging, storage, API clients, etc.
- **src/omni/** - Core application logic including memory management and capability orchestration
- **scripts/** - Build and deployment scripts
- **docs/** - Documentation files
- **templates/** - HTML templates for WebSocket testing

## Documentation

- [Architecture Guide](docs/architecture.md) - Detailed architecture and design patterns
- [Build Guide](docs/build-guide.md) - How to build standalone executables
- [Signing Guide](docs/signing-guide.md) - macOS code signing and notarization
- [Pre-commit Guide](docs/pre-commit-guide.md) - Code quality tooling setup

## Testing

```bash
pytest
```

## Logging

Logs are stored in the `logs/` directory with automatic rotation. Configure logging settings in [src/utilities/logging.py](src/utilities/logging.py).

## Contributing

1. Create a feature branch
2. Make your changes
3. Run pre-commit hooks
4. Submit a pull request

## License

[Add your license here]

## Support

For issues and questions, please open an issue in the repository.
