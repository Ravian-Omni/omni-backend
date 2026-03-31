"""SQLite database connection manager for local persistence.

Provides async SQLite connection management with automatic schema creation,
WAL mode for concurrent access, and singleton pattern for connection reuse.
"""

import os

import aiosqlite
from loguru import logger

from src.configs.settings import settings

_db: aiosqlite.Connection | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    collection TEXT NOT NULL,
    chat_dir TEXT,
    call_id TEXT,
    capability_id TEXT,
    messages TEXT NOT NULL DEFAULT '[]',
    raw_messages TEXT NOT NULL DEFAULT '[]',
    feedback TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chats_chat_id ON chats(chat_id);
CREATE INDEX IF NOT EXISTS idx_chats_user_collection ON chats(user_id, collection);
CREATE INDEX IF NOT EXISTS idx_chats_call_capability ON chats(chat_id, call_id, capability_id);

CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    agent_name TEXT NOT NULL DEFAULT 'unknown',
    model_name TEXT NOT NULL,
    provider TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_estimate REAL DEFAULT 0.0,
    capability TEXT,
    step_number INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_token_usage_chat_id ON token_usage(chat_id);

CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    first_name TEXT DEFAULT '',
    last_name TEXT DEFAULT '',
    email TEXT DEFAULT '',
    dob TEXT DEFAULT '',
    gender TEXT DEFAULT '',
    country TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    provider TEXT PRIMARY KEY,
    api_key TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _get_db_path() -> str:
    """Get the database file path, creating the directory if needed."""
    db_dir = settings.ROOT_DIR
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "ravian.db")


async def init_db() -> None:
    """Initialize the SQLite database connection and create tables."""
    global _db

    db_path = _get_db_path()
    logger.info(f"Initializing SQLite database at {db_path}")

    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row

    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")

    await _db.executescript(SCHEMA_SQL)
    await _db.commit()

    logger.info("SQLite database initialized successfully")


async def get_db() -> aiosqlite.Connection:
    """Get the database connection, initializing if needed."""
    global _db
    if _db is None:
        await init_db()
    return _db


async def close_db() -> None:
    """Close the database connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("SQLite database connection closed")
