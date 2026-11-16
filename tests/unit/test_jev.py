"""Jev reads each campaign reply; plain rules over the user's thresholds pick the route."""

import asyncio
import json

import httpx
import pytest

from src.agent_runtime import jev
from src.agent_runtime.prefs import InboxRules

RULES = InboxRules().model_dump()


def answers(intent="interested", probs=None, needs_human=0.2, urgency=1.0, buying=2.0, competitor=0.1, meeting=0.9, confidence=0.9):
    return {
        "intent": {"type": "choice", "choice": intent, "confidence": confidence, "probabilities": probs or {intent: 0.95, "other": 0.05}},
        "needs_human": {"type": "noul", "noul": needs_human},
        "urgency": {"type": "score", "score": urgency, "legend": {"0": "a", "1": "b", "2": "c", "3": "d"}},
        "buying_signal": {"type": "score", "score": buying, "legend": {"0": "a", "1": "b", "2": "c", "3": "d"}},
        "competitor": {"type": "noul", "noul": competitor},
        "meeting_ok": {"type": "noul", "noul": meeting},
    }


def client_returning(*responses):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        status, body = responses[min(len(calls) - 1, len(responses) - 1)]
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr(jev.settings, "JEV_API_KEY", "test-key", raising=False)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(jev.asyncio, "sleep", lambda s: real_sleep(0))  # no real backoff in tests


def test_read_reply_sends_the_questions_and_normalises_scores():
    client, calls = client_returning((200, {"model": "jev-1.13.0", "answers": answers()}))
    read = asyncio.run(jev.read_reply("Sounds good, can we talk Tuesday?", {"subject": "Hello"}, client=client))
    assert set(calls[0]["questions"]) == set(jev.QUESTIONS) and calls[0]["state"]["subject"] == "Hello"
    assert read["intent"] == "interested" and read["urgency"] == pytest.approx(0.333, abs=0.001) and read["model"] == "jev-1.13.0"


def test_rate_limits_are_retried():
    client, calls = client_returning((429, {}), (200, {"answers": answers()}))
    assert asyncio.run(jev.read_reply("hi", client=client))["intent"] == "interested" and len(calls) == 2


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(jev.settings, "JEV_API_KEY", "", raising=False)
    with pytest.raises(jev.JevError, match="Settings"):
        asyncio.run(jev.ask("x", {}))


@pytest.mark.parametrize("read,expected", [
    ({"intent": "unsubscribe", "intents": {"unsubscribe": 0.97}, "intent_confidence": 0.97}, "suppress"),
    ({"intent": "out_of_office", "intents": {"out_of_office": 0.95}, "intent_confidence": 0.95}, "auto_reply"),
    ({"intent": "question", "intents": {"question": 0.9}, "intent_confidence": 0.9, "needs_human": 0.85}, "handoff"),
    ({"intent": "question", "intents": {"question": 0.9}, "intent_confidence": 0.9, "urgency": 1.0}, "handoff"),
    ({"intent": "other", "intents": {"other": 0.4}, "intent_confidence": 0.3}, "handoff"),
    ({"intent": "interested", "intents": {"interested": 0.9}, "intent_confidence": 0.9, "meeting_ok": 0.9}, "propose_meeting"),
    ({"intent": "interested", "intents": {"interested": 0.9}, "intent_confidence": 0.9, "meeting_ok": 0.2}, "handoff"),
    ({"intent": "not_now", "intents": {"not_now": 0.8}, "intent_confidence": 0.8}, "snooze"),
    ({"intent": "objection", "intents": {"objection": 0.8}, "intent_confidence": 0.8}, "answer"),
    ({"intent": "other", "intents": {"other": 0.8}, "intent_confidence": 0.8, "competitor": 0.9}, "answer"),
])
def test_routes(read, expected):
    assert jev.route(read, RULES) == expected


def test_user_thresholds_change_the_route():
    read = {"intent": "question", "intents": {"question": 0.9}, "intent_confidence": 0.9, "needs_human": 0.6}
    assert jev.route(read, RULES) == "answer"
    assert jev.route(read, {**RULES, "handoff": 0.5}) == "handoff"


def test_an_openrouter_key_reads_the_reply_through_openrouter_with_the_same_reading(monkeypatch):
    monkeypatch.setattr(jev.settings, "JEV_API_KEY", "sk-or-v1-test", raising=False)
    said = {"intent": {"choice": "objection", "probabilities": {"objection": 0.8, "question": 0.15, "other": 0.05}},
            "needs_human": 0.3, "urgency": 1, "buying_signal": 2, "competitor": 0.9, "meeting_ok": 0.05}
    urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append((str(request.url), json.loads(request.content)["model"]))
        return httpx.Response(200, json={"model": "typesafe/jev-router", "choices": [{"message": {"content": "```json\n" + json.dumps(said) + "\n```"}}]})

    read = asyncio.run(jev.read_reply("we use other services, why should we go with you?", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert urls == [("https://openrouter.ai/api/v1/chat/completions", "typesafe/jev-router")]
    assert (read["intent"], read["intent_confidence"], read["competitor"], read["urgency"], read["buying_signal"]) == ("objection", 0.8, 0.9, 0.333, 0.667)
    assert jev.route(read, RULES) == "answer"


def test_an_openrouter_answer_without_json_is_an_error_not_a_guess(monkeypatch):
    monkeypatch.setattr(jev.settings, "JEV_API_KEY", "sk-or-v1-test", raising=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []})))
    with pytest.raises(jev.JevError):
        asyncio.run(jev.ask({"reply": "hi"}, jev.QUESTIONS, client=client))
