"""Move a local DAXAGENT's data into the hosted one (Railway), once.

1. The archive of a local ~/.daxagent (made by scripts/seed_archive.sh) is uploaded to POST /admin/seed
   with the one-time token in DAXAGENT_SEED_TOKEN; it is stored as <data dir>/seed.tar.gz.
2. On the next start, before the database opens, it is unpacked into the data dir (what was there is
   kept in a backup folder) and every stored path is rewritten from the old root to the new one.
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


def apply_pending(data_dir: str) -> bool:
    """Unpack a waiting archive into data_dir and rewrite its paths; True when one was applied."""
    archive = os.path.join(data_dir, ARCHIVE)
    if not os.path.exists(archive):
        return False
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
