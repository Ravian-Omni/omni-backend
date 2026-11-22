"""LLM configuration manager with local API key management.

This module constructs LLM configurations from locally stored API keys
and a model mapping file. No cloud dependency.
"""

import copy
import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from src.configs.settings import settings


_MODEL_MAPPING: dict[str, Any] | None = None


def _load_model_mapping() -> dict[str, Any]:
    """Load the model mapping from the local JSON file."""
    global _MODEL_MAPPING
    if _MODEL_MAPPING is None:
        mapping_path = (
            Path(__file__).parent.parent.parent / "configs" / "llm_model_mapping.json"
        )
        with open(mapping_path, "r") as f:
            _MODEL_MAPPING = json.load(f)
    return _MODEL_MAPPING


_PROVIDER_KEY_ATTRS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "together": "TOGETHER_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "brave": "BRAVE_API_KEY",
    "composio": "COMPOSIO_API_KEY",
}


class LLMConfigManager:
    """LLM Configuration Manager using local API keys and model mapping.

    Constructs config dicts from user-provided API keys (via settings)
    and a static model mapping file. Caches results for performance.
    """

    _cache: dict[str, Any] = {}
    _cache_time: float = 0

    @classmethod
    def get_config(cls, config_name: str) -> dict[str, Any]:
        """Get LLM configuration by name.

        Args:
            config_name: Name of the configuration to retrieve.

        Returns:
            Dictionary containing config_list with the requested configuration.

        Raises:
            ValueError: If config_name is not found in available configurations.
        """
        configs = cls._get_all_configs()

        if config_name not in configs:
            available = list(configs.keys())
            raise ValueError(
                f"Config '{config_name}' not found. Available: {available}"
            )

        config_data = copy.deepcopy(configs[config_name])
        return {"config_list": [config_data]}

    @classmethod
    def get_available_configs(cls) -> list:
        """Get list of available configuration names."""
        configs = cls._get_all_configs()
        return list(configs.keys())

    @classmethod
    def _get_all_configs(cls) -> dict[str, Any]:
        """Build all configs from local model mapping and API keys."""
        if cls._cache:
            return cls._cache

        mapping = _load_model_mapping()

        configs = {}
        for config_name, info in mapping.items():
            provider = info.get("provider", "")
            attr_name = _PROVIDER_KEY_ATTRS.get(provider)
            api_key = getattr(settings, attr_name, None) if attr_name else None

            config_entry: dict[str, Any] = {"api_key": api_key or ""}
            if info.get("model"):
                config_entry["model"] = info["model"]
            # Pass through extra request params from the mapping (e.g. extra_body)
            config_entry.update(
                {k: v for k, v in info.items() if k not in ("provider", "model")}
            )

            # AutoGen needs api_type for non-OpenAI providers
            if provider == "anthropic":
                config_entry["api_type"] = "anthropic"

            configs[config_name] = config_entry

        cls._cache = configs
        cls._cache_time = time.time()
        logger.info(f"Built LLM configs for {len(configs)} entries from local keys")
        return cls._cache

    @classmethod
    def clear_cache(cls):
        """Clear the configuration cache."""
        cls._cache = {}
        cls._cache_time = 0

    @classmethod
    def refresh_configs(cls) -> bool:
        """Rebuild configurations from current settings."""
        cls.clear_cache()
        cls._get_all_configs()
        return True

    @classmethod
    def is_server_available(cls) -> bool:
        """Local mode is always available."""
        return True

    @classmethod
    def get_cache_info(cls) -> dict[str, Any]:
        """Get cache status information."""
        return {
            "has_cache": bool(cls._cache),
            "config_count": len(cls._cache) if cls._cache else 0,
            "cache_time": cls._cache_time,
            "cache_age_seconds": (
                time.time() - cls._cache_time if cls._cache_time else 0
            ),
            "mode": "local",
        }


# Convenience functions
def get_llm_config(config_name: str) -> dict[str, Any]:
    """Get LLM configuration by name."""
    return LLMConfigManager.get_config(config_name)


def list_configs() -> list:
    """List available configuration names."""
    return LLMConfigManager.get_available_configs()


def clear_llm_cache():
    """Clear LLM configuration cache."""
    LLMConfigManager.clear_cache()


def refresh_llm_configs() -> bool:
    """Rebuild configurations from current settings."""
    return LLMConfigManager.refresh_configs()


def get_cache_info() -> dict[str, Any]:
    """Get cache information and status."""
    return LLMConfigManager.get_cache_info()


def is_server_available() -> bool:
    """Local mode is always available."""
    return True
