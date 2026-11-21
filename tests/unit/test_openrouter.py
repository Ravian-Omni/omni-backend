"""OpenRouter behind one switch (contract [28]): DAXAGENT_AGENT_PROVIDER=openrouter moves every OpenAI model to OpenRouter;
unset, DAX runs as before. The key alone switches nothing. No live call: OpenRouter's address is stubbed."""

import asyncio
import json

import httpx
import pytest
import respx

from src.agent_runtime import llm
from src.agent_runtime.openai_runner import OpenAIRunner
from src.configs.llm_configs_manager import LLMConfigManager, _load_model_mapping
from src.configs.settings import settings

OPENROUTER = "https://openrouter.ai/api/v1"


@pytest.fixture
def provider(monkeypatch):
    """Set the switch (and the keys every app may hold); the config table is rebuilt for each setting."""
    def use(value: str):
        monkeypatch.setattr(settings, "AGENT_PROVIDER", value)
        monkeypatch.setattr(settings, "AGENT_MODEL", None)
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-openai")
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-key")
        LLMConfigManager.clear_cache()
        return {name: LLMConfigManager.get_config(name)["config_list"][0] for name in _load_model_mapping()}

    yield use
    LLMConfigManager.clear_cache()


def test_with_the_switch_unset_every_model_is_as_before_even_with_the_key_present(provider):
    configs = provider("openai")
    mapping = _load_model_mapping()
    for name, info in mapping.items():
        if info.get("provider") == "openai":
            assert configs[name]["model"] == info["model"] and "base_url" not in configs[name] and configs[name]["api_key"] == "sk-openai"
            assert configs[name].get("extra_body") == info.get("extra_body")


def test_with_the_switch_on_openai_models_move_to_openrouter_and_the_rest_stay(provider):
    configs, mapping = provider("openrouter"), _load_model_mapping()
    moved = [n for n, i in mapping.items() if i.get("provider") == "openai" and n != "browser_llm_config"]
    assert moved and all(configs[n] == {"api_key": "sk-or-key", "base_url": OPENROUTER, "model": "deepseek/deepseek-v4.1-flash-1017"} for n in moved)
    assert configs["browser_llm_config"]["model"] == mapping["browser_llm_config"]["model"] and configs["browser_llm_config"]["api_key"] == "sk-openai"
    others = [n for n, i in mapping.items() if i.get("provider") not in ("openai",)]
    assert all("base_url" not in configs[n] for n in others)


def test_the_persona_runner_takes_openrouter_and_sends_no_openai_only_extras(provider):
    provider("openrouter")
    cfg = OpenAIRunner.model_config()
    assert (cfg["model"], cfg["base_url"], cfg["api_key"], cfg["extra_body"]) == ("deepseek/deepseek-v4.1-flash-1017", OPENROUTER, "sk-or-key", {})
    provider("openai")
    assert OpenAIRunner.model_config()["extra_body"] == _load_model_mapping()["default"]["extra_body"]  # unchanged when off


@respx.mock
def test_a_call_reaches_openrouter_with_its_own_key_never_the_openai_key(provider):
    provider("openrouter")
    route = respx.post(f"{OPENROUTER}/chat/completions").mock(return_value=httpx.Response(200, json={
        "id": "x", "object": "chat.completion", "created": 0, "model": "deepseek/deepseek-v4.1-flash-1017",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hello from the stub"}}]}))
    assert asyncio.run(llm.complete("system", "say hello")) == "hello from the stub"
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sk-or-key" and "sk-openai" not in str(sent.headers)
    assert json.loads(sent.content)["model"] == "deepseek/deepseek-v4.1-flash-1017" and "reasoning_effort" not in sent.content.decode()
