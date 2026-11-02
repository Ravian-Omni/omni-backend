"""Settings shows which model runs tasks, chat and the agents, and never a key."""

from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.settings import settings
from src.services.settings_service import SettingsService


def test_models_in_use_names_the_model_not_the_key(monkeypatch):
    luna = {"config_list": [{"model": "gpt-5.6-luna", "api_key": "sk-secret", "extra_body": {"reasoning_effort": "none"}}]}
    monkeypatch.setattr(LLMConfigManager, "get_config", classmethod(lambda cls, name: luna))
    monkeypatch.setattr(settings, "AGENT_PROVIDER", "openai")
    monkeypatch.setattr(settings, "AGENT_MODEL", None)
    models = SettingsService.models_in_use()
    assert models == {"tasks": {"provider": "openai", "model": "gpt-5.6-luna"}, "agents": {"provider": "openai", "model": "gpt-5.6-luna"}}
    assert "sk-secret" not in str(models)

    monkeypatch.setattr(settings, "AGENT_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "AGENT_MODEL", "claude-haiku-4-5-20251001")
    assert SettingsService.models_in_use()["agents"] == {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}


def test_no_default_model_still_answers(monkeypatch):
    def missing(cls, name):
        raise ValueError("Config 'default' not found")
    monkeypatch.setattr(LLMConfigManager, "get_config", classmethod(missing))
    monkeypatch.setattr(settings, "AGENT_PROVIDER", "openai")
    assert SettingsService.models_in_use()["tasks"] == {"provider": "openai", "model": ""}
