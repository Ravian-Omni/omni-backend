"""Copy one account's chats, tasks and agent settings to another account, as copies of their own.

DAXAGENT_COPY_ACCOUNT="<from user id>:<to user id>" (comma-separate several) runs it at start. A marker row in the
receiver's prefs lists the chats already copied, so running it again copies only the ones started since (settings
are copied the first time only). Each chat gets a new id, and so do its artifacts and
creatives (their files are copied under the new names); every reference to an old id in the copied messages,
records and paths is rewritten, so the two accounts never share a chat, an artifact, an approval or a live run.
Task folders stay where they are (both copies read them). Not copied: token usage, ratings, reply handoffs and
public share links, which belong to the original. The receiver's own settings win over the copied ones.
"""

import hashlib
import json
import os
import re
import shutil
import uuid

from loguru import logger

MARKER = "copied_from:"
SHAPED = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Za-z_]+-[0-9a-f]{8}(?![0-9a-f])")


async def copy_account(db, src: str, dst: str) -> dict[str, int]:
    """Copy src's chats not copied to dst yet (and, the first time, src's settings); returns what was copied."""
    marker = await (await db.execute("SELECT value, updated_at FROM user_prefs WHERE user_id = ? AND key = ?", (dst, MARKER + src))).fetchone()
    if marker is None:
        done: set[str] = set()
    elif marker[0] == "true":  # the first copy (2026-10-27) kept no list: it copied every chat started before it ran
        done = {c for (c,) in await (await db.execute(
            "SELECT chat_id FROM chats WHERE user_id = ? GROUP BY chat_id HAVING MIN(REPLACE(created_at, 'T', ' ')) <= ?",
            (src, marker[1]))).fetchall()}
    else:
        done = set(json.loads(marker[0]))
    chats = [c for c in await (await db.execute(
        "SELECT chat_id, collection, chat_dir, call_id, capability_id, messages, raw_messages, feedback, created_at, updated_at "
        "FROM chats WHERE user_id = ?", (src,))).fetchall() if c[0] not in done]
    if marker is not None and not chats:
        return {}
    chat_map = {c[0]: str(uuid.uuid4()) for c in chats}
    marks = ",".join("?" * len(chat_map)) or "''"
    old = list(chat_map)
    artifacts = await (await db.execute(
        f"SELECT id, chat_id, task_id, persona, kind, title, path, row_count, source, created_at FROM artifacts WHERE chat_id IN ({marks})", old)).fetchall()
    creatives = await (await db.execute(
        f"SELECT id, chat_id, plan_id, name, mime, path, size, url, summary, created_at FROM creatives WHERE chat_id IN ({marks})", old)).fetchall()
    decisions = await (await db.execute(
        f"SELECT chat_id, task_id, persona, card, request, response, created_at, answered_at FROM decision_log WHERE chat_id IN ({marks})", old)).fetchall()
    hidden = await (await db.execute(f"SELECT chat_id, hidden_at FROM hidden_chats WHERE chat_id IN ({marks})", old)).fetchall()
    prefs = [] if marker is not None else await (await db.execute(
        "SELECT key, value, updated_at FROM user_prefs WHERE user_id = ? AND key NOT LIKE ?", (src, MARKER + "%"))).fetchall()

    tag = hashlib.sha1(dst.encode()).hexdigest()[:6]  # the same for every copy to dst, so ids stay readable
    ids = {**chat_map, **{a[0]: f"{a[0]}-{tag}" for a in artifacts}, **{c[0]: f"{c[0]}-{tag}" for c in creatives}}
    # Ids have two shapes (chat UUIDs, "lead_list-95dee66c"), found in one fast pass; the odd few are matched by name.
    odd = [i for i in ids if not SHAPED.fullmatch(i)]
    odd_pattern = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(sorted(map(re.escape, odd), key=len, reverse=True)) + r")(?![A-Za-z0-9])") if odd else None

    def remap(text):
        if not isinstance(text, str):
            return text
        text = SHAPED.sub(lambda m: ids.get(m.group(0), m.group(0)), text)
        return odd_pattern.sub(lambda m: ids[m.group(1)], text) if odd_pattern else text

    def copy_file(path: str) -> str:
        new = remap(path)
        if new != path and os.path.isfile(path) and not os.path.exists(new):
            shutil.copy2(path, new)
        return new

    try:
        for c in chats:
            await db.execute(
                "INSERT INTO chats (user_id, chat_id, collection, chat_dir, call_id, capability_id, messages, raw_messages, feedback, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (dst, chat_map[c[0]], c[1], c[2], c[3], c[4], remap(c[5]), remap(c[6]), remap(c[7]), c[8], c[9]))
        for a in artifacts:
            await db.execute(
                "INSERT INTO artifacts (id, chat_id, task_id, persona, kind, title, path, row_count, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ids[a[0]], chat_map[a[1]], a[2], a[3], a[4], a[5], copy_file(a[6]), a[7], remap(a[8]), a[9]))
        for c in creatives:
            await db.execute(
                "INSERT INTO creatives (id, chat_id, plan_id, name, mime, path, size, url, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ids[c[0]], chat_map[c[1]], c[2], c[3], c[4], copy_file(c[5]), c[6], c[7], c[8], c[9]))
        for d in decisions:
            await db.execute(
                "INSERT INTO decision_log (chat_id, task_id, persona, card, request, response, created_at, answered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_map[d[0]], d[1], d[2], remap(d[3]), remap(d[4]), remap(d[5]), d[6], d[7]))
        for h in hidden:
            await db.execute("INSERT OR IGNORE INTO hidden_chats (chat_id, hidden_at) VALUES (?, ?)", (chat_map[h[0]], h[1]))
        for p in prefs:
            await db.execute("INSERT OR IGNORE INTO user_prefs (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)", (dst, p[0], p[1], p[2]))
        await db.execute("INSERT OR REPLACE INTO user_prefs (user_id, key, value, updated_at) VALUES (?, ?, ?, datetime('now'))",
                         (dst, MARKER + src, json.dumps(sorted(done | set(chat_map)))))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    counts = {"chats": len(chat_map), "artifacts": len(artifacts), "creatives": len(creatives),
              "decisions": len(decisions), "hidden": len(hidden), "settings": len(prefs)}
    logger.info(f"[copy] {src} -> {dst}: {counts}")
    return counts


async def copy_requested(db) -> None:
    """The copies DAXAGENT_COPY_ACCOUNT asks for; a failed one is logged and rolled back, the app still starts."""
    for pair in filter(None, (p.strip() for p in os.getenv("DAXAGENT_COPY_ACCOUNT", "").split(","))):
        src, _, dst = pair.partition(":")
        if not (src and dst) or src == dst:
            logger.warning(f"[copy] ignored '{pair}': expected <from user id>:<to user id>")
            continue
        try:
            await copy_account(db, src, dst)
        except Exception:
            logger.exception(f"[copy] {src} -> {dst} failed; nothing was copied")
