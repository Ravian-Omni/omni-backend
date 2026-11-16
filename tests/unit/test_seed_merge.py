"""Appending a local DAXAGENT's data to the hosted one (DAXAGENT_SEED_MODE=merge): new chats come with their rows and
files, everything already there stays as it is, and every chat goes to the owner."""

import os
import sqlite3
import tarfile

from src import seed


def database(path, chats, prefs=()):
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE chats (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, chat_id TEXT, title TEXT, chat_dir TEXT);
                        CREATE TABLE artifacts (id TEXT PRIMARY KEY, chat_id TEXT, path TEXT);
                        CREATE TABLE decision_log (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, card TEXT);
                        CREATE TABLE user_prefs (user_id TEXT, key TEXT, value TEXT, PRIMARY KEY (user_id, key));""")
    for chat_id, user, title, root in chats:
        db.execute("INSERT INTO chats (user_id, chat_id, title, chat_dir) VALUES (?, ?, ?, ?)", (user, chat_id, title, f"{root}/tasks/{chat_id}"))
        db.execute("INSERT INTO artifacts VALUES (?, ?, ?)", (f"a-{chat_id}", chat_id, f"{root}/tasks/{chat_id}/a.json"))
        db.execute("INSERT INTO decision_log (chat_id, card) VALUES (?, 'confirm_spend')", (chat_id,))
    db.executemany("INSERT INTO user_prefs VALUES (?, ?, ?)", prefs)
    db.commit()
    db.close()


def test_new_chats_are_appended_with_their_rows_and_files_and_nothing_there_changes(tmp_path, monkeypatch):
    local, hosted = tmp_path / "local", tmp_path / "hosted"
    for d in (local / "tasks" / "c1", local / "tasks" / "c2", hosted / "tasks" / "c1"):
        d.mkdir(parents=True)
    (local / "tasks" / "c1" / "a.json").write_text("local copy")
    (local / "tasks" / "c2" / "a.json").write_text("only local")
    (hosted / "tasks" / "c1" / "a.json").write_text("hosted copy")
    database(local / "daxagent.db", [("c1", "local_user", "local title", str(local)), ("c2", "local_user", "new chat", str(local))],
             [("local_user", "memory", "local"), ("local_user", "agents", "local agents")])
    database(hosted / "daxagent.db", [("c1", "user_OWNER", "hosted title", str(hosted))], [("user_OWNER", "memory", "hosted")])
    (local / "seed-root.txt").write_text(str(local))
    with tarfile.open(hosted / seed.ARCHIVE, "w:gz") as tar:
        for name in ("daxagent.db", "tasks", "seed-root.txt"):
            tar.add(local / name, arcname=name)
    monkeypatch.setenv("DAXAGENT_SEED_MODE", "merge")
    monkeypatch.setenv("DAXAGENT_OWNER", "user_OWNER")

    assert seed.apply_pending(str(hosted))
    db = sqlite3.connect(hosted / "daxagent.db")
    assert db.execute("SELECT chat_id, user_id, title FROM chats ORDER BY id").fetchall() == [
        ("c1", "user_OWNER", "hosted title"), ("c2", "user_OWNER", "new chat")]  # c1 untouched, c2 added for the owner
    assert db.execute("SELECT path FROM artifacts WHERE chat_id = 'c2'").fetchone()[0] == f"{hosted}/tasks/c2/a.json"
    assert db.execute("SELECT count(*) FROM decision_log").fetchone()[0] == 2  # c2's card, under a new id
    assert dict(db.execute("SELECT key, value FROM user_prefs")) == {"memory": "hosted", "agents": "local agents"}
    assert (hosted / "tasks" / "c1" / "a.json").read_text() == "hosted copy"  # no file overwritten
    assert (hosted / "tasks" / "c2" / "a.json").read_text() == "only local"
    assert not (hosted / seed.ARCHIVE).exists() and not any(n.startswith("seed-incoming") for n in os.listdir(hosted))
    assert not seed.apply_pending(str(hosted))  # applied once
