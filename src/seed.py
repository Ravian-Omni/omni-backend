"""Move a local DAXAGENT's data into the hosted one (Railway), once.

1. The archive of a local ~/.daxagent (made by scripts/seed_archive.sh) is uploaded to POST /admin/seed
   with the one-time token in DAXAGENT_SEED_TOKEN; it is stored as <data dir>/seed.tar.gz.
2. On the next start, before the database opens, it is unpacked into the data dir (what was there is
   kept in a backup folder) and every stored path is rewritten from the old root to the new one.
   With DAXAGENT_SEED_MODE=merge it is appended instead (merge_pending): nothing there is replaced.
"""

import os
import shutil
import sqlite3
import tarfile
import time

from loguru import logger

ARCHIVE = "seed.tar.gz"
ROOT_MARKER = "seed-root.txt"  # inside the archive: the absolute path the data came from
# Columns that hold absolute paths (or text that embeds them)
PATH_COLUMNS = {"chats": ("chat_dir", "messages", "raw_messages"), "artifacts": ("path",), "creatives": ("path",)}


# Tables whose rows belong to a chat and come along with it in a merge (runtime state such as queues does not)
CHAT_TABLES = ("artifacts", "creatives", "decision_log", "eval_results", "feedback", "handoffs", "hidden_chats", "run_outcomes",
               "token_usage", "data_spend", "source_emails")
USER_TABLES = ("user_prefs", "suppressions")  # the hosted app's own rows win on a clash
PATHS = {(t, c) for t, cs in PATH_COLUMNS.items() for c in cs}


def apply_pending(data_dir: str) -> bool:
    """Unpack a waiting archive into data_dir and rewrite its paths; True when one was applied."""
    archive = os.path.join(data_dir, ARCHIVE)
    if not os.path.exists(archive):
        return False
    if os.getenv("DAXAGENT_SEED_MODE") == "merge":
        return merge_pending(data_dir)
    backup = os.path.join(data_dir, f"before-seed-{int(time.time())}")
    os.makedirs(backup)
    for name in os.listdir(data_dir):
        if name not in (ARCHIVE, os.path.basename(backup)) and not name.startswith("before-seed-"):
            shutil.move(os.path.join(data_dir, name), backup)
    with tarfile.open(archive) as tar:
        tar.extractall(data_dir, filter="data")
    marker = os.path.join(data_dir, ROOT_MARKER)
    old_root = open(marker).read().strip() if os.path.exists(marker) else ""
    if old_root and old_root != data_dir:
        db = sqlite3.connect(os.path.join(data_dir, "daxagent.db"))
        for table, columns in PATH_COLUMNS.items():
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                sets = ", ".join(f"{c} = REPLACE({c}, ?, ?)" for c in columns)
                db.execute(f"UPDATE {table} SET {sets}", [v for _ in columns for v in (old_root, data_dir)])
        db.commit()
        db.close()
    os.rename(archive, os.path.join(backup, ARCHIVE))
    logger.info(f"[seed] local data applied from {old_root or 'an unknown root'} into {data_dir}; previous data kept in {backup}")
    return True


def _copy_missing(src: str, dst: str) -> int:
    """Copy src's files into dst, never over a file that is already there; returns how many were copied."""
    copied = 0
    for root, _, files in os.walk(src):
        target = os.path.join(dst, os.path.relpath(root, src))
        os.makedirs(target, exist_ok=True)
        for name in files:
            if not os.path.exists(os.path.join(target, name)):
                shutil.copy2(os.path.join(root, name), os.path.join(target, name))
                copied += 1
    return copied


def merge_pending(data_dir: str) -> bool:
    """Append a waiting archive to what is here: the chats this database does not have yet, with their artifacts,
    cards, feedback and the rest, their files (no existing file is overwritten) and the archive's preferences where
    this database has none. Every chat is given to DAXAGENT_OWNER; nothing already here changes."""
    archive = os.path.join(data_dir, ARCHIVE)
    incoming = os.path.join(data_dir, f"seed-incoming-{int(time.time())}")
    with tarfile.open(archive) as tar:
        tar.extractall(incoming, filter="data")
    marker = os.path.join(incoming, ROOT_MARKER)
    old_root = open(marker).read().strip() if os.path.exists(marker) else ""
    owner = os.getenv("DAXAGENT_OWNER", "") or "local_user"
    db = sqlite3.connect(os.path.join(data_dir, "daxagent.db"))
    db.execute("ATTACH DATABASE ? AS incoming", (os.path.join(incoming, "daxagent.db"),))

    def columns(schema: str, table: str) -> list[tuple]:
        return db.execute(f"PRAGMA {schema}.table_info({table})").fetchall()

    def copy(table: str, where: str, args: tuple = ()) -> int:
        """Rows of the archive's table matching `where`, appended here: a new integer key, owner-given users, paths moved."""
        theirs = {c[1]: c for c in columns("incoming", table)}
        if not theirs or not columns("main", table):
            return 0
        mine = {c[1] for c in columns("main", table)}
        for name, c in theirs.items():  # a column this older database lacks yet: added, so nothing is dropped
            if name not in mine:
                db.execute(f'ALTER TABLE main.{table} ADD COLUMN "{name}" {c[2]}')
        keys = [c for c in theirs.values() if c[5]]
        new_key = len(keys) == 1 and keys[0][2].upper() == "INTEGER"  # an autoincrement id: this database gives a new one
        names = [n for n in theirs if not (new_key and n == keys[0][1])]
        values = []
        for n in names:
            v = f'"{n}"'
            if n == "user_id":
                v = f"CASE WHEN {v} IS NULL OR {v} = '' THEN {v} ELSE ? END"
            elif old_root and (table, n) in PATHS:
                v = f"REPLACE({v}, ?, ?)"
            values.append(v)
        params = [p for n in names for p in ((owner,) if n == "user_id" else (old_root, data_dir) if old_root and (table, n) in PATHS else ())]
        cols = ", ".join(f'"{n}"' for n in names)
        cur = db.execute(f"INSERT OR IGNORE INTO main.{table} ({cols}) SELECT {', '.join(values)} FROM incoming.{table} WHERE {where}",
                         (*params, *args))
        return cur.rowcount

    new = [r[0] for r in db.execute("SELECT DISTINCT chat_id FROM incoming.chats WHERE chat_id NOT IN (SELECT chat_id FROM main.chats)")]
    db.execute("CREATE TEMP TABLE new_chats (chat_id TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO new_chats VALUES (?)", [(c,) for c in new])
    counts = {"chats": copy("chats", "chat_id IN (SELECT chat_id FROM new_chats)")}
    for table in CHAT_TABLES:
        counts[table] = copy(table, "chat_id IN (SELECT chat_id FROM new_chats)")
    for table in USER_TABLES:
        counts[table] = copy(table, "1")
    db.commit()
    db.execute("DETACH DATABASE incoming")
    db.close()
    files = sum(_copy_missing(os.path.join(incoming, name), os.path.join(data_dir, name))
                for name in os.listdir(incoming) if os.path.isdir(os.path.join(incoming, name)))
    shutil.rmtree(incoming)
    os.rename(archive, os.path.join(data_dir, f"merged-{int(time.time())}-{ARCHIVE}"))
    logger.info(f"[seed] merged from {old_root or 'an unknown root'}: {counts}, {files} files; nothing existing was replaced")
    return True
