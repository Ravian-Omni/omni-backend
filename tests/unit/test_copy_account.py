"""DAXAGENT_COPY_ACCOUNT copies an account's data to another as copies of their own, once."""

import asyncio
import json
import os

from src.database import connection


def _run(sql, *args):
    async def go():
        db = await connection.get_db()
        cur = await db.execute(sql, args)
        rows = [tuple(r) for r in await cur.fetchall()]
        await db.commit()
        return rows
    return asyncio.run(go())


def test_copy_gives_the_receiver_its_own_chats_once(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    monkeypatch.delenv("DAXAGENT_COPY_ACCOUNT", raising=False)
    monkeypatch.delenv("DAXAGENT_OWNER", raising=False)
    asyncio.run(connection.init_db())

    chat, odd = "56d8fed1-6cf5-4a91-b58a-94a70da3e783", "sd-direct"
    art_file, cre_file = tmp_path / "lead_list-95dee66c.json", tmp_path / "creative-292dd549-banner.png"
    art_file.write_text("[]")
    cre_file.write_bytes(b"png")
    msgs = json.dumps([{"chat": chat, "artifact": "lead_list-95dee66c", "path": str(art_file), "also": odd}])
    for cid in (chat, odd):
        _run("INSERT INTO chats (user_id, chat_id, collection, chat_dir, messages, raw_messages, created_at, updated_at) "
             "VALUES ('user_a', ?, 'omni', ?, ?, ?, 'now', 'now')", cid, str(tmp_path), msgs, msgs)
    _run("INSERT INTO artifacts VALUES ('lead_list-95dee66c', ?, 't1', 'lead_finder', 'lead_list', 'Leads', ?, 0, NULL, 'now')", chat, str(art_file))
    _run("INSERT INTO creatives VALUES ('creative-292dd549', ?, 'p1', 'banner', 'image/png', ?, 3, '', '', 'now')", chat, str(cre_file))
    _run("INSERT INTO decision_log (chat_id, persona, card, request, created_at) VALUES (?, 'x', 'c', '{\"a\": \"lead_list-95dee66c\"}', 'now')", chat)
    _run("INSERT INTO hidden_chats VALUES (?, 'now')", odd)
    _run("INSERT INTO feedback (chat_id, task_id, user_id, rating, description, created_at) VALUES (?, '', 'user_a', 5, '', 'now')", chat)
    _run("INSERT INTO user_prefs VALUES ('user_a', 'memory', '{\"x\": 1}', 'now'), ('user_a', 'agents', '{\"theirs\": 1}', 'now'), "
         "('user_b', 'agents', '{\"mine\": 1}', 'now')")
    asyncio.run(connection.close_db())

    monkeypatch.setenv("DAXAGENT_COPY_ACCOUNT", "user_a:user_b")
    for _ in range(2):  # the second start must not copy again
        asyncio.run(connection.init_db())
        asyncio.run(connection.close_db())

    mine = _run("SELECT chat_id, messages, raw_messages FROM chats WHERE user_id = 'user_b'")
    assert len(mine) == 2 and not {c for c, _, _ in mine} & {chat, odd}
    text = " ".join(m + r for _, m, r in mine)
    assert chat not in text and '"lead_list-95dee66c"' not in text and f'"{odd}"' not in text
    (art_id, art_path), = _run("SELECT id, path FROM artifacts WHERE chat_id != ?", chat)
    assert art_id.startswith("lead_list-95dee66c-") and art_id in text and art_path in text and os.path.isfile(art_path)
    (cre_path,), = _run("SELECT path FROM creatives WHERE chat_id != ?", chat)
    assert cre_path != str(cre_file) and os.path.isfile(cre_path)
    assert _run("SELECT request FROM decision_log WHERE chat_id != ?", chat) == [(json.dumps({"a": art_id}),)]
    assert len(_run("SELECT chat_id FROM hidden_chats")) == 2
    assert _run("SELECT COUNT(*) FROM feedback WHERE user_id = 'user_b'") == [(0,)]
    prefs = dict(_run("SELECT key, value FROM user_prefs WHERE user_id = 'user_b'"))
    assert prefs["memory"] == '{"x": 1}' and prefs["agents"] == '{"mine": 1}'  # theirs copied, the receiver's own kept
    assert _run("SELECT messages FROM chats WHERE user_id = 'user_a' AND chat_id = ?", chat) == [(msgs,)]  # original untouched

    # A chat started after the copy is copied on the next run, and nothing else again
    later = "11111111-2222-4333-8444-555555555555"
    _run("INSERT INTO chats (user_id, chat_id, collection, chat_dir, messages, raw_messages, created_at, updated_at) "
         "VALUES ('user_a', ?, 'chats', ?, '[\"mcp test\"]', '[]', 'now', 'now')", later, str(tmp_path))
    asyncio.run(connection.close_db())
    asyncio.run(connection.init_db())
    assert len(_run("SELECT chat_id FROM chats WHERE user_id = 'user_b'")) == 3
    assert _run("SELECT COUNT(*) FROM chats WHERE user_id = 'user_b' AND messages = '[\"mcp test\"]'") == [(1,)]
    assert _run("SELECT COUNT(*) FROM artifacts") == [(2,)]  # the first chat's artifact was not copied twice
    asyncio.run(connection.close_db())


def test_the_first_copys_marker_counts_what_it_had_copied(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    monkeypatch.delenv("DAXAGENT_COPY_ACCOUNT", raising=False)
    monkeypatch.delenv("DAXAGENT_OWNER", raising=False)
    asyncio.run(connection.init_db())
    for cid, created in (("aaaaaaaa-0000-4000-8000-000000000001", "2026-10-26 16:18:54.046125+00:00"),
                         ("aaaaaaaa-0000-4000-8000-000000000002", "2026-10-28T09:00:00+00:00")):
        _run("INSERT INTO chats (user_id, chat_id, collection, messages, raw_messages, created_at, updated_at) "
             "VALUES ('user_a', ?, 'chats', '[]', '[]', ?, ?)", cid, created, created)
    _run("INSERT INTO user_prefs VALUES ('user_b', 'copied_from:user_a', 'true', '2026-10-27 07:22:05')")  # the 2026-10-27 run
    asyncio.run(connection.close_db())
    monkeypatch.setenv("DAXAGENT_COPY_ACCOUNT", "user_a:user_b")
    asyncio.run(connection.init_db())
    assert _run("SELECT created_at FROM chats WHERE user_id = 'user_b'") == [("2026-10-28T09:00:00+00:00",)]
    (value,), = _run("SELECT value FROM user_prefs WHERE user_id = 'user_b' AND key = 'copied_from:user_a'")
    assert sorted(json.loads(value)) == ["aaaaaaaa-0000-4000-8000-000000000001", "aaaaaaaa-0000-4000-8000-000000000002"]
    asyncio.run(connection.close_db())
