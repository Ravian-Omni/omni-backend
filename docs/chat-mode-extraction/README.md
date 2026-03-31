# Chat Mode Extraction Guide

## Overview

This guide explains how to extract the Chat Mode functionality from `omni-backend` into a standalone microservice optimized for AWS ECS deployment.

## Architecture Comparison

### Current Architecture (Monolithic)
```
┌─────────────────────────────────────────────────────────────┐
│                     OMNI-BACKEND                            │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Omni Mode   │  │  Chat Mode   │  │ Capabilities │      │
│  │  (Complex)   │  │  (Simple)    │  │  (Browser,   │      │
│  │              │  │              │  │   Email...)  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                             │
│  Shared: Settings, WebSocket Manager, Services, Utilities   │
└─────────────────────────────────────────────────────────────┘
```

### Target Architecture (Microservices)
```
┌─────────────────────────┐     ┌─────────────────────────┐
│    OMNI-BACKEND         │     │    CHAT-SERVICE         │
│    (AWS ECS)            │     │    (AWS ECS)            │
├─────────────────────────┤     ├─────────────────────────┤
│  • Omni Mode            │     │  • Chat Mode Only       │
│  • Capabilities         │     │  • Lightweight          │
│  • Complex Workflows    │     │  • Fast Startup         │
└───────────┬─────────────┘     └───────────┬─────────────┘
            │                               │
            └───────────┬───────────────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │   Shared Backend    │
              │   (MongoDB API)     │
              └─────────────────────┘
```

## Files to Extract

### Core Chat Mode Files

```
src/
├── chat/                          # 🔴 EXTRACT ENTIRE FOLDER
│   ├── __init__.py
│   ├── manager.py                 # Main Chat orchestrator
│   ├── prompts.py                 # Chat prompts
│   └── tools/                     # Chat-specific tools
│       ├── brave.py               # Web search
│       ├── composio.py            # Composio integration
│       └── together_image.py      # Image generation
│
├── routers/
│   ├── chat.py                    # 🟡 EXTRACT chat_mode routes only
│   └── websocket.py               # 🟡 EXTRACT chat websocket only
│
├── services/
│   ├── chat_service.py            # 🟡 EXTRACT chat_mode methods only
│   └── websocket_service.py       # 🟡 EXTRACT load_chat_mode_history
│
├── managers/
│   └── connection.py              # 🟡 EXTRACT chat_mode_initiate method
│
├── configs/                       # 🔴 EXTRACT (simplified)
│   ├── settings.py
│   ├── routes.py
│   ├── datetime_utils.py
│   ├── llm_configs_manager.py
│   └── system_ai_config.py
│
├── utilities/                     # 🔴 EXTRACT ENTIRE FOLDER
│   ├── api_client.py
│   ├── async_helpers.py
│   ├── logging.py
│   └── storage.py
│
├── schemas/                       # 🟡 EXTRACT chat-related schemas
│   └── chat.py
│
├── dependencies.py                # 🔴 EXTRACT (simplified)
└── main.py                        # 🔴 CREATE NEW (simplified)
```

## Step-by-Step Extraction Process

### Step 1: Create New Project Structure

```bash
mkdir -p chat-service/src/{chat,routers,services,managers,configs,utilities,schemas}
mkdir -p chat-service/{templates,logs,docs,tests}
```

### Step 2: Copy Core Dependencies

See `project-structure.md` for the complete file structure.

### Step 3: Simplify Configuration

See `simplified-settings.md` for the streamlined settings.

### Step 4: Create Dockerfile

See `Dockerfile` in this directory.

### Step 5: AWS ECS Configuration

See `aws-ecs-config.md` for deployment configuration.

## Dependencies (Minimal)

```txt
# requirements.txt for chat-service
aiofiles==24.1.0
autogen==0.9.7
certifi
fastapi==0.116.1
httpx==0.28.1
loguru==0.7.3
nest_asyncio==1.6.0
openai==2.3.0
pydantic==2.11.7
python-dotenv==1.1.1
uvicorn==0.34.3
websockets==15.0.1
together==1.5.21
```

## API Endpoints (Chat Service)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chats/new` | Create new chat session |
| `GET` | `/chats/history/{user_id}/{chat_id}` | Get chat history |
| `WS` | `/ws/chat/{chat_id}` | WebSocket for chat |
| `GET` | `/health` | Health check |

## Environment Variables

```env
# Required
PORT=8000
BACKEND_URL=https://api.your-backend.com

# Optional
LOG_LEVEL=INFO
BRAVE_API_KEY=your_brave_api_key
TOGETHER_API_KEY=your_together_api_key
```

## Quick Start

```bash
# Local development
cd chat-service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py

# Docker
docker build -t chat-service .
docker run -p 8000:8000 --env-file .env chat-service
```
