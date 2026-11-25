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

CREATE TABLE IF NOT EXISTS shared_chats (
    token TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    collection TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);

-- MCP servers the user added at runtime (the bundled ones live in
-- configs/mcp_servers.json). `config` holds the same JSON shape as one entry
-- of that file, so both sources are read the same way.
CREATE TABLE IF NOT EXISTS mcp_servers (
    name TEXT PRIMARY KEY,
    config TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Per-tool overrides: how a tool is classed for confirmation (read | spend | send)
-- and which personas may use it. Applies to bundled and runtime servers alike.
CREATE TABLE IF NOT EXISTS mcp_tool_settings (
    server TEXT NOT NULL,
    tool TEXT NOT NULL,
    tool_class TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (server, tool)
);

-- User switches per MCP server (bundled or runtime): off means no persona, chat or planner sees it.
CREATE TABLE IF NOT EXISTS mcp_server_flags (
    name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

-- Every confirmation card an agent showed and what the user answered.
CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    task_id TEXT,
    persona TEXT NOT NULL,
    card TEXT NOT NULL,
    request TEXT NOT NULL,
    response TEXT,
    created_at TEXT NOT NULL,
    answered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_decision_log_chat_id ON decision_log(chat_id);

-- Links in sent emails, each with the recipient it was made for, and the clicks on them.
CREATE TABLE IF NOT EXISTS tracked_links (
    token TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    recipient TEXT NOT NULL,
    plan_id TEXT,
    step INTEGER,
    subject TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS link_clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL,
    clicked_at TEXT NOT NULL
);

-- Runs that began and have not ended. One still here after its process is gone was cut short and resumes at the next start.
CREATE TABLE IF NOT EXISTS active_runs (
    chat_id TEXT PRIMARY KEY,
    owner_pid INTEGER NOT NULL,
    task TEXT NOT NULL,
    files TEXT NOT NULL DEFAULT '[]',
    resumes INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL
);

-- Runs waiting behind the one on their chat, or for a free slot, oldest first.
CREATE TABLE IF NOT EXISTS run_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    run_key TEXT NOT NULL,
    task TEXT NOT NULL,
    files TEXT NOT NULL DEFAULT '[]',
    lead_target INTEGER NOT NULL DEFAULT 0,
    credit_budget REAL,
    created_at TEXT NOT NULL
);

-- Each task started over /hands/mcp (contract [26]), kept so its id and state survive a restart: one chat may hold many.
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    run_key TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    agenda_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    step TEXT NOT NULL DEFAULT '',
    waiting_on TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    last_progress_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tasks_key ON tasks(run_key, started_at);
CREATE INDEX IF NOT EXISTS idx_tasks_chat ON tasks(chat_id, started_at);

-- Credits a goal may still spend without asking, per agenda (per chat when it has none).
CREATE TABLE IF NOT EXISTS budgets (
    scope TEXT PRIMARY KEY,
    credits_left REAL NOT NULL,
    updated_at TEXT NOT NULL
);

-- Addresses no campaign may write to again (an unsubscribe, a bounce), for every later run.
CREATE TABLE IF NOT EXISTS suppressions (
    user_id TEXT NOT NULL,
    email TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, email)
);

-- What each paid data call cost: dollars for treg (removed, kept as history), credits for a Data Axle enrichment (the most it can take).
CREATE TABLE IF NOT EXISTS data_spend (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    at TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    usd REAL NOT NULL,
    call_id TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    email_status TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_data_spend_chat ON data_spend(chat_id, at);

-- Email addresses a data source's own answer held in a chat (Data Axle): only these get DAXAGENT's in-house email check.
CREATE TABLE IF NOT EXISTS source_emails (
    chat_id TEXT NOT NULL,
    email TEXT NOT NULL,
    server TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (chat_id, email)
);

-- Notices pushed to Brain_Hands from the reply-check round (a referral email, a booked meeting): each once.
CREATE TABLE IF NOT EXISTS pushed_notices (
    id TEXT PRIMARY KEY,
    pushed_at TEXT NOT NULL
);

-- Typed outputs a persona produced (lead list, buyer map, campaign plan, ...).
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    task_id TEXT,
    persona TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    path TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_chat_id ON artifacts(chat_id);

-- What each user tells the agents to know and do (memory, per-agent instructions, workflows).
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- The user's rating of a finished run ("How was your experience?"), bound to its conversation
-- (chat_id) and run (task_id); rating the same run again replaces it.
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    task_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (chat_id, task_id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_chat_id ON feedback(chat_id);

-- Replies a person on the team must answer, from the Inbox Agent: one row per reply thread,
-- reopened when the contact writes again. read = Jev's answers (JSON); draft = the suggested reply.
CREATE TABLE IF NOT EXISTS handoffs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    plan_id TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL,
    thread_id TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    route TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    reply TEXT NOT NULL,
    read TEXT NOT NULL DEFAULT '{}',
    draft TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'claimed', 'sent', 'done')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (chat_id, contact, thread_id)
);

CREATE INDEX IF NOT EXISTS idx_handoffs_status ON handoffs(user_id, status);

-- Ad creatives the user uploads for a campaign plan: read by Campaign Builder for the copy (summary),
-- attached to chosen steps, linked (url) or shown inside the email (url, images only).
CREATE TABLE IF NOT EXISTS creatives (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    name TEXT NOT NULL,
    mime TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_creatives_plan ON creatives(chat_id, plan_id);

-- Conversations the user deleted from the sidebar: kept in history, never listed again.
CREATE TABLE IF NOT EXISTS hidden_chats (
    chat_id TEXT PRIMARY KEY,
    hidden_at TEXT NOT NULL
);

-- Sign-in for the hosted app (src/auth.py): accounts and their live sessions; one shared workspace.
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- Bearer keys made in Settings > Connections > DAX MCP, for outside agents calling /hands/mcp.
CREATE TABLE IF NOT EXISTS hands_keys (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    last_client TEXT
);

-- Who each signed-in person is. Clerk's session token names only the user id, so the app reports the person's
-- email and name when it opens (PUT /auth/me). Labels for the admin dashboard; never used to decide access.
CREATE TABLE IF NOT EXISTS accounts (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    place TEXT PRIMARY KEY,
    lat REAL,
    lng REAL,
    resolved_at TEXT NOT NULL
);

-- LLM as judge (src/judge.py): one row per verdict on one turn, never overwritten, so judge versions can be compared.
CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    task_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    request TEXT NOT NULL DEFAULT '',
    turn_at TEXT NOT NULL DEFAULT '',
    judge_version TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    ground_truth TEXT NOT NULL DEFAULT '',  -- "<case id>@<version>" it was compared against; '' when none
    relevancy REAL NOT NULL,
    completeness REAL NOT NULL,
    tool_selection REAL NOT NULL,
    final_score REAL NOT NULL,
    severity TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    failing_step INTEGER NOT NULL DEFAULT -1,
    rationale TEXT NOT NULL DEFAULT '',
    suggested_fix TEXT NOT NULL DEFAULT '',
    facts TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eval_results_turn ON eval_results(chat_id, task_id);

-- Expected answers curated by Data Axle: one row per version of a case; editing or retiring adds a version.
CREATE TABLE IF NOT EXISTS ground_truth (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    request TEXT NOT NULL,
    expected_agents TEXT NOT NULL DEFAULT '[]',
    expected_answer TEXT NOT NULL DEFAULT '',
    query_class TEXT NOT NULL DEFAULT '',
    source_chat_id TEXT NOT NULL DEFAULT '',
    source_task_id TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    retired INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (case_id, version)
);

-- The gate: each run replays the planner on the expected answers with one person's prompts and cards (config).
CREATE TABLE IF NOT EXISTS suite_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    config_version TEXT NOT NULL,
    config TEXT NOT NULL,
    cases INTEGER NOT NULL,
    passed INTEGER NOT NULL,
    score REAL NOT NULL,
    results TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _get_db_path() -> str:
    """Get the database file path, creating the directory if needed."""
    db_dir = settings.ROOT_DIR
    os.makedirs(db_dir, exist_ok=True)
    os.chmod(db_dir, 0o700)  # it holds sign-in tokens and API keys: only this user may read it
    return os.path.join(db_dir, "daxagent.db")


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
    try:  # databases made before last_client existed
        await _db.execute("ALTER TABLE hands_keys ADD COLUMN last_client TEXT")
    except aiosqlite.OperationalError:
        pass  # already there
    try:  # databases made before cards recorded the process that shows them
        await _db.execute("ALTER TABLE decision_log ADD COLUMN owner_pid INTEGER")
    except aiosqlite.OperationalError:
        pass  # already there
    for column in ("title_by", "title_basis"):  # databases made before titles followed the work: who set it ("user" or "auto"), what it was made from
        try:
            await _db.execute(f"ALTER TABLE chats ADD COLUMN {column} TEXT")
        except aiosqlite.OperationalError:
            pass  # already there
    try:  # databases made before Data Axle credit spends were recorded here
        await _db.execute("ALTER TABLE data_spend ADD COLUMN credits REAL NOT NULL DEFAULT 0")
    except aiosqlite.OperationalError:
        pass  # already there
    try:  # databases made before chats had a title
        await _db.execute("ALTER TABLE chats ADD COLUMN title TEXT")
    except aiosqlite.OperationalError:
        pass  # already there
    # Data made while everyone was "local_user" (local runs, the shared workspace, the Teams and Slack bots) goes to
    # the hosted app's owner: DAXAGENT_OWNER, their Clerk user id or email. Never set it on a local run.
    owner = os.getenv("DAXAGENT_OWNER", "")
    for table in ("chats", "user_prefs", "feedback", "handoffs", "shared_chats") if owner else ():
        moved = await _db.execute(f"UPDATE OR IGNORE {table} SET user_id = ? WHERE user_id = 'local_user'", (owner,))
        if moved.rowcount:
            logger.info(f"[owner] {moved.rowcount} {table} rows moved from local_user to {owner}")
    await _db.commit()
    from src.database.copy_account import copy_requested

    await copy_requested(_db)  # DAXAGENT_COPY_ACCOUNT: one account's data copied to another, once

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
