"""Local data uploaded to the hosted app is unpacked once, with its paths moved to the new data dir."""

import io
import json
import sqlite3
import tarfile

from src import seed


def test_archive_is_unpacked_paths_rewritten_and_old_data_kept(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "daxagent.db").write_text("old")  # what a first boot created
    src = tmp_path / "local"
    src.mkdir()
    db = sqlite3.connect(src / "daxagent.db")
    db.execute("CREATE TABLE chats (chat_dir TEXT, messages TEXT, raw_messages TEXT)")
    db.execute("CREATE TABLE artifacts (path TEXT)")
    db.execute("INSERT INTO chats VALUES (?, ?, ?)", ("/Users/me/.daxagent/tasks/T1", "[]", json.dumps({"path": "/Users/me/.daxagent/tasks/T1/a.json"})))
    db.execute("INSERT INTO artifacts VALUES ('/Users/me/.daxagent/tasks/T1/a.json')")
    db.commit()
    db.close()
    (src / seed.ROOT_MARKER).write_text("/Users/me/.daxagent")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(src / "daxagent.db", arcname="daxagent.db")
        tar.add(src / seed.ROOT_MARKER, arcname=seed.ROOT_MARKER)
    (data / seed.ARCHIVE).write_bytes(buf.getvalue())

    assert seed.apply_pending(str(data)) and not seed.apply_pending(str(data))  # once
    db = sqlite3.connect(data / "daxagent.db")
    chat_dir, raw = db.execute("SELECT chat_dir, raw_messages FROM chats").fetchone()
    assert chat_dir == f"{data}/tasks/T1" and f"{data}/tasks/T1/a.json" in raw
    assert db.execute("SELECT path FROM artifacts").fetchone()[0] == f"{data}/tasks/T1/a.json"
    backups = [p for p in data.iterdir() if p.name.startswith("before-seed-")]
    assert len(backups) == 1 and (backups[0] / "daxagent.db").read_text() == "old"
